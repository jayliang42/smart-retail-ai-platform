FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY data/knowledge ./data/knowledge
COPY scripts ./scripts

RUN python -m pip install --no-cache-dir .

RUN useradd --create-home appuser

USER appuser

EXPOSE 8000

CMD ["uvicorn", "smart_retail.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
