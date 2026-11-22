// The address holds what's on screen, so a link opens the same moment, speed and view:
// ?at=2026-11-12T07:40:00Z&speed=10&paused=1&train=<rid>#map=11/51.4642/-0.1704
import { replayStart } from "./feed";
import { SPEEDS, type Speed } from "./playback";

export interface PlaybackAddress {
  at: number | null; // null when live
  speed: Speed;
  playing: boolean;
}

export interface View {
  longitude: number;
  latitude: number;
  zoom: number;
}

export function readPlayback(search = window.location.search): PlaybackAddress {
  const params = new URLSearchParams(search);
  const speed = Number(params.get("speed"));
  return {
    at: replayStart(search),
    speed: (SPEEDS as readonly number[]).includes(speed) ? (speed as Speed) : 1,
    playing: params.get("paused") !== "1",
  };
}

/** `url` with the playback written into it (and taken out when live). */
export function writePlayback(url: URL, playback: PlaybackAddress): URL {
  const next = new URL(url);
  const params = next.searchParams;
  params.delete("at");
  params.delete("speed");
  params.delete("paused");
  if (playback.at !== null) {
    params.set("at", new Date(Math.floor(playback.at / 1000) * 1000).toISOString().replace(".000Z", "Z"));
    if (playback.speed !== 1) params.set("speed", String(playback.speed));
    if (!playback.playing) params.set("paused", "1");
  }
  return next;
}

export function readView(hash = window.location.hash): View | null {
  const match = /map=([\d.]+)\/(-?[\d.]+)\/(-?[\d.]+)/.exec(hash);
  if (!match) return null;
  const [zoom, latitude, longitude] = match.slice(1).map(Number) as [number, number, number];
  if (![zoom, latitude, longitude].every(Number.isFinite)) return null;
  return { zoom, latitude, longitude };
}

export function viewHash({ zoom, latitude, longitude }: View): string {
  return `#map=${zoom.toFixed(2)}/${latitude.toFixed(4)}/${longitude.toFixed(4)}`;
}
