FROM python:3.12.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# git stores each generated project; Node builds and tests generated apps inside the sandbox.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 omniweb && mkdir -p /data && chown omniweb /data
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir ".[postgres]"

USER omniweb
EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
