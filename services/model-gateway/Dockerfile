FROM python:3.12.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True

RUN useradd --create-home --uid 10002 gateway
WORKDIR /app

COPY pyproject.toml ./
COPY gateway ./gateway
RUN pip install --no-cache-dir ".[postgres]"

USER gateway
EXPOSE 8020
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8020"]
