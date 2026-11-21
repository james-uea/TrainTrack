// A typed client for the TrainTrack API. Types come from FastAPI's schema: run `pnpm gen:api` after changing it
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "" });

export type TrainPosition = components["schemas"]["TrainPosition"];
export type PositionsResponse = components["schemas"]["PositionsResponse"];
export type PositionChanges = components["schemas"]["PositionChanges"];
export type TrainDetail = components["schemas"]["TrainDetail"];
export type TrainStop = components["schemas"]["TrainStop"];
export type Health = components["schemas"]["Health"];
