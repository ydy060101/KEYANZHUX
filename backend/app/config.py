"""Central configuration. Every tunable number from the spec lives here.

Values are read from environment variables (and `.env` at the repo root) so no
business code hard-codes model names, thresholds or limits.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- LLM -------------------------------------------------------------
    llm_base_url: str = "http://127.0.0.1:3425/v1"
    llm_api_key: str = ""
    llm_fast: str = "workbuddy-ai/deepseek-v4.1-flash"
    llm_strong: str = "workbuddy/deepseek-v4-pro"
    llm_vision_enabled: bool = False
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3
    llm_rate_limit_per_min: int = 60
    llm_cache_ttl_s: int = 86_400

    # ---- Storage ---------------------------------------------------------
    database_url: str = "postgresql+psycopg://research:research@127.0.0.1:55432/research"
    redis_url: str = "redis://127.0.0.1:56379/0"
    data_dir: Path = REPO_ROOT / "data"

    # ---- Models ----------------------------------------------------------
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    hf_endpoint: str = "https://hf-mirror.com"
    model_dir: Path = REPO_ROOT / ".runtime" / "models"

    # ---- External APIs ---------------------------------------------------
    semantic_scholar_api_key: str = ""
    github_token: str = ""
    external_timeout_s: float = 30.0
    external_max_retries: int = 3

    # ---- Limits ----------------------------------------------------------
    upload_max_mb: int = 200
    parse_memory_limit_mb: int = 4096
    long_book_window_pages: int = 20
    scanned_page_char_threshold: int = 30

    # ---- QA --------------------------------------------------------------
    qa_min_score: float = 0.35
    chunk_target_tokens: int = 450
    chunk_min_tokens: int = 300
    chunk_max_tokens: int = 600
    chunk_overlap_ratio: float = 0.15
    retrieval_bm25_k: int = 30
    retrieval_vector_k: int = 30
    retrieval_rerank_k: int = 8
    rrf_k: int = 60

    # ---- Dedup -----------------------------------------------------------
    dedup_l3_cosine: float = 0.95
    dedup_l3_cosine_possible: float = 0.85
    dedup_l3_minhash_jaccard: float = 0.8

    # ---- Sandbox ---------------------------------------------------------
    sandbox_timeout_s: int = 20
    sandbox_memory_mb: int = 512

    # ---- App -------------------------------------------------------------
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def upload_max_bytes(self) -> int:
        return self.upload_max_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
