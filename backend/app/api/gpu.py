"""GPU policy endpoints: chat runs on GPU only, never on CPU.

POST /gpu/start loads the chat model onto the GPU. 409 means no GPU is
installed on this machine (the frontend shows the "No GPU available" popup).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import get_current_user
from app.config import settings
from app.db.models import User
from app.llm.gpu import detect_gpu, gpu_chat_status, load_model_on_gpu

router = APIRouter(tags=["gpu"])

_REASON_MESSAGES = {
    "ollama_offline": "Ollama is not running. Start it with 'ollama serve' and try again.",
    "no_gpu": "No GPU available on this system. Chat requires a GPU.",
    "model_not_loaded": "The model is not loaded on the GPU. Use 'Start GPU' to load it.",
    "model_on_cpu": "The model is running on CPU. Chat only runs on GPU.",
    "insufficient_vram": (
        "The model does not fit fully in GPU memory. Chat only runs fully on GPU."
    ),
}


async def ensure_chat_on_gpu() -> None:
    """Reject chat unless the model is fully resident on a GPU."""
    if settings.llm_is_mock or not settings.llm_require_gpu_for_chat:
        return
    status = await gpu_chat_status()
    if status["chat_available"]:
        return
    reason = status["reason"] or "no_gpu"
    raise HTTPException(
        status_code=503,
        detail=_REASON_MESSAGES.get(reason, "Chat requires a GPU."),
    )


@router.post("/gpu/start")
async def start_gpu(user: User = Depends(get_current_user)) -> dict:
    status = await gpu_chat_status()
    if settings.llm_is_mock:
        return status
    if not status["online"]:
        raise HTTPException(status_code=503, detail=_REASON_MESSAGES["ollama_offline"])

    gpu_hw = await detect_gpu(force=True)
    if gpu_hw is None and not status["gpu_installed"]:
        raise HTTPException(status_code=409, detail=_REASON_MESSAGES["no_gpu"])

    try:
        status = await load_model_on_gpu()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to load the model onto the GPU: {exc}"
        )

    if not status["model_fully_on_gpu"]:
        key = "insufficient_vram" if status["gpu"] else "model_on_cpu"
        raise HTTPException(status_code=503, detail=_REASON_MESSAGES[key])
    return status
