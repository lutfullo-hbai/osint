import os

from fastapi import APIRouter

router = APIRouter(tags=["config"])


@router.get("/api/config")
async def get_config():
    """Non-sensitive client config. The browser calls Ollama directly, so the URL
    here must be reachable from the user's browser (default localhost)."""
    return {
        "ollama": {
            "url": os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
            "vision_model": os.environ.get("OLLAMA_VISION_MODEL", "qwen2.5vl:7b"),
        }
    }
