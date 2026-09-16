# API container — previously the only piece of this stack that wasn't
# containerized at all (it ran as a bare `uvicorn` process). That meant it
# had no restart policy and didn't survive a host/process interruption,
# unlike every other service in docker-compose.yml (all of which now have
# `restart: unless-stopped`).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# vendor/ holds local path-dependency shims (frozendict, text-unidecode --
# gap #22 copyleft-license replacements) that `uv sync` resolves against;
# without it, "Distribution not found at: file:///app/vendor/..." fails
# the build immediately. README.md is needed too -- this project installs
# itself editable, and pyproject.toml's `readme = "README.md"` field makes
# hatchling refuse to build without it present.
COPY vendor ./vendor
RUN uv sync --frozen --no-dev

COPY src ./src
COPY config ./config
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8123

# Runs migrations (via DATABASE_URL, the superuser role) before serving,
# so a fresh deployment doesn't need a separate manual `alembic upgrade
# head` step -- safe to run on every start, it's a no-op once the schema
# is current.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.api.main:app --host 0.0.0.0 --port 8123"]
