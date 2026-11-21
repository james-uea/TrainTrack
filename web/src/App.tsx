import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";

export function App() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await api.GET("/api/health")).data,
    refetchInterval: 5000,
  });
  return (
    <main>
      <h1>TrainTrack</h1>
      <p>{health.data ? `${health.data.placed} trains placed at ${health.data.at}` : "Connecting…"}</p>
    </main>
  );
}
