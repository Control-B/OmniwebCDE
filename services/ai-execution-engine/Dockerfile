FROM python:3.12-slim

# git is used to snapshot Codex workspaces; the Codex CLI itself is installed separately
# (npm i -g @openai/codex) only where the Codex strategy is enabled.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 aaee
WORKDIR /app
COPY pyproject.toml ./
COPY aaee ./aaee
RUN pip install --no-cache-dir ".[postgres]"
COPY alembic.ini ./
COPY migrations ./migrations
RUN mkdir -p /data && chown aaee /data
USER aaee
ENV AAEE_DATA_DIR=/data
EXPOSE 8030
CMD ["sh", "-c", "alembic upgrade head && uvicorn aaee.main:app --host 0.0.0.0 --port 8030"]
