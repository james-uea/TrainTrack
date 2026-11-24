import type { PickingInfo } from "@deck.gl/core";
import { DataFilterExtension } from "@deck.gl/extensions";
import { IconLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import MapView, { Layer, type MapRef, NavigationControl, Source, useControl } from "react-map-gl/maplibre";
import { readView, viewHash } from "../feed/address";
import { useUi } from "../state";
import { Smoother } from "../trains/motion";
import type { SegmentCache } from "../trains/segments";
import type { TrainStore } from "../trains/store";
import { useTrain } from "../trains/useTrain";
import { ARROW_MAPPING, arrowAtlas } from "./arrow";
import { drawGeojsonTrains, geojsonRenderer } from "./geojsonTrains";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const INITIAL_VIEW = { longitude: -2.5, latitude: 54.2, zoom: 5.4 };
// The Track Model's lines, served by the API, drawn under the basemap's labels
const TRACK_TILES = [`${window.location.origin}/tiles/track/{z}/{x}/{y}.pbf`];
const LABELS_FROM = "waterway_line_label";
// From this zoom trains are drawn as arrows pointing the way they're going
const ARROW_ZOOM = 9;
// Hides trains in the legend's switched-off delay bands on the GPU, keeping indexes stable for picking
const FILTER = [new DataFilterExtension({ filterSize: 1 })];

/** Adds the overlay the draw loop feeds. It's made by TrainMap, so remounts (StrictMode) add the same one back. */
function DeckOverlay({ overlay }: { overlay: MapboxOverlay }) {
  useControl(() => overlay);
  return null;
}

/** Frame times for `?bench=1`: how long each animation frame took to place and hand over every train. */
export const frameTimes: number[] = [];

export function TrainMap({ store, segments }: { store: TrainStore; segments: SegmentCache }) {
  const [overlay] = useState(() => new MapboxOverlay({ interleaved: false, layers: [] }));
  const [initialView] = useState(() => readView() ?? INITIAL_VIEW);
  const zoomRef = useRef(initialView.zoom);
  const mapRef = useRef<MapRef>(null);
  const select = useUi((state) => state.select);
  const selected = useUi((state) => state.selected);
  const atlas = useMemo(() => arrowAtlas(), []);

  // The selected train's route, drawn under the trains; the draw loop reads it from a ref so it never restarts
  const { data: train } = useTrain(selected);
  const route = train?.rid === selected ? train?.route : undefined;
  const routeLayer = useMemo(
    () =>
      route && route.length > 1
        ? new PathLayer({
            id: "selected-route",
            data: [route],
            getPath: (path: [number, number][]) => path,
            getColor: [29, 29, 31, 150],
            getWidth: 4,
            widthUnits: "pixels",
            capRounded: true,
            jointRounded: true,
          })
        : null,
    [route],
  );
  const hiddenBands = useUi((state) => state.hiddenBands);
  const operator = useUi((state) => state.operator?.code ?? null);
  const selectedRef = useRef({ rid: selected, routeLayer, hiddenBands, operator });
  selectedRef.current = { rid: selected, routeLayer, hiddenBands, operator };

  // Fly to whatever search picked
  const focus = useUi((state) => state.focus);
  useEffect(() => {
    if (focus) mapRef.current?.flyTo({ center: [focus.lon, focus.lat], zoom: focus.zoom, duration: 1200 });
  }, [focus]);

  useEffect(() => {
    let frame = 0;
    let revision = -1;
    let filtered: ReadonlySet<string> | null = null;
    let filteredOperator: string | null = null;
    let filteredRevision = -1;
    let visible = new Float32Array(0);
    let positions = new Float32Array(0);
    let angles = new Float32Array(0);
    const segment = (key: string) => segments.get(key);
    const smoother = new Smoother();

    const draw = () => {
      frame = requestAnimationFrame(draw);
      if (!store.clock.ready) return;
      const started = performance.now();

      const trains = store.order;
      if (revision !== store.revision) {
        revision = store.revision;
        positions = new Float32Array(trains.length * 2);
        angles = new Float32Array(trains.length);
        smoother.keepOnly(new Set(trains.map((train) => train.rid)));
      }
      const now = store.clock.now();
      for (let i = 0; i < trains.length; i++) {
        const place = smoother.place(trains[i] as (typeof trains)[number], now, segment);
        positions[i * 2] = place.lon;
        positions[i * 2 + 1] = place.lat;
        angles[i] = -(place.bearing ?? 0); // deck.gl turns anticlockwise; bearings run clockwise
      }

      if (geojsonRenderer) {
        const map = mapRef.current?.getMap();
        if (map) drawGeojsonTrains(map, positions, store.colours, trains.length);
        frameTimes.push(performance.now() - started);
        return;
      }

      const { rid, routeLayer, hiddenBands, operator } = selectedRef.current;
      if (filtered !== hiddenBands || filteredOperator !== operator || filteredRevision !== store.revision) {
        filtered = hiddenBands;
        filteredOperator = operator;
        filteredRevision = store.revision;
        visible = new Float32Array(trains.length);
        for (let i = 0; i < trains.length; i++) {
          const shown =
            !hiddenBands.has(store.bands[i] ?? "unknown") && (!operator || trains[i]?.toc === operator);
          visible[i] = shown ? 1 : 0;
        }
      }

      const data = {
        length: trains.length,
        attributes: {
          getPosition: { value: positions, size: 2 },
          getColor: { value: store.colours, size: 4, normalized: true },
          getFillColor: { value: store.colours, size: 4, normalized: true },
          getAngle: { value: angles, size: 1 },
          getFilterValue: { value: visible, size: 1 },
        },
      };
      const arrows = zoomRef.current >= ARROW_ZOOM;
      const at = rid ? store.indexOf(rid) : -1;
      overlay.setProps({
        layers: [
          routeLayer,
          arrows
            ? new IconLayer({
                // Each kind has its own id: deck.gl matches layers by id, and won't carry one's state to the other
                id: "train-arrows",
                data,
                iconAtlas: atlas as unknown as string,
                iconMapping: ARROW_MAPPING,
                getIcon: () => "arrow",
                getSize: 22,
                sizeUnits: "pixels",
                pickable: true,
                extensions: FILTER,
                filterRange: [1, 1],
              })
            : new ScatterplotLayer({
                id: "train-dots",
                data,
                getRadius: 3.5,
                radiusUnits: "pixels",
                stroked: true,
                getLineColor: [255, 255, 255, 200],
                lineWidthUnits: "pixels",
                getLineWidth: 0.75,
                pickable: true,
                extensions: FILTER,
                filterRange: [1, 1],
              }),
          at >= 0 &&
            new ScatterplotLayer({
              id: "selected-train",
              data: [at],
              getPosition: () => [positions[at * 2] ?? 0, positions[at * 2 + 1] ?? 0],
              updateTriggers: { getPosition: now },
              getRadius: arrows ? 15 : 8,
              radiusUnits: "pixels",
              filled: false,
              stroked: true,
              getLineColor: [29, 29, 31, 230],
              lineWidthUnits: "pixels",
              getLineWidth: 2,
            }),
        ],
        getTooltip: ({ index }: PickingInfo) => {
          const train = store.order[index];
          if (index < 0 || !train) return null;
          const delay =
            train.delay === null ? "no report yet" : train.delay <= 0 ? "on time" : `${train.delay} min late`;
          return `${train.headcode ?? train.rid} (${train.toc ?? "?"}): ${delay}`;
        },
        onClick: ({ index }: PickingInfo) => {
          const train = store.order[index];
          select(train ? train.rid : null);
        },
      });
      frameTimes.push(performance.now() - started);
      if (frameTimes.length > 10_000) frameTimes.splice(0, 5_000);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [overlay, store, segments, atlas, select]);

  return (
    <MapView
      ref={mapRef}
      initialViewState={initialView}
      mapStyle={STYLE}
      dragRotate={false}
      touchPitch={false}
      onZoom={(event) => {
        zoomRef.current = event.viewState.zoom;
      }}
      onMoveEnd={(event) => {
        // The view goes in the address's hash, so a shared link opens the same place
        const url = new URL(window.location.href);
        url.hash = viewHash(event.viewState);
        window.history.replaceState(null, "", url);
      }}
      style={{ position: "absolute", inset: 0 }}
    >
      <Source id="track" type="vector" tiles={TRACK_TILES} minzoom={5} maxzoom={14}>
        <Layer
          id="track"
          type="line"
          source-layer="track"
          beforeId={LABELS_FROM}
          paint={{
            "line-color": "#8a8f98",
            "line-opacity": ["interpolate", ["linear"], ["zoom"], 5, 0.35, 10, 0.6],
            "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 5, 0.4, 10, 1, 15, 2.5],
          }}
        />
      </Source>
      <NavigationControl position="top-right" showCompass={false} />
      <DeckOverlay overlay={overlay} />
    </MapView>
  );
}
