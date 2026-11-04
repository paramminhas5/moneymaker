"""Parquet lake: data/lake/<dataset>/<source>/<symbol>.parquet plus a manifest.

The snapshot ID is a hash over every file's content hash, so a backtest can record exactly which
data it saw and be replayed later.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import polars as pl

DEFAULT_LAKE = Path(__file__).resolve().parents[3] / "data" / "lake"

BAR_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Datetime("ms", "UTC"),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "volume": pl.Float64(),
    "quote_volume": pl.Float64(),
}
FUNDING_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Datetime("ms", "UTC"),
    "rate": pl.Float64(),  # per funding interval, as a fraction (0.0001 = 1 bp)
    "interval_hours": pl.Float64(),
}
SCHEMAS = {"bars_1d": BAR_SCHEMA, "funding": FUNDING_SCHEMA}


def lake_root() -> Path:
    return Path(os.environ.get("MM_LAKE_DIR", DEFAULT_LAKE))


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    rows: int
    start: str | None
    end: str | None
    sha256: str


def conform(df: pl.DataFrame, dataset: str) -> pl.DataFrame:
    """Cast to the dataset schema, sort by ts, drop exact duplicate timestamps (keep last)."""
    schema = SCHEMAS.get(dataset)
    if schema is None:
        return df
    missing = [c for c in schema if c not in df.columns]
    for col in missing:
        df = df.with_columns(pl.lit(None).alias(col))
    df = df.select([pl.col(c).cast(t) for c, t in schema.items()])
    return df.sort("ts").unique(subset="ts", keep="last", maintain_order=True)


def _frame_hash(df: pl.DataFrame) -> str:
    """Content hash from a canonical CSV encoding: stable across polars versions and file layout."""
    return hashlib.sha256(df.write_csv(float_precision=12).encode()).hexdigest()


class Catalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or lake_root()

    def path(self, dataset: str, source: str, symbol: str) -> Path:
        return self.root / dataset / source / f"{symbol}.parquet"

    def read(self, dataset: str, source: str, symbol: str) -> pl.DataFrame:
        return pl.read_parquet(self.path(dataset, source, symbol))

    def exists(self, dataset: str, source: str, symbol: str) -> bool:
        return self.path(dataset, source, symbol).exists()

    def last_ts(self, dataset: str, source: str, symbol: str) -> int | None:
        """Last timestamp in epoch ms, for incremental syncs."""
        if not self.exists(dataset, source, symbol):
            return None
        ts = pl.read_parquet(self.path(dataset, source, symbol), columns=["ts"])["ts"]
        if ts.is_empty():
            return None
        return int(ts.max().timestamp() * 1000)  # type: ignore[union-attr]

    def write(
        self, dataset: str, source: str, symbol: str, df: pl.DataFrame, *, merge: bool = True
    ) -> Path:
        path = self.path(dataset, source, symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        if merge and path.exists():
            df = pl.concat([pl.read_parquet(path), df], how="diagonal_relaxed")
        df = conform(df, dataset)
        df.write_parquet(path, compression="zstd")
        return path

    def entries(self) -> list[FileEntry]:
        out: list[FileEntry] = []
        for path in sorted(self.root.rglob("*.parquet")):
            df = pl.read_parquet(path)
            start = end = None
            if "ts" in df.columns and not df.is_empty():
                start, end = str(df["ts"].min()), str(df["ts"].max())
            out.append(
                FileEntry(
                    path=str(path.relative_to(self.root)),
                    rows=df.height,
                    start=start,
                    end=end,
                    sha256=_frame_hash(df),
                )
            )
        return out

    def snapshot_id(self, entries: list[FileEntry] | None = None) -> str:
        entries = entries if entries is not None else self.entries()
        h = hashlib.sha256()
        for e in sorted(entries, key=lambda e: e.path):
            h.update(f"{e.path}:{e.sha256};".encode())
        return h.hexdigest()[:16]

    def write_manifest(self) -> dict[str, object]:
        entries = self.entries()
        manifest: dict[str, object] = {
            "snapshot_id": self.snapshot_id(entries),
            "files": [asdict(e) for e in entries],
        }
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest
