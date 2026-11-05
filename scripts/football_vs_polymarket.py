"""Compare the Dixon-Coles season simulation with Polymarket season futures (read-only) and log
proposals with an edge to the CLV queue. Nothing is traded: Polymarket trading is disabled in every
jurisdiction profile. Writes reports/research/football_vs_polymarket_2026.csv and appends to
ledger/football_proposals.jsonl.
"""

import difflib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from mm.config import load_settings
from mm.data.http import PoliteClient
from mm.research.football.proposals import ProposalQueue

EVENTS = {  # (div, metric in the simulation, Polymarket event slug)
    ("E0", "p_title"): "epl-2027-champion-20260701200428749",
    ("E0", "p_top4"): "premier-league-top-4-finishers-2026-27",
    ("F1", "p_title"): "ligue-1-2027-champion-20260701201053335",
}
ALIASES = {
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Nott'm Forest": "Nottingham Forest",
    "Newcastle": "Newcastle United",
    "Leeds": "Leeds United",
    "Ipswich": "Ipswich Town",
    "Hull": "Hull City",
    "Coventry": "Coventry City",
    "Paris SG": "Paris Saint-Germain",
    "Wolves": "Wolverhampton",
}
MIN_EDGE = 0.03

perm = load_settings().active_jurisdiction.venues.get("polymarket")
if perm is None or not perm.read:
    sys.exit("polymarket not readable under the active jurisdiction profile")

sim = pl.read_csv("reports/research/football_season_sim_2026.csv")
queue = ProposalQueue(Path("ledger/football_proposals.jsonl"))
rows = []
now = datetime.now(UTC)
with PoliteClient(min_interval_s=1.0) as c:
    for (div, metric), slug in EVENTS.items():
        resp = c.get("https://gamma-api.polymarket.com/events", params={"slug": slug})
        resp.raise_for_status()
        markets = resp.json()[0]["markets"]
        teams = sim.filter(pl.col("div") == div)
        names = teams["team"].to_list()
        for m in markets:
            pm_name = str(m.get("groupItemTitle") or "")
            ask = m.get("bestAsk")
            if not pm_name or ask is None or float(ask) >= 1 or m.get("closed"):
                continue
            match = next((k for k, v in ALIASES.items() if v == pm_name and k in names), None)
            if match is None:
                close = difflib.get_close_matches(pm_name, names, n=1, cutoff=0.6)
                match = close[0] if close else None
            if match is None:
                continue
            p = float(teams.filter(pl.col("team") == match)[metric][0])
            yes_mid = float(json.loads(m["outcomePrices"])[0])
            row = {
                "div": div,
                "market": metric,
                "team": match,
                "model_p": p,
                "pm_mid": yes_mid,
                "pm_ask": float(ask),
                "edge_vs_ask": p - float(ask),
                "liquidity": float(m.get("liquidityNum") or 0),
                "slug": m["slug"],
            }
            rows.append(row)
            prop = queue.propose(
                market=m["slug"],
                match=f"{div} 2026-27 {metric} {match}",
                outcome="YES",
                model_prob=min(p, 0.999),
                entry_price=float(ask),
                min_edge=MIN_EDGE,
                now=now,
            )
            if prop:
                print("proposal", prop.match, f"model {p:.3f} ask {float(ask):.3f}")
out = pl.DataFrame(rows).sort("div", "market", "model_p", descending=[False, False, True])
out.write_csv("reports/research/football_vs_polymarket_2026.csv")
with pl.Config(tbl_rows=60, tbl_width_chars=160):
    print(out.drop("slug"))
