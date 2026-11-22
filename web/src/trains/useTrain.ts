import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type TrainDetail } from "../api/client";
import { useFeed } from "../feed/context";
import { useUi } from "../state";

/** While replaying, a train's details are fetched for the moment shown, rounded to this much clock time. */
function bucketMs(speed: number): number {
  return speed >= 60 ? 5 * 60_000 : 60_000;
}

/** The replayed moment rounded down to a bucket, or null when live; re-renders as the bucket moves on. */
function useReplayMoment(): number | null {
  const feed = useFeed();
  const playback = useUi((state) => state.playback);
  const [moment, setMoment] = useState<number | null>(null);
  useEffect(() => {
    if (playback.mode !== "replay") {
      setMoment(null);
      return;
    }
    const size = bucketMs(playback.speed);
    const update = () => setMoment(Math.floor(feed.now() / size) * size);
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [feed, playback]);
  return moment;
}

/** A train's details for the panel and its route on the map, refreshed every 30 s while it's selected. */
export function useTrain(rid: string | null) {
  const moment = useReplayMoment();
  return useQuery({
    queryKey: ["train", rid, moment],
    enabled: rid !== null,
    refetchInterval: moment === null ? 30_000 : false,
    // While replaying, keep showing the train as the moment moves on rather than flashing a loading state
    placeholderData: (previous, query) => (query?.queryKey[1] === rid ? previous : undefined),
    queryFn: async (): Promise<TrainDetail | null> => {
      const { data, response } = await api.GET("/api/trains/{rid}", {
        params: {
          path: { rid: rid as string },
          query: moment === null ? {} : { at: new Date(moment).toISOString() },
        },
      });
      if (response.status === 404) return null;
      if (!data) throw new Error(`Train ${rid}: ${response.status}`);
      // openapi-typescript writes (lon, lat) pairs as number[][] in responses but as tuples in the named schema
      return data as TrainDetail;
    },
  });
}
