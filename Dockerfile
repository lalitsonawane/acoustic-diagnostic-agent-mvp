# syntax=docker/dockerfile:1
# Acoustic Diagnostic Agent — container image for Render / local Docker.
# Bind address and port follow Render conventions: 0.0.0.0:$PORT.
# The container filesystem is ephemeral; set ACOUSTIC_AGENT_DATA_DIR to a
# mounted volume if you need SQLite history across restarts. Exports remain
# the durable path on free tiers.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ACOUSTIC_AGENT_DATA_DIR=/tmp/acoustic_agent \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# libsndfile for soundfile / WAV decode
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY acoustic_agent ./acoustic_agent
COPY app.py ./
COPY data ./data
COPY .streamlit ./.streamlit
COPY scripts/run_server.sh ./scripts/run_server.sh

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install --no-deps . \
    && chmod +x scripts/run_server.sh

# Render (and most PaaS) inject PORT; default matches local Streamlit.
ENV PORT=8501
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8501')+'/_stcore/health', timeout=4)"

CMD ["./scripts/run_server.sh"]
