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

# A train can only go on from one link to another at a node if the track turns by at most this much there (degrees).
# Points diverge by a few degrees; going back the way it came along another branch of a junction is a reversal, which
# a train can't do between two stops. An undirected route did that in 225 of the 344 paths that ran more than 1.4
# times the straight distance on 25 Nov, such as Paddington low level to Bond Street: 6.1 km for 2.1 km
MAX_TURN = 45.0
# How far along a link to look for its heading as it leaves a node (metres)
HEADING_LOOKAHEAD = 20.0


class TrackGraph:

    def __init__(self, links: Iterable[Link], max_turn: float = MAX_TURN):
        self.links: dict[str, Link] = {}
        self.coords: dict[int, tuple[float, float]] = {}
        self.graph = nx.Graph()  # nodes joined by links, for connectivity
        at_node: dict[int, list[str]] = {}
        for link in links:
            self.links[link.asset_id] = link
            self.coords[link.from_node] = link.line.coords[0]
            self.coords[link.to_node] = link.line.coords[-1]
            # Of parallel links between the same two nodes, keep the shortest
            existing = self.graph.get_edge_data(link.from_node, link.to_node)
            if existing is None or link.length < existing["weight"]:
                self.graph.add_edge(link.from_node, link.to_node, weight=link.length, link=link.asset_id)
            if link.from_node != link.to_node:
                at_node.setdefault(link.from_node, []).append(link.asset_id)
                at_node.setdefault(link.to_node, []).append(link.asset_id)

        # Routes run over moves: (link, node) is being at `node` having come along `link`. From there a train can go
        # on along any other link at that node the track turns onto gently, to the node at its far end
        self.moves = nx.DiGraph()
        headings = {(asset_id, node): self._heading(self.links[asset_id], node)
                    for node, asset_ids in at_node.items() for asset_id in asset_ids}
        for node, asset_ids in at_node.items():
            for arrived in asset_ids:
                coming = (headings[(arrived, node)] + 180) % 360  # the way a train arriving along it is heading
                for leaving in asset_ids:
                    if leaving != arrived and _turn(coming, headings[(leaving, node)]) <= max_turn:
                        link = self.links[leaving]
                        self.moves.add_edge((arrived, node), (leaving, self._far_end(link, node)), weight=link.length)

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

    def route(self, start: Snap | list[Snap], end: Snap | list[Snap], reversing: bool = False) -> Path | None:
        """
        The shortest path along the track between two points that a train could run without reversing, or None if
        there's none. It may leave the first point either way and reach the last from either side. Each end can be
        several candidate snaps (say one per parallel track) and the best pair is used, so a route doesn't cross to
        the other line and back because its ends snapped to different tracks. `reversing` allows turning back at
        any node, as if the track ran every way.
        """
        starts = start if isinstance(start, list) else [start]
        ends = end if isinstance(end, list) else [end]
        if reversing:
            return self._route_reversing(starts, ends)
        coords = {START: self.point(starts[0]), END: self.point(ends[0])}

        def heuristic(a, b):
            return math.dist(coords.get(a) or self.coords[a[1]], coords.get(b) or self.coords[b[1]])

        moves = self.moves
        added = [START, END]  # virtual nodes, and moves only a route's start leads to: all taken out again
        try:
            for snap in starts:
                link = self.links[snap.asset_id]
                if link.from_node != link.to_node:
                    for node, along in ((link.from_node, snap.along), (link.to_node, link.length - snap.along)):
                        if not moves.has_node((snap.asset_id, node)):
                            added.append((snap.asset_id, node))
                        self._add_virtual_edge(START, (snap.asset_id, node), along, snap)
            for snap in ends:
                link = self.links[snap.asset_id]
                for node, along in ((link.from_node, snap.along), (link.to_node, link.length - snap.along)):
                    # Into the end link from any move that could carry on along it
                    onward = (snap.asset_id, self._far_end(link, node))
                    for move in list(moves.predecessors(onward)) if moves.has_node(onward) else []:
                        if move[1] == node:
                            self._add_virtual_edge(move, END, along, snap)
            for a in starts:
                for b in ends:
                    if a.asset_id == b.asset_id:
                        self._add_virtual_edge(START, END, abs(a.along - b.along), (a, b))

            try:
                nodes = nx.astar_path(moves, START, END, heuristic=heuristic, weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return None
            first_hop = moves[nodes[0]][nodes[1]]["snap"]
            last_hop = moves[nodes[-2]][nodes[-1]]["snap"]
        finally:
            moves.remove_nodes_from(added)

        return self._path_line(nodes, first_hop, last_hop)

    def _route_reversing(self, starts: list[Snap], ends: list[Snap]) -> Path | None:
        """The shortest path between two points over the links as an undirected graph of nodes."""
        coords = {START: self.point(starts[0]), END: self.point(ends[0])}
        graph = self.graph

        def heuristic(a, b):
            return math.dist(coords.get(a) or self.coords[a], coords.get(b) or self.coords[b])

        def join(a, b, weight, snap):
            if not graph.has_edge(a, b) or graph[a][b]["weight"] > weight:
                graph.add_edge(a, b, weight=weight, snap=snap)

        try:
            for name, snaps in ((START, starts), (END, ends)):
                for snap in snaps:
                    link = self.links[snap.asset_id]
                    join(name, link.from_node, snap.along, snap)
                    join(name, link.to_node, link.length - snap.along, snap)
            for a in starts:
                for b in ends:
                    if a.asset_id == b.asset_id:
                        join(START, END, abs(a.along - b.along), (a, b))
            try:
                nodes = nx.astar_path(graph, START, END, heuristic=heuristic, weight="weight")
            except nx.NetworkXNoPath:
                return None
            first_hop, last_hop = graph[nodes[0]][nodes[1]]["snap"], graph[nodes[-2]][nodes[-1]]["snap"]
            # As moves: each link taken with the node it reaches
            moves = [START, *((graph[u][v]["link"], v) for u, v in pairwise(nodes[1:-1]))]
            if len(nodes) > 2:
                moves.insert(1, (first_hop.asset_id, nodes[1]))
            moves.append(END)
        finally:
            graph.remove_nodes_from([START, END])
        return self._path_line(moves, first_hop, last_hop)

    def _add_virtual_edge(self, a, b, weight, snap):
        """Join a virtual node to the moves, keeping the shortest way if there are several."""
        if self.moves.has_edge(a, b) and self.moves[a][b]["weight"] <= weight:
            return
        self.moves.add_edge(a, b, weight=weight, snap=snap)

    @staticmethod
    def _far_end(link: Link, node: int) -> int:
        return link.to_node if node == link.from_node else link.from_node

    @staticmethod
    def _heading(link: Link, node: int) -> float:
        """Degrees anticlockwise from east of the way along `link` leaving `node`."""
        line = link.line
        ahead = min(HEADING_LOOKAHEAD, line.length)
        if node == link.from_node:
            a, b = line.coords[0], line.interpolate(ahead)
        else:
            a, b = line.coords[-1], line.interpolate(line.length - ahead)
        return math.degrees(math.atan2(b.y - a[1], b.x - a[0])) % 360

    def _path_line(self, nodes: list, first_hop, last_hop) -> Path:
        pieces: list[list[tuple[float, float]]] = []

        if nodes == [START, END]:
            start, end = first_hop
            pieces.append(list(substring(self.links[start.asset_id].line, start.along, end.along).coords))
        else:
            # Moves are (link, node reached along it): from the start point along the first link to its node, then
            # each later link whole from the node before, then from the last node into the end point
            start, end = first_hop, last_hop
            first, last = self.links[start.asset_id], self.links[end.asset_id]
            exit_at = 0.0 if nodes[1][1] == first.from_node else first.length
            pieces.append(list(substring(first.line, start.along, exit_at).coords))
            for (_, u), (asset_id, _) in pairwise(nodes[1:-1]):
                link = self.links[asset_id]
                coords = list(link.line.coords)
                pieces.append(coords if link.from_node == u else coords[::-1])
            enter_at = 0.0 if nodes[-2][1] == last.from_node else last.length
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


def _turn(a: float, b: float) -> float:
    """The angle between two headings, 0 to 180 degrees."""
    return abs((b - a + 180) % 360 - 180)


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
