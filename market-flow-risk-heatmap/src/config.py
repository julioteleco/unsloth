"""Configuration loading for market-flow-risk-heatmap.

Loads ``config/default_config.yaml`` into validated pydantic models and resolves
project paths relative to the repository root. Environment variables (read from a
``.env`` file if present) provide optional secrets such as ``FRED_API_KEY``.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

try:  # python-dotenv is optional at import time
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a convenience only
    pass


def project_root() -> Path:
    """Return the project root (directory that contains ``config/``)."""
    return Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Pydantic models mirroring default_config.yaml
# --------------------------------------------------------------------------- #
class UniverseConfig(BaseModel):
    tickers: list[str]
    sectors: list[str] = Field(default_factory=list)
    vol_indices: list[str] = Field(default_factory=list)
    extra_context: list[str] = Field(default_factory=list)
    futures_context: list[str] = Field(default_factory=list)
    primary_tickers: list[str] = Field(default_factory=list)
    options_tickers: list[str] = Field(default_factory=list)

    def context_universe(self) -> list[str]:
        """All tickers we fetch for cross-asset context (deduped, order-stable)."""
        merged = [
            *self.tickers,
            *self.sectors,
            *self.vol_indices,
            *self.extra_context,
        ]
        return list(dict.fromkeys(merged))


class DownloadConfig(BaseModel):
    period: str = "60d"
    interval: str = "5m"
    daily_period: str = "2y"
    daily_interval: str = "1d"
    cache_ttl_minutes: int = 30


class FredConfig(BaseModel):
    series: list[str] = Field(default_factory=list)


class VwapConfig(BaseModel):
    atr_window: int = 14
    band_sigmas: list[float] = Field(default_factory=lambda: [1.0, 2.0])


class AtrConfig(BaseModel):
    window: int = 14
    method: str = "wilder"


class RvolConfig(BaseModel):
    lookback_days: int = 20
    clip_max: float = 10.0


class VolumeProfileConfig(BaseModel):
    bins: int = 80
    value_area_pct: float = 0.70
    hvn_quantile: float = 0.80
    lvn_quantile: float = 0.20


class BreadthConfig(BaseModel):
    ratios: list[list[str]] = Field(default_factory=list)
    return_windows: list[int] = Field(default_factory=lambda: [1, 3, 12])


class RegimeConfig(BaseModel):
    vix_ma_short: int = 5
    vix_ma_long: int = 20
    vix_backwardation_threshold: float = 1.0


class SeasonalityConfig(BaseModel):
    fomc_dates: list[str] = Field(default_factory=list)
    cpi_dates: list[str] = Field(default_factory=list)
    closing_window_min: int = 30


class FeaturesConfig(BaseModel):
    vwap: VwapConfig = Field(default_factory=VwapConfig)
    atr: AtrConfig = Field(default_factory=AtrConfig)
    rvol: RvolConfig = Field(default_factory=RvolConfig)
    volume_profile: VolumeProfileConfig = Field(default_factory=VolumeProfileConfig)
    breadth: BreadthConfig = Field(default_factory=BreadthConfig)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    seasonality: SeasonalityConfig = Field(default_factory=SeasonalityConfig)


class ScoringLabels(BaseModel):
    bajo: float = 25
    medio: float = 50
    alto: float = 75


class ScoringConfig(BaseModel):
    labels: ScoringLabels = Field(default_factory=ScoringLabels)


class TripleBarrierConfig(BaseModel):
    upper_atr: float = 0.8
    lower_atr: float = 0.5
    horizon_bars: int = 12


class LabelingConfig(BaseModel):
    triple_barrier: TripleBarrierConfig = Field(default_factory=TripleBarrierConfig)
    backtest_buckets: list[int] = Field(default_factory=lambda: [0, 20, 40, 60, 80, 100])


class PathsConfig(BaseModel):
    data_dir: str = "data"
    raw: str = "data/raw"
    processed: str = "data/processed"
    features: str = "data/features"
    options_snapshots: str = "data/options_snapshots"


class AppConfig(BaseModel):
    universe: UniverseConfig
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    fred: FredConfig = Field(default_factory=FredConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    labeling: LabelingConfig = Field(default_factory=LabelingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    # --- convenience accessors ------------------------------------------- #
    def abs_path(self, relative: str) -> Path:
        """Resolve a config path relative to the project root."""
        override = os.getenv("MFRH_DATA_DIR")
        p = Path(relative)
        if p.is_absolute():
            return p
        if override and relative.startswith(self.paths.data_dir):
            # Re-root data/* paths under the override directory.
            tail = Path(relative).relative_to(self.paths.data_dir)
            return Path(override) / tail
        return project_root() / p

    def ensure_dirs(self) -> None:
        for rel in (
            self.paths.raw,
            self.paths.processed,
            self.paths.features,
            self.paths.options_snapshots,
        ):
            self.abs_path(rel).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=4)
def load_config(path: Optional[str] = None) -> AppConfig:
    """Load and cache the application config from YAML.

    Parameters
    ----------
    path:
        Optional explicit path to a YAML config. Defaults to
        ``config/default_config.yaml`` at the project root.
    """
    cfg_path = Path(path) if path else project_root() / "config" / "default_config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    cfg = AppConfig(**raw)
    cfg.ensure_dirs()
    return cfg


def get_fred_api_key() -> Optional[str]:
    """Return the FRED API key if configured, else ``None`` (optional)."""
    key = os.getenv("FRED_API_KEY", "").strip()
    return key or None


def cache_ttl_minutes() -> int:
    """Cache TTL in minutes, overridable via ``MFRH_CACHE_TTL_MIN``."""
    env = os.getenv("MFRH_CACHE_TTL_MIN")
    if env and env.isdigit():
        return int(env)
    return load_config().download.cache_ttl_minutes
