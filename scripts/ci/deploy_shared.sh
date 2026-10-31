#!/usr/bin/env bash
# Deploys the shared stacks in order: platform, then databases, which imports from platform.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/lib.sh
source scripts/ci/lib.sh

deploy_stack cicnids-platform infra/platform.yaml shared "AlertEmail=${ALERT_EMAIL:-}"
deploy_stack cicnids-databases infra/databases.yaml shared
