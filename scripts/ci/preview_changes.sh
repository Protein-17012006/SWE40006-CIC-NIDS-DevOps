#!/usr/bin/env bash
# preview_changes.sh STACK TEMPLATE [Key=Value ...]
# Writes what deploying TEMPLATE to STACK would change to the job summary, without applying it.
# Only existing stacks are previewed; a new stack is created when the change reaches main.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

stack=$1
template=$2
shift 2
summary=${GITHUB_STEP_SUMMARY:-/dev/stdout}

if ! stack_exists "$stack"; then
  printf '### %s\n\nThe stack does not exist yet; it is created when this change reaches main.\n\n' \
    "$stack" >>"$summary"
  exit 0
fi

# Given parameters take their new values; every other parameter keeps its current value.
given=" "
params=()
for pair in "$@"; do
  params+=("ParameterKey=${pair%%=*},ParameterValue=${pair#*=}")
  given+="${pair%%=*} "
done
for key in $(aws cloudformation describe-stacks --stack-name "$stack" \
  --query 'Stacks[0].Parameters[].ParameterKey' --output text); do
  [[ "$given" == *" $key "* ]] || params+=("ParameterKey=$key,UsePreviousValue=true")
done

name="preview-${GITHUB_RUN_ID:-local}-$RANDOM"
args=(--stack-name "$stack" --change-set-name "$name" --template-body "file://$template"
  --capabilities CAPABILITY_NAMED_IAM --role-arn "$(cfn_exec_role_arn)")
if ((${#params[@]} > 0)); then args+=(--parameters "${params[@]}"); fi
aws cloudformation create-change-set "${args[@]}" >/dev/null

printf '### %s\n\n' "$stack" >>"$summary"
if aws cloudformation wait change-set-create-complete --stack-name "$stack" \
  --change-set-name "$name" 2>/dev/null; then
  printf '| Action | Resource | Type | Replacement |\n| --- | --- | --- | --- |\n' >>"$summary"
  aws cloudformation describe-change-set --stack-name "$stack" --change-set-name "$name" \
    --query 'Changes[].ResourceChange.[Action, LogicalResourceId, ResourceType, Replacement]' \
    --output text | while read -r action resource type replacement; do
    printf '| %s | %s | %s | %s |\n' "$action" "$resource" "$type" "$replacement" >>"$summary"
  done
else
  reason=$(aws cloudformation describe-change-set --stack-name "$stack" --change-set-name "$name" \
    --query StatusReason --output text)
  printf '%s\n' "$reason" >>"$summary"
fi
printf '\n' >>"$summary"
aws cloudformation delete-change-set --stack-name "$stack" --change-set-name "$name"
