import type { PickingInfo } from "@deck.gl/core";
import { IconLayer, ScatterplotLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import MapView, { NavigationControl, useControl } from "react-map-gl/maplibre";
import { useUi } from "../state";
import { placeTrain } from "../trains/motion";
import type { SegmentCache } from "../trains/segments";
import type { TrainStore } from "../trains/store";
import { ARROW_MAPPING, arrowAtlas } from "./arrow";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const INITIAL_VIEW = { longitude: -2.5, latitude: 54.2, zoom: 5.4 };
// From this zoom trains are drawn as arrows pointing the way they're going
const ARROW_ZOOM = 9;

/** Adds the overlay the draw loop feeds. It's made by TrainMap, so remounts (StrictMode) add the same one back. */
function DeckOverlay({ overlay }: { overlay: MapboxOverlay }) {
  useControl(() => overlay);
  return null;
}

/** Frame times for `?bench=1`: how long each animation frame took to place and hand over every train. */
export const frameTimes: number[] = [];

export function TrainMap({ store, segments }: { store: TrainStore; segments: SegmentCache }) {
  const [overlay] = useState(() => new MapboxOverlay({ interleaved: false, layers: [] }));
  const zoomRef = useRef(INITIAL_VIEW.zoom);
  const select = useUi((state) => state.select);
  const atlas = useMemo(() => arrowAtlas(), []);

  useEffect(() => {
    let frame = 0;
    let revision = -1;
    let positions = new Float32Array(0);
    let angles = new Float32Array(0);
    const segment = (key: string) => segments.get(key);

    const draw = () => {
      frame = requestAnimationFrame(draw);
      if (!store.clock.ready) return;
      const started = performance.now();

      const trains = store.order;
      if (revision !== store.revision) {
        revision = store.revision;
        positions = new Float32Array(trains.length * 2);
        angles = new Float32Array(trains.length);
      }
      const now = store.clock.now();
      for (let i = 0; i < trains.length; i++) {
        const place = placeTrain(trains[i] as (typeof trains)[number], now, segment);
        positions[i * 2] = place.lon;
        positions[i * 2 + 1] = place.lat;
        angles[i] = -(place.bearing ?? 0); // deck.gl turns anticlockwise; bearings run clockwise
      }

      const data = {
        length: trains.length,
        attributes: {
          getPosition: { value: positions, size: 2 },
          getColor: { value: store.colours, size: 4, normalized: true },
          getFillColor: { value: store.colours, size: 4, normalized: true },
          getAngle: { value: angles, size: 1 },
        },
      };
      const arrows = zoomRef.current >= ARROW_ZOOM;
      overlay.setProps({
        layers: [
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
      initialViewState={INITIAL_VIEW}
      mapStyle={STYLE}
      dragRotate={false}
      touchPitch={false}
      onZoom={(event) => {
        zoomRef.current = event.viewState.zoom;
      }}
      style={{ position: "absolute", inset: 0 }}
    >
      <NavigationControl position="top-right" showCompass={false} />
      <DeckOverlay overlay={overlay} />
    </MapView>
  );
}
