#!/usr/bin/env bash
# Quick ways to start parts of TrainTrack. Run ./run.sh with no arguments for the list.
set -euo pipefail
cd "$(dirname "$0")"

REPLAY_DEFAULT="2026-11-21T14:40Z"

usage() {
  cat <<'EOF'
Usage: ./run.sh <command> [args]

Containers
  db                 Postgres (PostGIS) and Adminer only
  up                 everything in Docker: db, adminer, consumer, td, recorder, timetable, api (map on :8000)
  down               stop the containers
  logs [service]     follow container logs

Local processes (start the db first, or use `dev`)
  api [clock]        the API on :8000; clock is now (default), fixed:<ISO time> or replay:<ISO time>
  web                the map's dev server on :5173 (installs packages the first time)
  consumer           the Push Port consumer
  td                 the Train Describer consumer (berth steps)
  recorder           records the map every 5 s, so it can be replayed
  backfill FROM TO   computes replay frames for a past window (default: 21 Nov 13:50-14:51 UTC)

Together
  dev [clock]        db, then the API and the map dev server; Ctrl+C stops both
  live               dev on the live clock, plus both consumers feeding the db and the recorder
  replay [ISO time]  dev replaying a past moment (default 2026-11-21T14:40Z)
EOF
}

db() { docker compose up -d db adminer; }

wait_for_db() {
  for _ in $(seq 1 30); do
    docker compose exec -T db pg_isready -q && return
    sleep 1
  done
  echo "Postgres didn't come up" >&2
  exit 1
}

api() { uv run src/api.py --clock "${1:-now}"; }

web() {
  [ -d web/node_modules ] || pnpm --dir web install
  pnpm --dir web dev
}

consumer() { uv run src/consumer.py; }

td() { uv run src/td_consumer.py; }

recorder() { uv run src/recorder.py; }

# Runs each argument as a background command and stops them all (and anything they started) on Ctrl+C
together() {
  set -m # each part gets its own process group, so stopping one stops its children (uv's python, vite's node)
  local pids=()
  for cmd in "$@"; do
    $cmd &
    pids+=($!)
  done
  trap 'trap - INT TERM EXIT; for p in "${pids[@]}"; do kill -- "-$p" 2>/dev/null || true; done' INT TERM EXIT
  wait
}

dev() {
  db && wait_for_db
  echo "Map: http://localhost:5173   API: http://localhost:8000   Adminer: http://localhost:8080"
  together "api ${1:-now}" web
}

case "${1:-}" in
  db) db ;;
  up) docker compose up -d --build && echo "Map: http://localhost:8000" ;;
  down) docker compose down ;;
  logs) shift; docker compose logs -f "$@" ;;
  api) api "${2:-now}" ;;
  web) web ;;
  consumer) consumer ;;
  td) td ;;
  recorder) recorder ;;
  backfill) uv run src/recorder.py --backfill "${2:-2026-11-21T13:50Z}" "${3:-2026-11-21T14:51Z}" ;;
  dev) dev "${2:-now}" ;;
  live)
    db && wait_for_db
    echo "Map: http://localhost:5173   API: http://localhost:8000"
    together consumer td recorder "api now" web
    ;;
  replay) dev "replay:${2:-$REPLAY_DEFAULT}" ;;
  *) usage ;;
esac
