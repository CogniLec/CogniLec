FROM python:3.12-slim

# curl is required by this container's own healthcheck (docker-compose.yml
# `test: ["CMD", "curl", ...]`) -- without it the healthcheck can never
# pass even when the app itself is working fine (confirmed live, gap #31).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# torch is a large (~2GB), unpinned-size download; --default-timeout/
# --retries make this survive a slow or bursty network instead of failing
# the whole build partway through (confirmed live on a real slow network,
# gap #31) -- harmless on a fast network, just a higher ceiling.
RUN pip install --no-cache-dir --default-timeout=120 --retries 5 -r requirements.txt

COPY app.py .

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
