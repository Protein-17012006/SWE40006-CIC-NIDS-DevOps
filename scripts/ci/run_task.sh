#!/usr/bin/env bash
# run_task.sh ENV KIND [COMMAND...]: run the environment's one-off task (KIND is job or admin),
# wait until it stops, print its log, and exit with the container's exit code.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

usage="usage: run_task.sh ENV job|admin [COMMAND...]"
env_name=${1:?$usage}
kind=${2:?$usage}
shift 2
[[ "$kind" == job || "$kind" == admin ]] || { log "$usage"; exit 2; }

stack="cicnids-$env_name"
cluster=$(stack_output "$stack" ClusterName)
security_group=$(stack_output "$stack" TaskSecurityGroupId)
log_group=$(stack_output "$stack" LogGroupName)
subnets=$(stack_output cicnids-platform PublicSubnetIds)
family="cicnids-$env_name-$kind"

overrides='{}'
if (($# > 0)); then
  overrides=$(jq -cn --arg name "$kind" '{containerOverrides: [{name: $name, command: $ARGS.positional}]}' \
    --args "$@")
fi
network="awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=ENABLED}"

task_arn=$(aws ecs run-task --cluster "$cluster" --task-definition "$family" --launch-type FARGATE \
  --network-configuration "$network" --overrides "$overrides" --started-by github-actions \
  --query 'tasks[0].taskArn' --output text)
if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  log "ECS did not start $family"
  exit 1
fi
task_id=${task_arn##*/}
log "started $family task $task_id: ${*:-default command}"

deadline=$((SECONDS + 1800))
while true; do
  status=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
    --query 'tasks[0].lastStatus' --output text)
  [[ "$status" == STOPPED ]] && break
  if ((SECONDS > deadline)); then
    log "task $task_id is still $status after 30 minutes"
    exit 1
  fi
  sleep 10
done

aws logs get-log-events --log-group-name "$log_group" --log-stream-name "$kind/$kind/$task_id" \
  --start-from-head --query 'events[].[message]' --output text 2>/dev/null || log "no log stream yet"

exit_code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
  --query "tasks[0].containers[?name=='$kind'].exitCode | [0]" --output text)
if [[ "$exit_code" == "None" ]]; then
  reason=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
    --query 'tasks[0].stoppedReason' --output text)
  log "task $task_id stopped before its container ran: $reason"
  exit 1
fi
log "task $task_id exited with $exit_code"
exit "$exit_code"
