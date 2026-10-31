#!/usr/bin/env bash
# ingest.sh ENV TARGET: run the ingestion job once in ENV and wait for it (ING-01, ING-09).
# TARGET is an S3 key under raw/ (ingest that file), reconcile (re-ingest what the deployed
# contracts read differently) or status (log each dataset). The wait ends after
# TASK_TIMEOUT_MINUTES (default 120): the 4 GB day file takes a while.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

usage="usage: ingest.sh development|test|staging|production raw/<key>|reconcile|status"
env_name=${1:-}
target=${2:-}
case "$env_name" in
  development | test | staging | production) ;;
  *)
    log "$usage"
    exit 2
    ;;
esac
case "$target" in
  reconcile | status) command=(python -m pipeline "$target") ;;
  raw/?*) command=(python -m pipeline ingest --key "$target") ;;
  *)
    log "$usage"
    exit 2
    ;;
esac

export TASK_TIMEOUT_MINUTES=${TASK_TIMEOUT_MINUTES:-120}
exec bash scripts/ci/run_task.sh "$env_name" job "${command[@]}"
