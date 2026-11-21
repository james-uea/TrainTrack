import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { useEffect, useMemo, useState } from "react";
import { api, type Operator, type Station } from "../api/client";
import { useUi } from "../state";
import type { TrainStore } from "../trains/store";
import { matchOperators, matchStations, matchTrains } from "./match";
import styles from "./Search.module.css";

function useStations(enabled: boolean) {
  return useQuery({
    queryKey: ["stations"],
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () => (await api.GET("/api/stations")).data ?? [],
  });
}

function useOperators(enabled: boolean) {
  return useQuery({
    queryKey: ["operators"],
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () => (await api.GET("/api/operators")).data ?? [],
  });
}

/**
 * Find a station (flies the map there), an operator (shows only its trains) or a train by headcode (selects it).
 * Opened with / or Ctrl/Cmd+K.
 */
export function Search({ store }: { store: TrainStore }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const select = useUi((state) => state.select);
  const focusOn = useUi((state) => state.focusOn);
  const { data: stations = [] } = useStations(open);
  const { data: operators = [] } = useOperators(open);
  const showOperator = useUi((state) => state.showOperator);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement;
      if ((event.key === "k" && (event.metaKey || event.ctrlKey)) || (event.key === "/" && !typing)) {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const trains = useMemo(() => (open ? matchTrains(store.trains.values(), query) : []), [open, query, store]);
  const places = useMemo(() => matchStations(stations, query), [stations, query]);
  const companies = useMemo(() => matchOperators(operators, query), [operators, query]);

  const close = () => {
    setOpen(false);
    setQuery("");
  };
  const pickStation = (station: Station) => {
    focusOn({ lon: station.lon, lat: station.lat, zoom: 13 });
    close();
  };
  const pickOperator = (operator: Operator) => {
    showOperator(operator);
    close();
  };
  const pickTrain = (rid: string) => {
    const train = store.trains.get(rid);
    select(rid);
    if (train) focusOn({ lon: train.lon, lat: train.lat, zoom: 10 });
    close();
  };

  return (
    <>
      <button type="button" className={styles.opener} onClick={() => setOpen(true)}>
        Search stations, operators, headcodes <kbd>/</kbd>
      </button>
      <Command.Dialog
        open={open}
        onOpenChange={(next) => (next ? setOpen(true) : close())}
        shouldFilter={false}
        label="Search stations or trains"
        overlayClassName={styles.overlay}
        contentClassName={styles.dialog}
      >
        <Command.Input
          className={styles.input}
          value={query}
          onValueChange={setQuery}
          placeholder="Station, CRS code, operator or headcode"
        />
        <Command.List className={styles.list}>
          {query.trim() && <Command.Empty className={styles.empty}>Nothing found</Command.Empty>}
          {trains.length > 0 && (
            <Command.Group heading="Trains" className={styles.group}>
              {trains.map((train) => (
                <Command.Item
                  key={train.rid}
                  value={`train-${train.rid}`}
                  onSelect={() => pickTrain(train.rid)}
                  className={styles.item}
                >
                  <strong>{train.headcode}</strong>
                  <span className={styles.detail}>
                    {train.toc} ·{" "}
                    {train.delay === null
                      ? "no report"
                      : train.delay <= 0
                        ? "on time"
                        : `${train.delay} min late`}
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          {companies.length > 0 && (
            <Command.Group heading="Operators" className={styles.group}>
              {companies.map((operator) => (
                <Command.Item
                  key={operator.code}
                  value={`operator-${operator.code}`}
                  onSelect={() => pickOperator(operator)}
                  className={styles.item}
                >
                  {operator.name}
                  <span className={styles.detail}>show only its trains</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          {places.length > 0 && (
            <Command.Group heading="Stations" className={styles.group}>
              {places.map((station) => (
                <Command.Item
                  key={station.crs}
                  value={`station-${station.crs}`}
                  onSelect={() => pickStation(station)}
                  className={styles.item}
                >
                  {station.name}
                  <span className={styles.detail}>{station.crs}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </Command.Dialog>
    </>
  );
}
