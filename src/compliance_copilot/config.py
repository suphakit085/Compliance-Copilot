"""Application settings (12-factor: everything overridable via environment / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Secrets may also be mounted as files (Docker/Kubernetes secrets): /run/secrets/copilot_jwt_secret
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="COPILOT_", extra="ignore",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    # development | production. Production refuses to start with unsafe defaults (see security.py).
    env: str = "development"

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
    # Password login can be switched off once SSO is the only way in.
    password_login: bool = True
    # Require every user to accept the acceptable-use terms (config/terms.th.md) before asking questions.
    terms_required: bool = False
    # Lock an account for a while after repeated wrong passwords (an unknown username is
    # counted the same way, so the response never reveals whether an account exists).
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    # Operations
    log_format: str = "text"  # text | json (one object per line, for a log shipper)
    log_level: str = "INFO"
    # Bearer token for GET /metrics. Metrics are disabled (404) until one is set.
    metrics_token: str | None = None
    # How often the hash chain of the audit log is re-verified in the background (0 = never).
    audit_verify_minutes: int = 60
    # Rate limits (requests per window, per signed-in user unless noted)
    rate_user_per_min: int = 300
    rate_chat_per_min: int = 20  # each answer is an LLM call
    rate_gap_per_10min: int = 5  # a gap analysis is dozens of LLM calls
    rate_login_ip_per_min: int = 20  # per client address, across all usernames
    # Trust X-Forwarded-For for the client address. Only enable behind a proxy you control.
    trust_proxy: bool = False
    # Comma-separated Host headers the API answers to (empty = any). Set in production.
    allowed_hosts: str = ""
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
