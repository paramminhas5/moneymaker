from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest

from mm.config import Settings
from mm.data.catalog import Catalog, conform
from mm.data.http import PoliteClient, SourceUnavailableError
from mm.data.quality import check_bars, check_funding
from mm.data.sources import binance, hyperliquid, polymarket, upstox
from mm.data.sync import DataJob, load_jobs, run_job
from mm.data.universe import top_n_by_liquidity

from .conftest import CONFIG_DIR, settings_for

DAY = 86_400_000


def client_for(handler: httpx.MockTransport) -> PoliteClient:
    return PoliteClient(transport=handler, min_interval_s=0, sleep=lambda _: None)


def bars(
    n: int, start: datetime | None = None, price: float = 100.0, qv: float = 1e6
) -> pl.DataFrame:
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "ts": [start + timedelta(days=i) for i in range(n)],
            "open": [price] * n,
            "high": [price * 1.01] * n,
            "low": [price * 0.99] * n,
            "close": [price] * n,
            "volume": [1.0] * n,
            "quote_volume": [qv] * n,
        }
    ).pipe(conform, "bars_1d")


# HTTP client ------------------------------------------------------------------------------
def test_client_refuses_to_work_around_blocks() -> None:
    c = client_for(httpx.MockTransport(lambda r: httpx.Response(451)))
    with pytest.raises(SourceUnavailableError, match="not retrying"):
        c.get("https://x.test")


def test_client_retries_rate_limits() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429 if calls["n"] < 3 else 200, json={"ok": True})

    assert client_for(httpx.MockTransport(handler)).get("https://x.test").json() == {"ok": True}
    assert calls["n"] == 3


def test_client_sends_honest_user_agent() -> None:
    seen: dict[str, str] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["ua"] = r.headers["user-agent"]
        return httpx.Response(200)

    client_for(httpx.MockTransport(handler)).get("https://x.test")
    assert seen["ua"].startswith("moneymaker-data/")


# Binance ----------------------------------------------------------------------------------
def kline(open_ms: int, close: float = 100.0) -> list[object]:
    return [
        open_ms,
        "99",
        "101",
        "98",
        str(close),
        "10",
        open_ms + DAY - 1,
        "1000",
        5,
        "5",
        "500",
        "0",
    ]


def test_binance_spot_paginates_and_drops_open_candle() -> None:
    start = 1_700_000_000_000 - (1_700_000_000_000 % DAY)

    def handler(r: httpx.Request) -> httpx.Response:
        cursor = int(r.url.params["startTime"])
        if cursor >= start + 3 * DAY:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[kline(cursor + i * DAY) for i in range(2)])

    df = binance.fetch_spot_daily(
        client_for(httpx.MockTransport(handler)), "BTCUSDT", start, end_ms=start + 4 * DAY
    )
    assert df.height == 4
    assert df["ts"].is_sorted()


