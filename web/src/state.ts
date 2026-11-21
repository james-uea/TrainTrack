// UI state shared between components
import { create } from "zustand";
import type { FeedStatus } from "./feed/feed";

interface UiState {
  status: FeedStatus;
  selected: string | null; // rid
  setStatus: (status: FeedStatus) => void;
  select: (rid: string | null) => void;
}

export const useUi = create<UiState>((set) => ({
  status: "connecting",
  selected: null,
  setStatus: (status) => set({ status }),
  select: (selected) => set({ selected }),
}));
