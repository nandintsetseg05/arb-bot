"""Typed configuration loaded from .env via pydantic-settings."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class KalshiEnv(str, Enum):
    PROD = "prod"
    DEMO = "demo"


KALSHI_HOSTS: dict[KalshiEnv, str] = {
    KalshiEnv.PROD: "https://api.elections.kalshi.com/trade-api/v2",
    KalshiEnv.DEMO: "https://demo-api.kalshi.co/trade-api/v2",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Polymarket
    polymarket_pk: str = ""
    polymarket_funder: str = ""
    polymarket_signature_type: int = 0
    polymarket_host: str = "https://clob.polymarket.com"
    polymarket_chain_id: int = 137

    # Kalshi
    kalshi_key_id: str = ""
    kalshi_private_key_path: str = ""
    kalshi_env: KalshiEnv = KalshiEnv.DEMO

    # Trading
    # NOTE (crypto-research build): live trading is hard-disabled in code and
    # fails closed regardless of this flag — see src/errors.py and the guards in
    # execution/executor.py and scripts/live_run.py (CRYPTO_REFACTOR_PLAN.md Phase 0).
    live_trading_enabled: bool = False
    paper_only: bool = True
    min_edge_bps: int = 50
    max_position_usd: float = 500.0
    quarter_kelly: bool = True
    drawdown_limit: float = 0.15

    # Scope (crypto-only research build). Assets are matched case-insensitively
    # against market metadata; window is the short-duration series we target first.
    crypto_assets: tuple[str, ...] = ("BTC", "ETH")
    market_window: str = "15m"

    # Matching
    match_auto_threshold: float = 0.85
    match_review_threshold: float = 0.65

    # Loop / TTL
    scan_interval_seconds: int = 5
    opportunity_ttl_ms: int = 1500

    # Storage
    db_path: str = "data/poly_arb.db"

    # Logging
    log_level: str = "INFO"

    @field_validator("polymarket_signature_type")
    @classmethod
    def _validate_sig_type(cls, v: int) -> int:
        if v not in (0, 1, 2):
            raise ValueError("POLYMARKET_SIGNATURE_TYPE must be 0, 1, or 2")
        return v

    @field_validator("drawdown_limit")
    @classmethod
    def _validate_drawdown(cls, v: float) -> float:
        if not 0 < v < 1:
            raise ValueError("DRAWDOWN_LIMIT must be in (0, 1)")
        return v

    @field_validator("match_auto_threshold", "match_review_threshold")
    @classmethod
    def _validate_thresholds(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError("match thresholds must be in [0, 1]")
        return v

    @property
    def kalshi_host(self) -> str:
        return KALSHI_HOSTS[self.kalshi_env]

    @property
    def db_full_path(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def kalshi_private_key_full_path(self) -> Path | None:
        if not self.kalshi_private_key_path:
            return None
        p = Path(self.kalshi_private_key_path).expanduser()
        return p if p.is_absolute() else REPO_ROOT / p

    def assert_polymarket_ready(self) -> None:
        if not self.polymarket_pk:
            raise RuntimeError("POLYMARKET_PK is empty — set it in .env")

    def assert_kalshi_ready(self) -> None:
        if not self.kalshi_key_id:
            raise RuntimeError("KALSHI_KEY_ID is empty — set it in .env")
        path = self.kalshi_private_key_full_path
        if path is None or not path.exists():
            raise RuntimeError(f"KALSHI_PRIVATE_KEY_PATH not found: {path}")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
