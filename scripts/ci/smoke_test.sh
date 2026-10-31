#!/usr/bin/env bash
# smoke_test.sh ENV TAG: the service is stable, runs TAG, and answers its health check (OPS-07).
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

env_name=${1:?usage: smoke_test.sh ENV TAG}
tag=${2:?usage: smoke_test.sh ENV TAG}
stack="cicnids-$env_name"
cluster=$(stack_output "$stack" ClusterName)
service=$(stack_output "$stack" ServiceName)
port=$(stack_output "$stack" ListenerPort)
host=$(stack_output cicnids-platform AlbDnsName)

log "waiting for $service to be stable"
aws ecs wait services-stable --cluster "$cluster" --services "$service"

task_definition=$(aws ecs describe-services --cluster "$cluster" --services "$service" \
  --query 'services[0].taskDefinition' --output text)
image=$(aws ecs describe-task-definition --task-definition "$task_definition" \
  --query "taskDefinition.containerDefinitions[?name=='app'].image | [0]" --output text)
if [[ "$image" != *":$tag" ]]; then
  log "$service runs $image, expected the tag $tag"
  exit 1
fi

url="http://$host:$port/_stcore/health"
log "checking $url"
body=$(curl -fsS --retry 12 --retry-delay 10 --retry-all-errors --max-time 10 "$url")
if [[ "$body" != ok ]]; then
  log "the health check answered: $body"
  exit 1
fi
log "$env_name runs $tag and is healthy"
