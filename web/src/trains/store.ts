// Every train the map shows, kept outside React: the animation loop reads it on every frame
import type { PositionChanges, PositionsResponse, ReplayFrame, TrainPosition } from "../api/client";
import { ServerClock } from "../feed/serverClock";
import { DELAY_BANDS, type DelayBand, delayBand } from "./delay";
import { isMoving } from "./motion";
import { type SegmentCache, segmentKey } from "./segments";

const BAND_COLOURS = new Map(DELAY_BANDS.map(({ band, colour }) => [band, colour]));

export class TrainStore {
  readonly clock = new ServerClock();
  trains = new Map<string, TrainPosition>();
  version = -1;
  active = 0;
  clockName = "";
  /** Changes whenever the set of trains or their colours change, so drawing can rebuild its arrays. */
  revision = 0;
  // In draw order, rebuilt on each revision
  order: TrainPosition[] = [];
  colours = new Uint8Array(0);
  bands: DelayBand[] = []; // each train's delay band, in draw order
  private indexes = new Map<string, number>();

  constructor(private segments: SegmentCache) {}

  loadSnapshot(snapshot: PositionsResponse) {
    this.trains = new Map(snapshot.trains.map((train) => [train.rid, train]));
    this.accept(snapshot.version, snapshot.at, snapshot.clock, snapshot.active);
  }

  applyChanges(changes: PositionChanges) {
    for (const rid of changes.removed) this.trains.delete(rid);
    for (const train of changes.trains) this.trains.set(train.rid, train);
    this.accept(changes.version, changes.at, changes.clock, changes.active);
  }

  /** Stored frames, in order: a keyframe replaces every train, the rest add, update and remove some. */
  applyFrames(frames: ReplayFrame[]) {
    const last = frames.at(-1);
    if (!last) return;
    for (const frame of frames) {
      if (frame.keyframe) this.trains = new Map(frame.trains.map((train) => [train.rid, train]));
      else {
        for (const rid of frame.removed) this.trains.delete(rid);
        for (const train of frame.trains) this.trains.set(train.rid, train);
      }
    }
    this.accept(this.version + 1, last.at, `replay:${last.source}`, last.active);
  }

  /** Drop every train, when switching between live and replay. */
  clear() {
    this.trains = new Map();
    this.accept(this.version + 1, new Date().toISOString(), "", 0);
  }

  /** Where a train is in `order` (and the drawing arrays), or -1 if it isn't on the map. */
  indexOf(rid: string): number {
    return this.indexes.get(rid) ?? -1;
  }

  private accept(version: number, at: string, clock: string, active: number) {
    this.version = version;
    this.active = active;
    this.clockName = clock;
    this.clock.update(at, clock);
    this.order = [...this.trains.values()];
    this.indexes = new Map(this.order.map((train, i) => [train.rid, i]));
    this.colours = new Uint8Array(this.order.length * 4);
    this.bands = this.order.map((train) => delayBand(train.delay));
    this.order.forEach((train, i) => {
      const [r, g, b] = BAND_COLOURS.get(this.bands[i] as DelayBand) ?? [128, 128, 128];
      this.colours.set([r, g, b, train.confidence === "low" ? 150 : 255], i * 4);
    });
    this.segments.want(
      this.order.filter(isMoving).map((train) => segmentKey(train.from_tiploc, train.to_tiploc)),
    );
    this.revision++;
  }
}