def zipped(csv: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("f.csv", csv)
    return buf.getvalue()


@pytest.mark.parametrize("header", [True, False])
def test_binance_funding_archive_with_or_without_header(header: bool) -> None:
    body = "1577836800000,8,-0.00012359\n1577865600000,8,0.0001\n"
    if header:
        body = "calc_time,funding_interval_hours,last_funding_rate\n" + body

    def handler(r: httpx.Request) -> httpx.Response:
        if "2020-01" in str(r.url):
            return httpx.Response(200, content=zipped(body))
        return httpx.Response(404)

    df = binance.fetch_perp_funding(
        client_for(httpx.MockTransport(handler)), "BTCUSDT", date(2020, 1, 1)
    )
    assert df.height == 2
    assert df["rate"].to_list() == [-0.00012359, 0.0001]
    assert df["interval_hours"].to_list() == [8.0, 8.0]


def test_binance_perp_klines_archive() -> None:
    row = ",".join(str(x) for x in kline(1577836800000))

    def handler(r: httpx.Request) -> httpx.Response:
        if "2020-01" in str(r.url):
            return httpx.Response(200, content=zipped(row + "\n"))
        return httpx.Response(404)

    df = binance.fetch_perp_daily(
        client_for(httpx.MockTransport(handler)), "BTCUSDT", date(2020, 1, 1)
    )
    assert df.height == 1
    assert df["close"][0] == 100.0


# Hyperliquid ------------------------------------------------------------------------------
def test_hyperliquid_candles_and_funding() -> None:
    t0 = 1_700_000_000_000 - (1_700_000_000_000 % DAY)

    def handler(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        if body["type"] == "candleSnapshot":
            if body["req"]["startTime"] > t0:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "t": t0 + i * DAY,
                        "T": t0 + (i + 1) * DAY - 1,
                        "o": "1",
                        "h": "2",
                        "l": "0.5",
                        "c": "1.5",
                        "v": "10",
                    }
                    for i in range(3)
                ],
            )
        if body["startTime"] > t0 + 3_600_000:
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {"coin": "BTC", "fundingRate": "0.0000125", "premium": "0", "time": t0},
                {"coin": "BTC", "fundingRate": "0.00002", "premium": "0", "time": t0 + 3_600_000},
            ],
        )

    c = client_for(httpx.MockTransport(handler))
    candles = hyperliquid.fetch_daily(c, "BTC", t0)
    assert candles.height == 3
    assert candles["quote_volume"][0] == 15.0
    funding = hyperliquid.fetch_funding(c, "BTC", t0)
    assert funding.height == 2
    assert funding["interval_hours"].unique().to_list() == [1.0]


# Upstox and Polymarket --------------------------------------------------------------------
def test_upstox_instrument_keys_and_candles() -> None:
    instruments = gzip.compress(
        json.dumps(
            [
                {
                    "trading_symbol": "NIFTYBEES",
                    "segment": "NSE_EQ",
                    "instrument_key": "NSE_EQ|INF204",
                },
                {"trading_symbol": "NIFTYBEES", "segment": "NSE_FO", "instrument_key": "NSE_FO|1"},
            ]
        ).encode()
    )

    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith(".json.gz"):
            return httpx.Response(200, content=instruments)
        if "/day/2025-01-10/" not in r.url.path:
            return httpx.Response(200, json={"status": "success", "data": {"candles": []}})
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "candles": [
                        ["2025-01-10T00:00:00+05:30", 270.1, 272.0, 269.5, 271.3, 1000, 0],
                        ["2025-01-09T00:00:00+05:30", 268.0, 270.5, 267.9, 270.0, 900, 0],
                    ]
                },
            },
        )

    c = client_for(httpx.MockTransport(handler))
    assert upstox.instrument_keys(c, ["NIFTYBEES"]) == {"NIFTYBEES": "NSE_EQ|INF204"}
    df = upstox.fetch_daily(c, "NSE_EQ|INF204", date(2024, 6, 1), date(2025, 1, 10))
    assert df.height == 2
    assert str(df["ts"].dtype) == "Datetime(time_unit='ms', time_zone='UTC')"


def test_polymarket_yes_price_parsing() -> None:
    assert polymarket._yes_price('["0.0185", "0.9815"]') == pytest.approx(0.0185)
    assert polymarket._yes_price("garbage") is None


# Catalog ----------------------------------------------------------------------------------
def test_catalog_merge_dedupe_and_snapshot_ids(tmp_path: Path) -> None:
    cat = Catalog(tmp_path)
    cat.write("bars_1d", "src", "AAA", bars(5))
    cat.write("bars_1d", "src", "AAA", bars(3, start=datetime(2024, 1, 4, tzinfo=UTC), price=101))
    df = cat.read("bars_1d", "src", "AAA")
    assert df.height == 6  # days 1-6, overlap replaced by the newer rows
    assert df.filter(pl.col("ts") == datetime(2024, 1, 4, tzinfo=UTC))["close"][0] == 101
    snap1 = cat.snapshot_id()
    assert snap1 == Catalog(tmp_path).snapshot_id()  # deterministic
    cat.write("bars_1d", "src", "BBB", bars(2))
    assert cat.snapshot_id() != snap1
    manifest = cat.write_manifest()
    assert (tmp_path / "manifest.json").exists()
    assert len(manifest["files"]) == 2  # type: ignore[arg-type]
    assert cat.last_ts("bars_1d", "src", "AAA") == int(
        datetime(2024, 1, 6, tzinfo=UTC).timestamp() * 1000
    )


