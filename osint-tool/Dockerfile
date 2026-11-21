# Subfinder ships as a static Go binary; copy it from the pinned upstream image
FROM projectdiscovery/subfinder:v2.17.0 AS subfinder

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc tesseract-ocr \
       tesseract-ocr-rus tesseract-ocr-uzb tesseract-ocr-uzb-cyrl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=subfinder /usr/local/bin/subfinder /usr/local/bin/subfinder

COPY backend/requirements.txt .

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend/requirements-dev.txt .
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY backend/VERSION .
COPY backend/main.py .
COPY backend/security.py .
COPY backend/cache.py .
COPY backend/store.py .
COPY backend/worker.py .
COPY backend/pytest.ini .
COPY backend/routers ./routers
COPY backend/services ./services
COPY backend/tools ./tools
COPY backend/assets ./assets
COPY backend/scripts ./scripts
COPY backend/tests ./tests
COPY backend/eval ./eval

RUN useradd --create-home --shell /bin/bash osint \
    && mkdir -p /app/data \
    && chown -R osint:osint /app

USER osint

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
