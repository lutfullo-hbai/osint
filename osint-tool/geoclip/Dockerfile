# GeoCLIP (MIT, github.com/VicenteVivan/geo-clip): image -> likely GPS points.
# CPU-only PyTorch keeps the image small and needs no GPU runtime in Docker.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/hf TORCH_HOME=/cache/torch

WORKDIR /srv
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.7.1 torchvision==0.22.1 \
    && pip install geoclip==1.3.0 fastapi==0.115.6 uvicorn==0.32.1

COPY app.py .
RUN useradd --create-home geo && mkdir -p /cache && chown -R geo:geo /cache /srv
USER geo
EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
