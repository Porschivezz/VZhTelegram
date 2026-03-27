FROM python:3.11-slim AS base

WORKDIR /app

# Install system deps for lxml
RUN apt-get update && \
    apt-get install -y --no-install-recommends libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/

# Create data directory for SQLite
RUN mkdir -p data

ENV PYTHONUNBUFFERED=1

CMD ["python", "scripts/run_pipeline.py", "--mode", "bot", "--log-format", "json"]
