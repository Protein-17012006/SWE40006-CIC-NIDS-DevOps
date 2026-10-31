#!/usr/bin/env bash
# load_baseline.sh ENV: put the CSE-CIC-IDS2018 baseline into ENV's raw/ folder (design 5.5).
# staging and production get the ten day files, one at a time and the 4 GB file last, so each
# copy starts one ingestion run; development gets the first 100,000 rows of one day.
# Run it from a laptop with the project's profile: AWS_PROFILE=hoang scripts/load_baseline.sh staging
# A file already in raw/ is skipped, so the script can be run again after an interruption.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

usage="usage: load_baseline.sh development|staging|production"
env_name=${1:-}
case "$env_name" in
  development | staging | production) ;;
  *)
    log "$usage"
    exit 2
    ;;
esac

source_bucket=cse-cic-ids2018
source_folder="Processed Traffic Data for ML Algorithms"
# Smallest first, so a problem shows up early; "Thuesday" is the dataset's own spelling
days=(
  Thursday-01-03-2018 Wednesday-28-02-2018 Wednesday-21-02-2018 Friday-16-02-2018
  Friday-02-03-2018 Wednesday-14-02-2018 Thursday-15-02-2018 Thursday-22-02-2018
  Friday-23-02-2018 Thuesday-20-02-2018
)

stack="cicnids-$env_name"
bucket=$(stack_output "$stack" BucketName)
cluster=$(stack_output "$stack" ClusterName)
family="cicnids-$env_name-job"
log "account $(aws sts get-caller-identity --query Account --output text), bucket $bucket"

running_jobs() {
  aws ecs list-tasks --cluster "$cluster" --family "$family" --desired-status RUNNING \
    --query 'length(taskArns)' --output text
}

# EventBridge starts the job within a minute or two of the upload; then wait for it to stop
wait_for_ingestion() {
  local key=$1 waited=0
  until (($(running_jobs) > 0)); do
    if ((waited >= 180)); then
      log "no ingestion task started for $key within 3 minutes"
      return 1
    fi
    sleep 10
    waited=$((waited + 10))
  done
  log "ingesting $key"
  waited=0
  while (($(running_jobs) > 0)); do
    if ((waited >= 7200)); then
      log "the ingestion of $key is still running after 120 minutes"
      return 1
    fi
    sleep 30
    waited=$((waited + 30))
  done
  log "done with $key; the Ingest workflow's status target shows its run"
}

already_there() {
  aws s3api head-object --bucket "$bucket" --key "$1" >/dev/null 2>&1
}

if [[ "$env_name" == development ]]; then
  key="raw/cse-cic-ids2018/Wednesday-14-02-2018.csv"
  if already_there "$key"; then
    log "$key is already there"
    exit 0
  fi
  cut=$(mktemp)
  trap 'rm -f "$cut"' EXIT
  # head closes the stream early on purpose; the line count below is the check
  aws s3 cp --no-sign-request \
    "s3://$source_bucket/$source_folder/Wednesday-14-02-2018_TrafficForML_CICFlowMeter.csv" - \
    2>/dev/null | head -n 100001 >"$cut" || true
  lines=$(wc -l <"$cut")
  if ((lines != 100001)); then
    log "expected the header and 100,000 rows, got $lines lines"
    exit 1
  fi
  aws s3 cp "$cut" "s3://$bucket/$key" --only-show-errors
  wait_for_ingestion "$key"
  exit 0
fi

for day in "${days[@]}"; do
  key="raw/cse-cic-ids2018/$day.csv"
  if already_there "$key"; then
    log "$key is already there; skipping"
    continue
  fi
  source_key="$source_folder/${day}_TrafficForML_CICFlowMeter.csv"
  log "copying $day"
  if ! aws s3 cp "s3://$source_bucket/$source_key" "s3://$bucket/$key" --only-show-errors; then
    log "the server-side copy was refused; streaming through this machine instead"
    size=$(aws s3api head-object --no-sign-request --bucket "$source_bucket" --key "$source_key" \
      --query ContentLength --output text)
    aws s3 cp --no-sign-request "s3://$source_bucket/$source_key" - |
      aws s3 cp - "s3://$bucket/$key" --expected-size "$size" --only-show-errors
  fi
  wait_for_ingestion "$key"
done
log "all ten day files are in $bucket/raw/cse-cic-ids2018/"
