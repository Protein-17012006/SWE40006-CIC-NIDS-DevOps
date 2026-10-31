#!/usr/bin/env bash
# Helpers shared by the deployment scripts. Source it from the repository root.
# Expects AWS_REGION and AWS_ACCOUNT_ID in the environment (GitHub repository variables).
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2
}

stack_exists() {
  aws cloudformation describe-stacks --stack-name "$1" >/dev/null 2>&1
}

# stack_output STACK KEY: prints one output of a stack; fails when it is missing.
stack_output() {
  local value
  value=$(aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text) || true
  if [[ -z "$value" || "$value" == "None" ]]; then
    log "stack $1 has no output $2"
    return 1
  fi
  printf '%s\n' "$value"
}

# stack_parameter STACK KEY: the value the stack was last deployed with, or nothing.
stack_parameter() {
  local value
  value=$(aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Parameters[?ParameterKey=='$2'].ParameterValue | [0]" \
    --output text 2>/dev/null) || true
  if [[ "$value" != "None" ]]; then printf '%s\n' "$value"; fi
}

cfn_exec_role_arn() {
  printf 'arn:aws:iam::%s:role/cicnids-cfn-exec\n' "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is not set}"
}

# read_params ENV: the Key=Value lines of infra/params/ENV.params.
read_params() {
  local file="infra/params/$1.params"
  if [[ ! -f "$file" ]]; then
    log "no parameter file $file"
    return 1
  fi
  grep -Ev '^[[:space:]]*(#|$)' "$file"
}

# container_overrides CONTAINER ARG...: ECS RunTask overrides that run ARG... in CONTAINER.
# The arguments reach jq on stdin, one per line, so ones like -m are never read as jq options.
container_overrides() {
  local name=$1
  shift
  printf '%s\n' "$@" |
    jq -cRn --arg name "$name" '{containerOverrides: [{name: $name, command: [inputs]}]}'
}

# deploy_stack STACK TEMPLATE ENVIRONMENT_TAG [Key=Value ...]: create or update a stack through
# the CloudFormation execution role; on failure, print the events that explain it.
deploy_stack() {
  local stack=$1 template=$2 env_tag=$3
  shift 3
  local args=(--stack-name "$stack" --template-file "$template"
    --role-arn "$(cfn_exec_role_arn)" --capabilities CAPABILITY_NAMED_IAM
    --no-fail-on-empty-changeset --tags Project=cic-nids "Environment=$env_tag")
  if (($# > 0)); then args+=(--parameter-overrides "$@"); fi
  # A failed first creation leaves an empty ROLLBACK_COMPLETE stack that can only be deleted
  local status
  status=$(aws cloudformation describe-stacks --stack-name "$stack" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null) || true
  if [[ "$status" == ROLLBACK_COMPLETE ]]; then
    log "$stack failed to create earlier; deleting the empty stack before retrying"
    aws cloudformation delete-stack --stack-name "$stack" --role-arn "$(cfn_exec_role_arn)"
    aws cloudformation wait stack-delete-complete --stack-name "$stack"
  fi
  log "deploying $stack"
  if ! aws cloudformation deploy "${args[@]}"; then
    log "deploying $stack failed; the latest failure reasons:"
    aws cloudformation describe-stack-events --stack-name "$stack" --max-items 40 \
      --query "StackEvents[?contains(ResourceStatus, 'FAILED')].[LogicalResourceId, ResourceStatusReason]" \
      --output text >&2 || true
    return 1
  fi
}
