"""Application settings. EVERYTHING configurable via environment / .env.

This is the single place that reads env. Nothing else in the app should read
os.environ directly, so the cloud migration only has to change env values.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the repo root (one level above backend/) or backend/.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+psycopg://quolate:quolate@localhost:5433/quolate"
    test_database_url: str = (
        "postgresql+psycopg://quolate:quolate@localhost:5433/quolate_test"
    )

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # Admin console (compliance). Override in .env for production.
    admin_username: str = "admin@quolate.com"
    admin_password: str = "admin1963"
    admin_token_expire_hours: int = 8

    # Storage
    file_storage_path: str = "./data/files"

    # LLM (OpenAI-compatible). Set LLM_BASE_URL=mock to use the in-process mock.
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3:8b"
    llm_num_ctx: int = 8192
    llm_request_timeout_seconds: float = 300.0  # interactive chat calls (5min for CPU-bound models)
    llm_fast_timeout_seconds: float = 120.0  # non-interactive (classify/extract) (2min)
    llm_disable_thinking_for_fast_calls: bool = True
    # GPU-only chat policy: chat is refused unless the model is fully in GPU
    # VRAM. Set false to allow CPU chat (e.g. live tests on CPU machines).
    llm_require_gpu_for_chat: bool = True
    # Use Ollama's native /api/chat (honors num_ctx/keep_alive, unlike the
    # /v1 shim). Set false for hosted OpenAI-compatible APIs.
    llm_native_ollama: bool = True
    llm_keep_alive: str = "2h"  # how long Ollama keeps the model warm
    gpu_load_timeout_seconds: float = 300.0  # /gpu/start model-load timeout

    # Parse-time estimation (per-op seconds; tuned for this deployment's CPU OCR
    # + local LLM). Only drives the progress bar / ETA, never correctness.
    parse_est_base_seconds: float = 2.0  # download + routing + overhead
    parse_est_ocr_page_seconds: float = 3.5  # per page, per OCR language
    parse_est_llm_chunk_seconds: float = 9.0  # per LLM extraction chunk
    parse_est_persist_seconds: float = 2.0  # persist fields + embedding

    # Embeddings
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # OCR
    # ocr_langs is the set of languages OFFERED at upload time (the picker).
    # ocr_default_langs is what's pre-selected when the uploader picks nothing.
    # Chinese roughly doubles OCR time (a second full pass per page), so it is
    # off by default and only run when the uploader opts in.
    ocr_langs: str = "en,ch"
    ocr_default_langs: str = "en"
    # Rasterization DPI for scanned PDFs. 200 is print-crisp but slow; 150 is
    # plenty for OCR of typed invoices/quotations and ~44% fewer pixels to scan.
    ocr_dpi: int = 150
    # Pages of a scanned PDF OCR'd in parallel. PaddleOCR is CPU-bound and the
    # LLM/GPU sits idle during OCR, so a small pool cuts multi-page wall time.
    # 1 disables parallelism.
    ocr_max_workers: int = 2

    # Tender scraping
    scrape_cron: str = "0 7 * * *"
    scrape_user_agent: str = "QuolateBot/0.1 (+contact@quolate.local)"
    tender_keep_limit: int = 50  # cleanup keeps this many newest tenders

    # Global document library storage cap per user (bytes).
    library_quota_bytes: int = 500 * 1024 * 1024  # 500 MB

    # CORS
    allow_origins: str = "http://localhost:3000"

    # Background worker: disabled in tests (driven manually).
    run_worker: bool = True

    # Preflight checks
    db_preflight_timeout_seconds: float = 3.0
    ollama_preflight_timeout_seconds: float = 3.0

    @property
    def ocr_langs_list(self) -> list[str]:
        """Languages OFFERED at upload (also the fallback if a job carries none)."""
        return [x.strip() for x in self.ocr_langs.split(",") if x.strip()]

    @property
    def ocr_default_langs_list(self) -> list[str]:
        """Pre-selected languages when the uploader specifies none."""
        allowed = set(self.ocr_langs_list)
        picked = [x.strip() for x in self.ocr_default_langs.split(",") if x.strip()]
        return [x for x in picked if x in allowed] or (self.ocr_langs_list[:1] or ["en"])

    @property
    def allow_origins_list(self) -> list[str]:
        return [x.strip() for x in self.allow_origins.split(",") if x.strip()]

    @property
    def storage_path(self) -> Path:
        p = Path(self.file_storage_path)
        if not p.is_absolute():
            p = _BACKEND_DIR / p
        return p

    @property
    def llm_is_mock(self) -> bool:
        return self.llm_base_url.strip().lower() == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
