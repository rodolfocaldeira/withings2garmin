#!/usr/bin/env bash
# Sync recent Withings weigh-ins to Garmin Connect.
#
# Usage:
#   ./sync_weights.sh                 # download last 7 days, dry-run upload (nothing uploaded)
#   ./sync_weights.sh --days 30       # download last 30 days instead
#   ./sync_weights.sh --execute       # upload new weigh-ins (asks you to type UPLOAD)
#   ./sync_weights.sh --execute --yes # upload without the UPLOAD prompt
set -euo pipefail
cd "$(dirname "$0")"

DAYS=7
UPLOAD_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --days) DAYS="$2"; shift 2 ;;
        --execute) UPLOAD_ARGS+=(--execute); shift ;;
        --yes) UPLOAD_ARGS+=(--yes); shift ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# Load WITHINGS_* settings from .env if present.
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

PY=.venv/bin/python
if [[ ! -x "$PY" ]]; then
    echo "Missing .venv. Create it first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

echo "== 1/2 Downloading the last $DAYS days from Withings"
"$PY" withings_download.py --days "$DAYS"

echo
echo "== 2/2 Checking Garmin Connect for new weigh-ins"
"$PY" upload_new_weighins.py ${UPLOAD_ARGS[@]+"${UPLOAD_ARGS[@]}"}
