"""Run data sync jobs from config/data.yaml: fetch, quality-check, write to the lake."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict

from mm.config import Settings
from mm.config.loader import config_dir
from mm.data.catalog import Catalog
from mm.data.http import PoliteClient, SourceUnavailableError
from mm.data.quality import QualityReport, check_bars, check_funding
from mm.data.sources import binance, hyperliquid, polymarket, upstox
from mm.logging import get_logger

log = get_logger(__name__)

Source = Literal[
    "binance_spot",
    "binance_perp",
    "binance_funding",
    "hyperliquid_bars",
    "hyperliquid_funding",
    "upstox",
    "polymarket",
]
LAKE_SOURCE: dict[str, str] = {
    "binance_spot": "binance_spot",
    "binance_perp": "binance_perp",
    "binance_funding": "binance_perp",
    "hyperliquid_bars": "hyperliquid",
    "hyperliquid_funding": "hyperliquid",
    "upstox": "nse",
    "polymarket": "polymarket",
}


class DataJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    source: Source
    venue: str
    dataset: str
    start: date
    symbols: list[str]


def load_jobs(root: Path | None = None) -> list[DataJob]:
    raw = yaml.safe_load(((root or config_dir()) / "data.yaml").read_text())
    return [DataJob.model_validate(j) for j in raw["jobs"]]


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _resume_from(cat: Catalog, job: DataJob, symbol: str) -> date:
    last = cat.last_ts(job.dataset, LAKE_SOURCE[job.source], symbol)
    if last is None:
        return job.start
    # Re-fetch the last month so late corrections and partial months are overwritten.
    d = datetime.fromtimestamp(last / 1000, tz=UTC).date()
    return max(job.start, date(d.year, d.month, 1))


def _fetch(client: PoliteClient, job: DataJob, symbol: str, start: date) -> pl.DataFrame:
    match job.source:
        case "binance_spot":
            return binance.fetch_spot_daily(client, symbol, _ms(start))
        case "binance_perp":
            return binance.fetch_perp_daily(client, symbol, start)
        case "binance_funding":
            return binance.fetch_perp_funding(client, symbol, start)
        case "hyperliquid_bars":
            return hyperliquid.fetch_daily(client, symbol, _ms(start))
        case "hyperliquid_funding":
            return hyperliquid.fetch_funding(client, symbol, _ms(start))
        case "upstox" | "polymarket":
            raise AssertionError("handled separately")


def _check(df: pl.DataFrame, job: DataJob, symbol: str) -> QualityReport:
    name = f"{job.name}:{symbol}"
    if job.dataset == "funding":
        return check_funding(df, name)
    return check_bars(df, name)


def run_job(
    job: DataJob,
    settings: Settings,
    cat: Catalog,
    client: PoliteClient,
    *,
    on_report: Callable[[QualityReport], None] = lambda _: None,
) -> list[QualityReport]:
    if not settings.active_jurisdiction.can_read(job.venue):
        log.info("job_skipped_jurisdiction", job=job.name, venue=job.venue)
        return []
    reports: list[QualityReport] = []
    lake_source = LAKE_SOURCE[job.source]

    if job.source == "polymarket":
        df = polymarket.fetch_open_markets(client)
        if not df.is_empty():
            day = datetime.now(UTC).date().isoformat()
            path = cat.root / job.dataset / lake_source / f"{day}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(path, compression="zstd")
        rep = QualityReport(name=f"{job.name}:snapshot", rows=df.height)
        if df.is_empty():
            rep.errors.append("no markets returned")
        on_report(rep)
        return [rep]

    keys: dict[str, str] = {}
    if job.source == "upstox":
        keys = upstox.instrument_keys(client, job.symbols)

    for symbol in job.symbols:
        try:
            start = _resume_from(cat, job, symbol)
            if job.source == "upstox":
                if symbol not in keys:
                    rep = QualityReport(name=f"{job.name}:{symbol}", rows=0)
                    rep.errors.append("symbol not found in Upstox NSE instrument list")
                    reports.append(rep)
                    on_report(rep)
                    continue
                df = upstox.fetch_daily(client, keys[symbol], start)
            else:
                df = _fetch(client, job, symbol, start)
        except SourceUnavailableError as exc:
            rep = QualityReport(name=f"{job.name}:{symbol}", rows=0, errors=[str(exc)])
            reports.append(rep)
            on_report(rep)
            continue
        if df.is_empty():
            rep = QualityReport(name=f"{job.name}:{symbol}", rows=0)
            rep.warnings.append("no new rows (symbol may not exist on this venue)")
            reports.append(rep)
            on_report(rep)
            continue
        path = cat.write(job.dataset, lake_source, symbol, df)
        rep = _check(pl.read_parquet(path), job, symbol)
        reports.append(rep)
        on_report(rep)
    return reports
