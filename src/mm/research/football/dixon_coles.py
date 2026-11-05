"""Dixon-Coles (1997) team-strength model with exponential time decay.

log(lambda_home) = home + attack[h] - defence[a]
log(mu_away)     =        attack[a] - defence[h]
P(x, y) = tau(x, y) * Poisson(x; lambda) * Poisson(y; mu), with the low-score correction tau
governed by rho. Matches are weighted by exp(-xi * age_days). A small ridge penalty keeps
teams with few matches near average, and a sum-to-zero penalty pins the attack scale.

Fitting is point-in-time: `fit` only ever sees matches strictly before `as_of`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import polars as pl
from numpy.typing import NDArray
from scipy.optimize import minimize  # type: ignore[import-untyped]
from scipy.stats import poisson  # type: ignore[import-untyped]

Arr = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class DCConfig:
    xi: float = 0.002  # decay per day (half-life ~ ln2/xi = 347 days)
    window_days: int = 3 * 365  # matches older than this are dropped
    ridge: float = 0.05  # L2 on attack/defence
    max_goals: int = 10
    unknown_quantile: float = 0.2  # strength given to a team with no history (promoted sides)


@dataclass(frozen=True, slots=True)
class DCModel:
    teams: tuple[str, ...]
    attack: Arr
    defence: Arr
    home: float
    rho: float
    as_of: date
    n_matches: int
    config: DCConfig

    def _idx(self, team: str) -> tuple[float, float]:
        if team in self.teams:
            i = self.teams.index(team)
            return float(self.attack[i]), float(self.defence[i])
        q = self.config.unknown_quantile
        return float(np.quantile(self.attack, q)), float(np.quantile(self.defence, q))

    def rates(self, home: str, away: str) -> tuple[float, float]:
        ah, dh = self._idx(home)
        aa, da = self._idx(away)
        return float(np.exp(self.home + ah - da)), float(np.exp(aa - dh))

    def score_matrix(self, home: str, away: str) -> Arr:
        lam, mu = self.rates(home, away)
        g = np.arange(self.config.max_goals + 1)
        m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
        m[0, 0] *= max(1 - lam * mu * self.rho, 1e-10)
        m[0, 1] *= max(1 + lam * self.rho, 1e-10)
        m[1, 0] *= max(1 + mu * self.rho, 1e-10)
        m[1, 1] *= max(1 - self.rho, 1e-10)
        return m / m.sum()

    def outcome_probs(self, home: str, away: str) -> tuple[float, float, float]:
        m = self.score_matrix(home, away)
        return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def _nll_and_grad(
    theta: Arr,
    hi: NDArray[np.int64],
    ai: NDArray[np.int64],
    x: Arr,
    y: Arr,
    w: Arr,
    n: int,
    ridge: float,
) -> tuple[float, Arr]:
    att, dfn = theta[:n], theta[n : 2 * n]
    home, rho = theta[2 * n], theta[2 * n + 1]
    log_lam = home + att[hi] - dfn[ai]
    log_mu = att[ai] - dfn[hi]
    lam, mu = np.exp(log_lam), np.exp(log_mu)

    tau = np.ones_like(lam)
    dtau_dlam = np.zeros_like(lam)
    dtau_dmu = np.zeros_like(lam)
    dtau_drho = np.zeros_like(lam)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    tau[m00] = 1 - lam[m00] * mu[m00] * rho
    dtau_dlam[m00] = -mu[m00] * rho
    dtau_dmu[m00] = -lam[m00] * rho
    dtau_drho[m00] = -lam[m00] * mu[m00]
    tau[m01] = 1 + lam[m01] * rho
    dtau_dlam[m01] = rho
    dtau_drho[m01] = lam[m01]
    tau[m10] = 1 + mu[m10] * rho
    dtau_dmu[m10] = rho
    dtau_drho[m10] = mu[m10]
    tau[m11] = 1 - rho
    dtau_drho[m11] = -1.0
    tau = np.maximum(tau, 1e-10)

    ll = w * (np.log(tau) + x * log_lam - lam + y * log_mu - mu)
    pen = ridge * (att @ att + dfn @ dfn) + 10.0 * att.sum() ** 2
    nll = -float(ll.sum()) + float(pen)

    # d ll / d log_lam = x - lam + lam * dtau_dlam / tau
    g_lam = w * (x - lam + lam * dtau_dlam / tau)
    g_mu = w * (y - mu + mu * dtau_dmu / tau)
    g_rho = float((w * dtau_drho / tau).sum())
    g_att = np.zeros(n)
    g_def = np.zeros(n)
    np.add.at(g_att, hi, g_lam)
    np.add.at(g_att, ai, g_mu)
    np.add.at(g_def, ai, -g_lam)
    np.add.at(g_def, hi, -g_mu)
    grad = -np.concatenate([g_att, g_def, [g_lam.sum(), g_rho]])
    grad[:n] += 2 * ridge * att + 20.0 * att.sum()
    grad[n : 2 * n] += 2 * ridge * dfn
    return nll, grad


def fit(
    matches: pl.DataFrame,
    as_of: date,
    config: DCConfig | None = None,
    warm: DCModel | None = None,
) -> DCModel:
    """Fit on matches (date, home, away, hg, ag) played strictly before `as_of`."""
    cfg = config or DCConfig()
    hist = matches.filter(pl.col("date") < as_of)
    hist = hist.filter(pl.col("date") >= as_of - timedelta(days=cfg.window_days))
    if hist.height < 50:
        raise ValueError(f"only {hist.height} matches before {as_of}; need >= 50")
    teams = tuple(sorted(set(hist["home"].to_list()) | set(hist["away"].to_list())))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.array([idx[t] for t in hist["home"].to_list()], dtype=np.int64)
    ai = np.array([idx[t] for t in hist["away"].to_list()], dtype=np.int64)
    x = hist["hg"].to_numpy().astype(np.float64)
    y = hist["ag"].to_numpy().astype(np.float64)
    age = np.array([(as_of - d).days for d in hist["date"].to_list()], dtype=np.float64)
    w = np.exp(-cfg.xi * age)

    theta0 = np.zeros(2 * n + 2)
    theta0[2 * n] = 0.25
    theta0[2 * n + 1] = -0.05
    if warm is not None:
        for t, i in idx.items():
            if t in warm.teams:
                j = warm.teams.index(t)
                theta0[i], theta0[n + i] = warm.attack[j], warm.defence[j]
        theta0[2 * n], theta0[2 * n + 1] = warm.home, warm.rho
    bounds = [(None, None)] * (2 * n + 1) + [(-0.3, 0.3)]
    res = minimize(
        _nll_and_grad,
        theta0,
        args=(hi, ai, x, y, w, n, cfg.ridge),
        jac=True,
        method="L-BFGS-B",
        bounds=bounds,
    )
    th = np.asarray(res.x, dtype=np.float64)
    return DCModel(
        teams=teams,
        attack=th[:n].copy(),
        defence=th[n : 2 * n].copy(),
        home=float(th[2 * n]),
        rho=float(th[2 * n + 1]),
        as_of=as_of,
        n_matches=hist.height,
        config=cfg,
    )


def simulate_season(
    model: DCModel,
    played: pl.DataFrame,
    teams: list[str],
    n_sims: int = 10_000,
    seed: int = 0,
) -> pl.DataFrame:
    """Monte Carlo of the rest of a double round-robin season.

    `played`: this season's results so far (home, away, hg, ag). Remaining fixtures are every
    ordered (home, away) pair not yet played. Returns per-team expected points and probabilities
    of finishing 1st, top 4 and bottom 3 (ties broken by goal difference, then at random).
    """
    rng = np.random.default_rng(seed)
    k = len(teams)
    ti = {t: i for i, t in enumerate(teams)}
    pts = np.zeros(k)
    gd = np.zeros(k)
    done: set[tuple[str, str]] = set()
    for h, a, hg, ag in played.select("home", "away", "hg", "ag").iter_rows():
        done.add((h, a))
        gd[ti[h]] += hg - ag
        gd[ti[a]] += ag - hg
        if hg > ag:
            pts[ti[h]] += 3
        elif hg < ag:
            pts[ti[a]] += 3
        else:
            pts[ti[h]] += 1
            pts[ti[a]] += 1
    remaining = [(h, a) for h in teams for a in teams if h != a and (h, a) not in done]
    sim_pts = np.tile(pts, (n_sims, 1))
    sim_gd = np.tile(gd, (n_sims, 1))
    g = model.config.max_goals + 1
    for h, a in remaining:
        m = model.score_matrix(h, a).ravel()
        draws = rng.choice(m.size, size=n_sims, p=m)
        hg, ag = draws // g, draws % g
        hw, aw, dr = hg > ag, hg < ag, hg == ag
        sim_pts[:, ti[h]] += 3 * hw + dr
        sim_pts[:, ti[a]] += 3 * aw + dr
        sim_gd[:, ti[h]] += hg - ag
        sim_gd[:, ti[a]] += ag - hg
    key = sim_pts * 1000 + sim_gd + rng.random((n_sims, k)) * 1e-3
    rank = (-key).argsort(axis=1).argsort(axis=1)  # 0 = first
    return pl.DataFrame(
        {
            "team": teams,
            "points_now": pts,
            "exp_points": sim_pts.mean(axis=0),
            "p_title": (rank == 0).mean(axis=0),
            "p_top4": (rank < 4).mean(axis=0),
            "p_bottom3": (rank >= k - 3).mean(axis=0),
        }
    ).sort("exp_points", descending=True)
