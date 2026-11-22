import { createContext, useContext } from "react";
import type { FeedController } from "./controller";

export const FeedContext = createContext<FeedController | null>(null);

export function useFeed(): FeedController {
  const feed = useContext(FeedContext);
  if (!feed) throw new Error("useFeed outside FeedContext");
  return feed;
}
