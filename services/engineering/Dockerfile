FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libgl1 libglu1-mesa libx11-6 libxext6 && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 engineering
WORKDIR /app
COPY pyproject.toml ./
COPY engineering ./engineering
RUN pip install --no-cache-dir .
RUN mkdir -p /tmp/engineering && chown engineering:engineering /tmp/engineering
USER engineering
ENV HOME=/home/engineering TMPDIR=/tmp/engineering
EXPOSE 8040
CMD ["uvicorn", "engineering.main:app", "--host", "0.0.0.0", "--port", "8040", "--workers", "1"]