# Quality ----------------------------------------------------------------------------------
def test_quality_checks_catch_bad_bars() -> None:
    assert check_bars(bars(10), "ok").ok
    bad = bars(10).with_columns(
        pl.when(pl.col("ts") == pl.col("ts").min()).then(-1.0).otherwise(pl.col("low")).alias("low")
    )
    assert not check_bars(bad, "neg").ok
    broken = bars(10).with_columns(pl.lit(50.0).alias("high"))
    assert any("violate" in e for e in check_bars(broken, "ohlc").errors)
    gappy = pl.concat([bars(5), bars(5, start=datetime(2024, 3, 1, tzinfo=UTC))])
    assert any("gaps" in w for w in check_bars(gappy, "gap").warnings)
    jump = pl.concat([bars(5), bars(5, start=datetime(2024, 1, 6, tzinfo=UTC), price=10)])
    assert any("one-bar moves" in w for w in check_bars(jump, "jump").warnings)


def test_quality_checks_funding() -> None:
    df = pl.DataFrame(
        {"ts": [datetime(2024, 1, 1, tzinfo=UTC)], "rate": [0.2], "interval_hours": [8.0]}
    ).pipe(conform, "funding")
    rep = check_funding(df, "f")
    assert rep.ok
    assert rep.warnings


# Universe ---------------------------------------------------------------------------------
def test_universe_is_point_in_time() -> None:
    panel = {
        "BIG": bars(200, qv=5e6),
        "MID": bars(200, qv=2e6),
        "NEW": bars(60, start=datetime(2024, 5, 1, tzinfo=UTC), qv=9e9),  # too little history
    }
    uni = top_n_by_liquidity(panel, n=1, lookback_days=30, min_history_days=30)
    first_day = uni["ts"].min()
    assert first_day == datetime(2024, 1, 31, tzinfo=UTC)  # needs 30 prior days, uses days < D
    assert set(uni["symbol"]) <= {"BIG", "NEW"}

    # Changing the future must not change the past.
    cutoff = datetime(2024, 4, 1, tzinfo=UTC)
    future_shock = {
        k: v.with_columns(
            pl.when(pl.col("ts") >= cutoff)
            .then(pl.col("quote_volume") * 1000)
            .otherwise(pl.col("quote_volume"))
            .alias("quote_volume")
        )
        for k, v in panel.items()
    }
    future_shock["MID"] = future_shock["MID"].with_columns(
        pl.when(pl.col("ts") >= cutoff)
        .then(1e12)
        .otherwise(pl.col("quote_volume"))
        .alias("quote_volume")
    )
    uni2 = top_n_by_liquidity(future_shock, n=1, lookback_days=30, min_history_days=30)
    before = uni.filter(pl.col("ts") <= cutoff)
    before2 = uni2.filter(pl.col("ts") <= cutoff)
    assert before.select("ts", "symbol").equals(before2.select("ts", "symbol"))


# Sync -------------------------------------------------------------------------------------
def test_jobs_config_is_valid() -> None:
    jobs = load_jobs(CONFIG_DIR)
    assert {j.name for j in jobs} >= {
        "crypto_spot_daily",
        "crypto_perp_funding",
        "india_etf_daily",
        "polymarket_snapshot",
    }
    spot = next(j for j in jobs if j.name == "crypto_spot_daily")
    assert {"LUNAUSDT", "FTTUSDT"} <= set(spot.symbols)  # survivorship guard


def test_sync_respects_jurisdiction(base_settings: Settings, tmp_path: Path) -> None:
    india = settings_for(base_settings, "india")
    job = DataJob(
        name="pm",
        source="polymarket",
        venue="polymarket",
        dataset="pm_snapshots",
        start=date(2026, 1, 1),
        symbols=["open_markets"],
    )

    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Polymarket under the india profile")

    assert run_job(job, india, Catalog(tmp_path), client_for(httpx.MockTransport(handler))) == []
