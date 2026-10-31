#!/usr/bin/env bash
# parity.sh: the image tag each environment's service runs, as a table in the job summary.
# After a promotion every row shows the same tag (environment parity).
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

summary=${GITHUB_STEP_SUMMARY:-/dev/stdout}
printf '### Environment parity\n\n| Environment | Image tag |\n| --- | --- |\n' >>"$summary"
for env_name in development test staging production; do
  stack="cicnids-$env_name"
  if ! stack_exists "$stack"; then
    printf '| %s | not deployed |\n' "$env_name" >>"$summary"
    continue
  fi
  cluster=$(stack_output "$stack" ClusterName)
  service=$(stack_output "$stack" ServiceName)
  task_definition=$(aws ecs describe-services --cluster "$cluster" --services "$service" \
    --query 'services[0].taskDefinition' --output text)
  image=$(aws ecs describe-task-definition --task-definition "$task_definition" \
    --query "taskDefinition.containerDefinitions[?name=='app'].image | [0]" --output text)
  # shellcheck disable=SC2016 # the backticks are Markdown code formatting
  printf '| %s | `%s` |\n' "$env_name" "${image##*:}" >>"$summary"
done
