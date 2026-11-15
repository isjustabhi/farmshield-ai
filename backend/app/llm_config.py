"""Load LLM settings from .env — never hardcode secrets."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # Fill missing keys from .env; do not override process env (tests / CI).
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "backend" / ".env", override=False)


def _detect_provider(api_key: str, explicit: str) -> str:
    if explicit in {"anthropic", "openai"}:
        return explicit
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    return "openai"


class LLMSettings(BaseModel):
    provider: str = "anthropic"  # anthropic | openai
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-haiku-4-5"
    enabled: bool = True
    timeout_sec: float = Field(default=20.0, gt=0)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip()) and self.enabled


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    _load_dotenv()
    enabled_raw = os.getenv("LLM_AGENTS_ENABLED", "true").strip().lower()
    enabled = enabled_raw not in {"0", "false", "no", "off"}
    timeout = float(os.getenv("LLM_TIMEOUT_SEC", "20") or "20")
    api_key = os.getenv("LLM_API_KEY", "").strip()
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    provider = _detect_provider(api_key, explicit)

    if provider == "anthropic":
        default_base = "https://api.anthropic.com"
        default_model = "claude-haiku-4-5"
    else:
        default_base = "https://api.openai.com/v1"
        default_model = "gpt-4o-mini"

    return LLMSettings(
        provider=provider,
        api_key=api_key,
        base_url=(os.getenv("LLM_BASE_URL") or default_base).rstrip("/"),
        model=(os.getenv("LLM_MODEL") or default_model).strip() or default_model,
        enabled=enabled,
        timeout_sec=timeout,
    )


def reload_llm_settings() -> LLMSettings:
    get_llm_settings.cache_clear()
    return get_llm_settings()
