// UI state shared between components
import { create } from "zustand";
import type { FeedStatus } from "./feed/feed";
import type { DelayBand } from "./trains/delay";

export interface Focus {
  lon: number;
  lat: number;
  zoom: number;
}

interface UiState {
  status: FeedStatus;
  selected: string | null; // rid, kept in the address as ?train= so a train can be linked to
  hiddenBands: ReadonlySet<DelayBand>; // delay bands the map leaves out
  focus: Focus | null; // where the map should fly to next
  operator: { code: string; name: string } | null; // show only this operator's trains
  setStatus: (status: FeedStatus) => void;
  select: (rid: string | null) => void;
  toggleBand: (band: DelayBand) => void;
  setHiddenBands: (bands: Iterable<DelayBand>) => void;
  focusOn: (focus: Focus) => void;
  showOperator: (operator: { code: string; name: string } | null) => void;
}

function trainInAddress(): string | null {
  return new URLSearchParams(window.location.search).get("train");
}

function setTrainInAddress(rid: string | null) {
  const url = new URL(window.location.href);
  if (rid) url.searchParams.set("train", rid);
  else url.searchParams.delete("train");
  window.history.replaceState(null, "", url);
}

export const useUi = create<UiState>((set) => ({
  status: "connecting",
  selected: trainInAddress(),
  hiddenBands: new Set(),
  focus: null,
  operator: null,
  setStatus: (status) => set({ status }),
  select: (selected) => {
    setTrainInAddress(selected);
    set({ selected });
  },
  toggleBand: (band) =>
    set(({ hiddenBands }) => {
      const next = new Set(hiddenBands);
      if (!next.delete(band)) next.add(band);
      return { hiddenBands: next };
    }),
  setHiddenBands: (bands) => set({ hiddenBands: new Set(bands) }),
  focusOn: (focus) => set({ focus }),
  showOperator: (operator) => set({ operator }),
}));
