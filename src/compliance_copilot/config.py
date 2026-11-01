"""Application settings (12-factor: everything overridable via environment / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="COPILOT_", extra="ignore")

    # Storage
    database_url: str = "postgresql+psycopg://copilot:copilot@localhost:5433/copilot"
    data_dir: Path = ROOT / "data"

    # Retrieval models (run locally - document text never leaves the bank for embedding)
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"  # auto | cpu | cuda

    # Retrieval parameters
    dense_top_k: int = 40
    lexical_top_k: int = 40
    rrf_k: int = 60
    rerank_candidates: int = 24
    context_top_n: int = 6
    # Below this reranker score (sigmoid, 0..1) the evidence is clearly irrelevant and the
    # assistant abstains without calling the LLM. Kept just above the highest out-of-corpus
    # score on the main set (0.008): colloquial questions about real policies can score as
    # low as ~0.04 (held-out set), and in that grey zone the LLM itself reports
    # "insufficient_evidence" when the passages do not answer the question.
    abstain_threshold: float = 0.02
    # Minimum score for pairing a policy clause with the regulation that governs it.
    policy_pairing_threshold: float = 0.3
    chunk_max_chars: int = 1400

    # LLM. Keys use the COPILOT_ prefix so they never collide with other tools' env vars.
    llm_provider: str = "gemini"  # gemini | anthropic
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    gemini_batch_model: str | None = None  # gap analysis / eval; defaults to gemini_model
    llm_cache: bool = True  # disk-cache batch LLM calls (never live chat)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    llm_max_tokens: int = 16000
    # Reasoning effort per task (minimal | low | medium | high)
    answer_effort: str = "low"
    condense_effort: str = "minimal"

    # Security
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 480
    pii_masking: bool = True
    # Single sign-on (OpenID Connect). Leave oidc_issuer empty to use only the demo login.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str = "http://localhost:3000/api/auth/sso/callback"
    oidc_groups_claim: str = "groups"
    oidc_group_map: Path | None = None  # default: config/sso.yaml
    oidc_label: str = "SSO ขององค์กร"
    # Chat history retention (days); set by the DPO / legal team. 0 disables saving history.
    chat_retention_days: int = 90

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
