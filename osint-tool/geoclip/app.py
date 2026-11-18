"""Tiny internal GeoCLIP service: POST image bytes -> top-k GPS guesses."""
import asyncio
import os

from fastapi import FastAPI, HTTPException, Request

MAX_BYTES = 15 * 1024 * 1024
TOP_K_MAX = 10
app = FastAPI(title="geoclip")
_model = None
_gallery = None   # normalized location features of the 100K GPS gallery
_lock = asyncio.Lock()   # one inference at a time on CPU


def _load():
    """Load GeoCLIP once and pre-compute the gallery features.

    GeoCLIP.predict() re-encodes all 100K gallery coordinates on every call
    (~45 s on CPU). Those features never change, so we compute them once and
    only encode the image per request — same result, a fraction of the time.
    """
    global _model, _gallery
    if _model is None:
        import torch
        import torch.nn.functional as F
        from geoclip import GeoCLIP
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        model = GeoCLIP()
        model.eval()
        with torch.no_grad():
            _gallery = F.normalize(model.location_encoder(model.gps_gallery), dim=1)
        _model = model
    return _model


def _predict(data: bytes, top_k: int):
    import io

    import torch
    import torch.nn.functional as F
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 40_000_000      # decompression-bomb guard
    model = _load()
    with Image.open(io.BytesIO(data)) as image:
        image.draft("RGB", (1024, 1024))
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))          # CLIP sees 224 px anyway
        pixels = model.image_encoder.preprocess_image(image)
    with torch.no_grad():
        features = F.normalize(model.image_encoder(pixels), dim=1)
        logits = model.logit_scale.exp() * (features @ _gallery.t())
        top = torch.topk(logits.softmax(dim=-1), top_k, dim=1)
        gps = model.gps_gallery.index_select(0, top.indices[0])
    return [
        {"lat": float(g[0]), "lon": float(g[1]), "prob": float(p)}
        for g, p in zip(gps.tolist(), top.values[0].tolist())
    ]


@app.on_event("startup")
async def warm():
    # load weights in the background so /health answers right away
    asyncio.get_running_loop().run_in_executor(None, _load)


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _model is not None}


@app.post("/predict")
async def predict(request: Request, top_k: int = 5):
    data = await request.body()
    if not data:
        raise HTTPException(400, "empty body")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "image too large")
    top_k = max(1, min(top_k, TOP_K_MAX))
    async with _lock:
        try:
            preds = await asyncio.to_thread(_predict, data, top_k)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"could not process image: {type(exc).__name__}") from exc
    return {"predictions": preds}
