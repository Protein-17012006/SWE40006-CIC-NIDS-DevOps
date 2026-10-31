#!/usr/bin/env bash
# push_image.sh TAG: build the image once and push it to ECR as TAG, unless the tag exists.
# Tags are immutable, so re-running a workflow for the same commit must not push again.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

tag=${1:?usage: push_image.sh TAG}
registry="${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is not set}.dkr.ecr.${AWS_REGION:?AWS_REGION is not set}.amazonaws.com"
image="$registry/cic-nids:$tag"

if aws ecr describe-images --repository-name cic-nids --image-ids "imageTag=$tag" >/dev/null 2>&1; then
  log "$image is already pushed"
  exit 0
fi

aws ecr get-login-password | docker login --username AWS --password-stdin "$registry"
docker build -t "$image" .
docker push "$image"
log "pushed $image"
