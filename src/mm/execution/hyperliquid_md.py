"""Hyperliquid public market data for paper fills: mids, top of book with depth, size decimals,
funding since a timestamp. Read-only, no keys."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mm.core.types import BookTop
from mm.data.http import PoliteClient

INFO = "https://api.hyperliquid.xyz/info"

# Binance spot symbol -> (Hyperliquid coin, price multiplier). k-prefixed coins are quoted per 1000.
SYMBOL_MAP: dict[str, tuple[str, int]] = {"SHIBUSDT": ("kSHIB", 1000), "PEPEUSDT": ("kPEPE", 1000)}


def hl_coin(binance_symbol: str) -> tuple[str, int]:
    if binance_symbol in SYMBOL_MAP:
        return SYMBOL_MAP[binance_symbol]
    return binance_symbol.removesuffix("USDT"), 1


@dataclass(frozen=True, slots=True)
class CoinMeta:
    name: str
    sz_decimals: int


class HyperliquidMD:
    def __init__(self, client: PoliteClient) -> None:
        self.c = client
        self._meta: dict[str, CoinMeta] | None = None

    def _post(self, body: dict[str, Any]) -> Any:
        resp = self.c.post(INFO, json=body)
        resp.raise_for_status()
        return resp.json()

    def meta(self) -> dict[str, CoinMeta]:
        if self._meta is None:
            uni = self._post({"type": "meta"})["universe"]
            self._meta = {
                u["name"]: CoinMeta(u["name"], int(u["szDecimals"]))
                for u in uni
                if not u.get("isDelisted")
            }
        return self._meta

    def mids(self) -> dict[str, Decimal]:
        return {k: Decimal(v) for k, v in self._post({"type": "allMids"}).items()}

    def book(self, coin: str, band: float = 0.005) -> BookTop:
        """Top of book, with resting size within `band` of the touch on each side."""
        levels = self._post({"type": "l2Book", "coin": coin})["levels"]
        bids, asks = levels[0], levels[1]
        bid, ask = Decimal(bids[0]["px"]), Decimal(asks[0]["px"])
        lo, hi = bid * Decimal(1 - band), ask * Decimal(1 + band)
        bid_depth = sum((Decimal(x["sz"]) for x in bids if Decimal(x["px"]) >= lo), Decimal(0))
        ask_depth = sum((Decimal(x["sz"]) for x in asks if Decimal(x["px"]) <= hi), Decimal(0))
        return BookTop(bid=bid, ask=ask, bid_depth_qty=bid_depth, ask_depth_qty=ask_depth)

    def funding_since(self, coin: str, start_ms: int) -> Decimal:
        """Sum of hourly funding rates since start_ms (positive = longs paid)."""
        rows = self._post({"type": "fundingHistory", "coin": coin, "startTime": start_ms})
        return sum((Decimal(r["fundingRate"]) for r in rows), Decimal(0))
