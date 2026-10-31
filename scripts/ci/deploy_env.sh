#!/usr/bin/env bash
# deploy_env.sh ENV TAG [--skip-migrations]
# One release of one environment, in the order the brief fixes: infrastructure, migrations,
# application, smoke test. --skip-migrations is for rollbacks: an older image cannot migrate a
# newer schema, and expand-then-contract migrations keep the newer schema compatible.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

usage="usage: deploy_env.sh ENV TAG [--skip-migrations]"
env_name=${1:?$usage}
tag=${2:?$usage}
skip_migrations=false
if [[ "${3:-}" == --skip-migrations ]]; then skip_migrations=true; fi
if [[ ! "$tag" =~ ^[0-9a-f]{7}$ ]]; then
  log "image tags are 7-character commit hashes; got '$tag'"
  exit 2
fi

stack="cicnids-$env_name"
mapfile -t params < <(read_params "$env_name")

write_recent_tags() {
  local summary=${GITHUB_STEP_SUMMARY:-/dev/stdout}
  printf '### Newest image tags\n\n' >>"$summary"
  aws ecr describe-images --repository-name cic-nids \
    --query 'reverse(sort_by(imageDetails, &imagePushedAt))[:10].[imageTags[0], imagePushedAt]' \
    --output text | while read -r image_tag pushed_at; do
    # shellcheck disable=SC2016 # the backticks are Markdown code formatting
    printf -- '- `%s` pushed %s\n' "$image_tag" "$pushed_at" >>"$summary"
  done
}

# 1. Infrastructure and the job image; the running app keeps its image (a new stack starts on TAG)
app_tag_now=$(stack_parameter "$stack" AppImageTag)
deploy_stack "$stack" infra/environment.yaml "$env_name" "${params[@]}" \
  "JobImageTag=$tag" "AppImageTag=${app_tag_now:-$tag}"

# 2. A service stopped by hand comes back, so the smoke test has a task to check
cluster=$(stack_output "$stack" ClusterName)
service=$(stack_output "$stack" ServiceName)
desired=$(aws ecs describe-services --cluster "$cluster" --services "$service" \
  --query 'services[0].desiredCount' --output text)
if [[ "$desired" == 0 ]]; then
  log "$service was stopped by hand; starting one task"
  aws ecs update-service --cluster "$cluster" --service "$service" --desired-count 1 >/dev/null
fi

# 3. This environment's database role and database, then the migrations (OPS-04)
bash scripts/ci/run_task.sh "$env_name" admin
if [[ "$skip_migrations" == true ]]; then
  log "rollback: skipping migrations"
  write_recent_tags
else
  bash scripts/ci/run_task.sh "$env_name" job python -m pipeline migrate
fi

# 4. The application: ECS replaces tasks without dropping traffic (NFR-02)
deploy_stack "$stack" infra/environment.yaml "$env_name" "${params[@]}" \
  "JobImageTag=$tag" "AppImageTag=$tag"

# 5. Smoke test (OPS-07)
bash scripts/ci/smoke_test.sh "$env_name" "$tag"
