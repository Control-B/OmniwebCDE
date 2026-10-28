FROM python:3.12.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 omniweb
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[postgres]"
COPY app ./app

USER omniweb
EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
