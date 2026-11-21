import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

/**
 * The alternative to deck.gl that the benchmarks compare it with (`?renderer=geojson`): trains as a MapLibre GeoJSON
 * source, rebuilt and handed to MapLibre's worker every frame. Dots only, no arrows or picking.
 */
export const geojsonRenderer = new URLSearchParams(window.location.search).get("renderer") === "geojson";

const SOURCE = "trains-geojson";

/** How many times MapLibre finished loading new train data, for `?bench=1`: the redraws the worker kept up with. */
export const geojsonUpdates = { count: 0 };

export function drawGeojsonTrains(
  map: MapLibreMap,
  positions: Float32Array,
  colours: Uint8Array,
  count: number,
) {
  if (!map.isStyleLoaded() && !map.getSource(SOURCE)) return;
  const features = new Array(count);
  for (let i = 0; i < count; i++) {
    features[i] = {
      type: "Feature",
      properties: {
        colour: `rgb(${colours[i * 4]},${colours[i * 4 + 1]},${colours[i * 4 + 2]})`,
      },
      geometry: { type: "Point", coordinates: [positions[i * 2], positions[i * 2 + 1]] },
    };
  }
  const data = { type: "FeatureCollection" as const, features };
  const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
    return;
  }
  map.addSource(SOURCE, { type: "geojson", data });
  map.on("sourcedata", (event) => {
    if (event.sourceId === SOURCE && event.isSourceLoaded && event.sourceDataType !== "metadata") {
      geojsonUpdates.count++;
    }
  });
  map.addLayer({
    id: SOURCE,
    type: "circle",
    source: SOURCE,
    paint: {
      "circle-radius": 3.5,
      "circle-color": ["get", "colour"],
      "circle-stroke-color": "rgba(255,255,255,0.8)",
      "circle-stroke-width": 0.75,
    },
  });
}
