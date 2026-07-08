"""GPU detection and Ollama model-placement checks for the GPU-only chat policy.

Chat is only allowed when the chat model is fully resident in GPU VRAM
(Ollama's /api/ps reports size_vram == size, i.e. "100% GPU"). Hardware
detection uses nvidia-smi; any vendor also counts as installed once Ollama
reports VRAM usage for a loaded model.
"""
from __future__ import annotations

import asyncio
import subprocess
import time

import httpx

from app.config import settings

_NVIDIA_SMI_CANDIDATES = [
    "nvidia-smi",
    r"C:\Windows\System32\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
]

_GPU_RECHECK_SECONDS = 30.0
_gpu_info: dict | None = None
_gpu_checked_at: float = 0.0


def _nvidia_smi_sync() -> dict | None:
    for exe in _NVIDIA_SMI_CANDIDATES:
        try:
            proc = subprocess.run(
                [exe, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        if not lines:
            continue
        name, _, mem = lines[0].partition(",")
        return {"name": name.strip(), "memory_total": mem.strip() or None}
    return None


async def detect_gpu(force: bool = False) -> dict | None:
    """Detect an NVIDIA GPU via nvidia-smi.

    A positive result is cached for the process lifetime (hardware doesn't
    appear at runtime); a negative one is re-checked at most every 30s so the
    status poll doesn't spawn a subprocess on every tick.
    """
    global _gpu_info, _gpu_checked_at
    if not force:
        if _gpu_info is not None:
            return _gpu_info
        if _gpu_checked_at and time.monotonic() - _gpu_checked_at < _GPU_RECHECK_SECONDS:
            return None
    # subprocess must run in a thread: on Windows the app uses
    # SelectorEventLoop, which has no asyncio subprocess support.
    _gpu_info = await asyncio.to_thread(_nvidia_smi_sync)
    _gpu_checked_at = time.monotonic()
    return _gpu_info


def _ollama_base() -> str:
    return settings.llm_base_url.replace("/v1", "")


def _matches_model(entry: dict, model: str) -> bool:
    for key in ("name", "model"):
        value = entry.get(key) or ""
        if value == model or value.split(":")[0] == model:
            return True
    return False


async def _ollama_state() -> dict:
    """Return {online, loaded, size, size_vram} for the configured chat model."""
    state: dict = {"online": False, "loaded": False, "size": 0, "size_vram": 0}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            tags = await client.get(f"{_ollama_base()}/api/tags")
            if tags.status_code != 200:
                return state
            state["online"] = True

            ps = await client.get(f"{_ollama_base()}/api/ps")
            if ps.status_code != 200:
                return state
            for entry in ps.json().get("models", []):
                if not _matches_model(entry, settings.llm_model):
                    continue
                state["loaded"] = True
                state["size"] = entry.get("size") or 0
                state["size_vram"] = entry.get("size_vram") or 0
                break
    except httpx.HTTPError:
        pass
    return state


async def gpu_chat_status() -> dict:
    """Combined status consumed by /status/llm, /gpu/start and the chat gate."""
    if settings.llm_is_mock:
        return {
            "online": True,
            "model": settings.llm_model,
            "gpu": False,
            "gpu_name": None,
            "vram_used": None,
            "gpu_installed": False,
            "model_loaded": True,
            "model_fully_on_gpu": False,
            "chat_available": True,
            "reason": None,
        }

    gpu_hw, state = await asyncio.gather(detect_gpu(), _ollama_state())
    gpu_installed = gpu_hw is not None or state["size_vram"] > 0
    fully_on_gpu = state["loaded"] and state["size"] > 0 and state["size_vram"] >= state["size"]

    reason: str | None = None
    if not state["online"]:
        reason = "ollama_offline"
    elif not gpu_installed:
        reason = "no_gpu"
    elif not state["loaded"]:
        reason = "model_not_loaded"
    elif state["size_vram"] <= 0:
        reason = "model_on_cpu"
    elif not fully_on_gpu:
        reason = "insufficient_vram"

    chat_available = reason is None
    if not settings.llm_require_gpu_for_chat:
        chat_available = state["online"]

    return {
        "online": state["online"],
        "model": settings.llm_model,
        "gpu": state["size_vram"] > 0,
        "gpu_name": gpu_hw["name"] if gpu_hw else None,
        "vram_used": (
            f"{state['size_vram'] / (1024 ** 3):.1f} GB" if state["size_vram"] > 0 else None
        ),
        "gpu_installed": gpu_installed,
        "model_loaded": state["loaded"],
        "model_fully_on_gpu": fully_on_gpu,
        "chat_available": chat_available,
        "reason": None if chat_available else reason,
    }


async def load_model_on_gpu() -> dict:
    """Ask Ollama to load the chat model, then return the fresh status.

    keep_alive pins the model warm; options must match what chat requests
    send so the first chat call doesn't trigger a reload with different
    placement.
    """
    payload = {
        "model": settings.llm_model,
        "stream": False,
        "keep_alive": settings.llm_keep_alive,
        "options": {"num_ctx": settings.llm_num_ctx},
    }
    async with httpx.AsyncClient(timeout=settings.gpu_load_timeout_seconds) as client:
        resp = await client.post(f"{_ollama_base()}/api/generate", json=payload)
        resp.raise_for_status()

    # Right after the load returns, /api/ps can briefly omit the new runner
    # while Ollama swaps out a previous instance — retry before concluding.
    for _ in range(10):
        status = await gpu_chat_status()
        if status["model_loaded"]:
            return status
        await asyncio.sleep(1.0)
    return status
