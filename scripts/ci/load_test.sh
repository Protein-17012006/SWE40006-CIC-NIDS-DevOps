#!/usr/bin/env bash
# Helpers for the load test that deploy_env.sh runs during staging and production deployments
# (NFR-02). Source it after lib.sh, from the repository root. Locust runs on the GitHub runner
# in the background while ECS replaces the app's task; scripts/load_verdict.py judges its
# statistics. LOCUST and PYTHON name the commands to run (defaults: locust, python).

# load_test_start URL DIR: start 20 Locust users against URL in the background. DIR keeps the
# process id, the start time, Locust's log and its CSV statistics.
load_test_start() {
  local url=$1 dir=$2
  mkdir -p "$dir"
  "${LOCUST:-locust}" -f tests/load/locustfile.py --headless --users 20 --spawn-rate 5 \
    --run-time 30m --host "$url" --csv "$dir/locust" --only-summary >"$dir/locust.log" 2>&1 &
  printf '%s\n' "$!" >"$dir/pid"
  date +%s >"$dir/started"
  log "load test: 20 users against $url"
}

# load_test_finish DIR MIN_SECONDS: keep the load on until MIN_SECONDS have passed since it
# started, stop Locust, print the verdict (and add it to the job summary), and return the
# verdict's exit code: 1 when any request failed or Locust never really ran.
load_test_finish() {
  local dir=$1 min_seconds=$2 pid started elapsed code=0
  pid=$(cat "$dir/pid")
  started=$(cat "$dir/started")
  elapsed=$(($(date +%s) - started))
  if ((elapsed < min_seconds)); then
    log "load test: running $((min_seconds - elapsed)) s more, so it lasts $min_seconds s"
    sleep $((min_seconds - elapsed))
  fi
  kill -TERM "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  "${PYTHON:-python}" -m scripts.load_verdict "$dir/locust_stats.csv" "$dir/locust_failures.csv" \
    >"$dir/verdict.txt" || code=$?
  cat "$dir/verdict.txt"
  # The job summary gets the table and the notes; annotations (::warning::, ::error::) stay in
  # the log, where GitHub reads them
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    grep -v '^::' "$dir/verdict.txt" >>"$GITHUB_STEP_SUMMARY" || true
  fi
  return "$code"
}

# load_test_abort DIR: stop a Locust that is still running; for a trap on EXIT.
load_test_abort() {
  local pid
  pid=$(cat "$1/pid" 2>/dev/null) || return 0
  kill -TERM "$pid" 2>/dev/null || true
}
