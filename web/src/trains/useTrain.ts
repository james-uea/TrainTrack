import { useQuery } from "@tanstack/react-query";
import { api, type TrainDetail } from "../api/client";

/** A train's details for the panel and its route on the map, refreshed every 30 s while it's selected. */
export function useTrain(rid: string | null) {
  return useQuery({
    queryKey: ["train", rid],
    enabled: rid !== null,
    refetchInterval: 30_000,
    queryFn: async (): Promise<TrainDetail | null> => {
      const { data, response } = await api.GET("/api/trains/{rid}", {
        params: { path: { rid: rid as string } },
      });
      if (response.status === 404) return null;
      if (!data) throw new Error(`Train ${rid}: ${response.status}`);
      // openapi-typescript writes (lon, lat) pairs as number[][] in responses but as tuples in the named schema
      return data as TrainDetail;
    },
  });
}
