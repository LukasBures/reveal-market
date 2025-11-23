FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY price-streamer/pyproject.toml /app/pyproject.toml
COPY price-streamer/README.md /app/README.md
COPY price-streamer/app /app/app

RUN pip install --no-cache-dir hatchling \
    && pip install --no-cache-dir "uvicorn[standard]" \
    && pip install --no-cache-dir .

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
