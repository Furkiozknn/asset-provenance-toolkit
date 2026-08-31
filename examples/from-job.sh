#!/usr/bin/env bash
# Fetch a finished job from a running ai-job-gateway server and embed its
# provenance into a file in one step. Requires an ai-job-gateway server
# running locally (see https://github.com/Furkiozknn/ai-job-gateway) and
# a completed job id from it.
#
# Usage: ./from-job.sh <file> <gateway-url> <job-id>
set -euo pipefail

FILE="${1:?usage: from-job.sh <file> <gateway-url> <job-id>}"
GATEWAY_URL="${2:?usage: from-job.sh <file> <gateway-url> <job-id>}"
JOB_ID="${3:?usage: from-job.sh <file> <gateway-url> <job-id>}"

uv run aprov from-job "$FILE" --gateway-url "$GATEWAY_URL" --job-id "$JOB_ID"
uv run aprov extract "$FILE"
