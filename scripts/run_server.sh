#!/usr/bin/env bash
# Start Streamlit bound to 0.0.0.0:$PORT (Render / Docker / Cloud Run convention).
# Ephemeral filesystem: prefer downloads for durable artefacts; set
# ACOUSTIC_AGENT_DATA_DIR to a persistent volume when available.
set -euo pipefail

PORT="${PORT:-8501}"
export ACOUSTIC_AGENT_DATA_DIR="${ACOUSTIC_AGENT_DATA_DIR:-/tmp/acoustic_agent}"
mkdir -p "${ACOUSTIC_AGENT_DATA_DIR}"

exec streamlit run app.py \
  --server.address=0.0.0.0 \
  --server.port="${PORT}" \
  --server.headless=true \
  --browser.gatherUsageStats=false
