"""
A routable graph of the Track Model, for drawing a train's path along the track between two points.

    uv run src/track_graph.py    # connectivity of the loaded track_links
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

import networkx as nx
import shapely
from shapely.geometry import LineString
from shapely.ops import substring

from config import load_config
from db import Database


@dataclass
class Link:
    asset_id: str
    from_node: int
    to_node: int
    line: LineString  # British National Grid

    @property
    def length(self) -> float:
        return self.line.length


@dataclass
class Snap:
    """A point on the track: `along` metres from the start of link `asset_id`."""
    asset_id: str
    along: float


@dataclass
class Path:
    line: LineString
    length: float


START, END = "start", "end"  # the virtual nodes a route runs between


class TrackGraph:

    def __init__(self, links: Iterable[Link]):
        self.links: dict[str, Link] = {}
        self.coords: dict[int, tuple[float, float]] = {}
        self.graph = nx.Graph()
        for link in links:
            self.links[link.asset_id] = link
            self.coords[link.from_node] = link.line.coords[0]
            self.coords[link.to_node] = link.line.coords[-1]
            # Of parallel links between the same two nodes, keep the shortest
            existing = self.graph.get_edge_data(link.from_node, link.to_node)
            if existing is None or link.length < existing["weight"]:
                self.graph.add_edge(link.from_node, link.to_node, weight=link.length, link=link.asset_id)

    @classmethod
    def from_db(cls, db: Database) -> "TrackGraph":
        return cls(
            Link(asset_id, from_node, to_node, shapely.from_wkb(wkb))
            for asset_id, from_node, to_node, wkb in db.fetch_track_links()
        )

    def components(self) -> list[int]:
        """Node counts of the connected components, largest first."""
        return sorted((len(component) for component in nx.connected_components(self.graph)), reverse=True)

    def point(self, snap: Snap) -> tuple[float, float]:
        point = self.links[snap.asset_id].line.interpolate(snap.along)
        return point.x, point.y

    def route(self, start: Snap | list[Snap], end: Snap | list[Snap]) -> Path | None:
        """
        The shortest path along the track between two points, or None if no track connects them.
        Each end can be several candidate snaps (say one per parallel track) and the best pair is used,
        so a route doesn't cross to the other line and back because its ends snapped to different tracks.
        """
        starts = start if isinstance(start, list) else [start]
        ends = end if isinstance(end, list) else [end]
        coords = {START: self.point(starts[0]), END: self.point(ends[0])}

        def heuristic(a, b):
            return math.dist(coords.get(a) or self.coords[a], coords.get(b) or self.coords[b])

        try:
            for name, snaps in ((START, starts), (END, ends)):
                for snap in snaps:
                    link = self.links[snap.asset_id]
                    self._add_virtual_edge(name, link.from_node, snap.along, snap)
                    self._add_virtual_edge(name, link.to_node, link.length - snap.along, snap)
            for a in starts:
                for b in ends:
                    if a.asset_id == b.asset_id:
                        self._add_virtual_edge(START, END, abs(a.along - b.along), (a, b))

            try:
                nodes = nx.astar_path(self.graph, START, END, heuristic=heuristic, weight="weight")
            except nx.NetworkXNoPath:
                return None
            first_hop = self.graph[nodes[0]][nodes[1]]["snap"]
            last_hop = self.graph[nodes[-2]][nodes[-1]]["snap"]
        finally:
            self.graph.remove_nodes_from([START, END])

        return self._path_line(nodes, first_hop, last_hop)

    def _add_virtual_edge(self, name, node, weight, snap):
        """Join a virtual node to the graph, keeping the shortest way in if there are several."""
        if self.graph.has_edge(name, node) and self.graph[name][node]["weight"] <= weight:
            return
        self.graph.add_edge(name, node, weight=weight, snap=snap)

    def _path_line(self, nodes: list, first_hop, last_hop) -> Path:
        pieces: list[list[tuple[float, float]]] = []

        if nodes == [START, END]:
            start, end = first_hop
            pieces.append(list(substring(self.links[start.asset_id].line, start.along, end.along).coords))
        else:
            start, end = first_hop, last_hop
            first, last = self.links[start.asset_id], self.links[end.asset_id]
            # From the start point to the first real node, then whole links, then into the end point
            exit_at = 0.0 if nodes[1] == first.from_node else first.length
            pieces.append(list(substring(first.line, start.along, exit_at).coords))
            for u, v in pairwise(nodes[1:-1]):
                link = self.links[self.graph[u][v]["link"]]
                coords = list(link.line.coords)
                pieces.append(coords if link.from_node == u else coords[::-1])
            enter_at = 0.0 if nodes[-2] == last.from_node else last.length
            pieces.append(list(substring(last.line, enter_at, end.along).coords))

        coords: list[tuple[float, float]] = []
        for piece in pieces:
            for point in piece:
                if not coords or point != coords[-1]:
                    coords.append(point)
        if len(coords) == 1:
            coords.append(coords[0])
        line = LineString(coords)
        return Path(line, line.length)


def main():
    db = Database(load_config().database_url)
    try:
        graph = TrackGraph.from_db(db)
    finally:
        db.close()
    sizes = graph.components()
    print(f"{len(graph.links):,} links, {graph.graph.number_of_nodes():,} nodes, {len(sizes):,} connected components")
    print(f"largest component: {sizes[0]:,} nodes ({100 * sizes[0] / sum(sizes):.1f}%)")
    print("next largest:", ", ".join(f"{size:,}" for size in sizes[1:11]))


if __name__ == "__main__":
    main()
