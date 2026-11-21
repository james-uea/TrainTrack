// UI state shared between components
import { create } from "zustand";
import type { FeedStatus } from "./feed/feed";

interface UiState {
  status: FeedStatus;
  selected: string | null; // rid, kept in the address as ?train= so a train can be linked to
  setStatus: (status: FeedStatus) => void;
  select: (rid: string | null) => void;
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
  setStatus: (status) => set({ status }),
  select: (selected) => {
    setTrainInAddress(selected);
    set({ selected });
  },
}));
