"""`mm`: the one terminal. Commands not yet built say which phase delivers them."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from mm import __version__
from mm.config import load_settings
from mm.control.alerts import send_alert
from mm.db.session import init_db, make_engine
from mm.db.state import StateStore

app = typer.Typer(help="MONEYMAKER control terminal. See SPEC.md.", no_args_is_help=True)
jurisdiction_app = typer.Typer(help="Show or change the active jurisdiction profile.")
db_app = typer.Typer(help="Database maintenance.")
data_app = typer.Typer(help="Data lake: sync, status, quality checks.")
app.add_typer(jurisdiction_app, name="jurisdiction")
app.add_typer(db_app, name="db")
app.add_typer(data_app, name="data")
paper_app = typer.Typer(help="Paper trading against live prices (no keys, no real money).")
app.add_typer(paper_app, name="paper")

console = Console()


def _store() -> StateStore:
    engine = make_engine()
    init_db(engine)
    return StateStore(engine)


def _not_yet(phase: int, what: str) -> None:
    console.print(f"[yellow]{what} arrives in build phase {phase} (SPEC.md section 11).[/yellow]")
    raise typer.Exit(code=2)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"mm {__version__}")


@app.command()
def status() -> None:
    """Mode, jurisdiction, kill switch and paused strategies."""
    settings = load_settings()
    store = _store()
    kill = store.kill_status()
    table = Table(title="MONEYMAKER status", show_header=False)
    table.add_row("mode", str(settings.mode))
    table.add_row("jurisdiction", settings.jurisdiction.active)
    table.add_row(
        "kill switch",
        f"[red]ENGAGED[/red] ({kill.get('reason')}, by {kill.get('by')})"
        if kill.get("engaged")
        else "[green]off[/green]",
    )
    paused = store.paused()
    table.add_row("paused", ", ".join(sorted(paused)) if paused else "none")
    table.add_row("venues configured", ", ".join(sorted(settings.venues)))
    console.print(table)


@app.command()
def kill(
    reason: Annotated[str, typer.Option(help="Why the kill switch is being engaged")] = "manual",
    flatten: Annotated[bool, typer.Option(help="Also close all positions")] = False,
) -> None:
    """Engage the kill switch: block every new risk-increasing order."""
    store = _store()
    store.engage_kill(reason=reason, actor="human")
    console.print("[red]Kill switch ENGAGED.[/red] Only position-reducing orders will pass.")
    if flatten:
        console.print("[yellow]Flatten requested: execution adapters arrive in phase 5.[/yellow]")
    send_alert(f"MONEYMAKER kill switch engaged: {reason}")


@app.command()
def unkill(
    confirm: Annotated[str, typer.Option(prompt="Type RELEASE to release the kill switch")],
) -> None:
    """Release the kill switch (human only, typed confirmation)."""
    if confirm != "RELEASE":
        console.print("Not released.")
        raise typer.Exit(code=1)
    _store().release_kill(actor="human")
    console.print("[green]Kill switch released.[/green]")
    send_alert("MONEYMAKER kill switch released by human")


@app.command()
def pause(strategy_id: str) -> None:
    """Pause a strategy: no new entries, exits still allowed."""
    _store().pause(strategy_id, actor="human")
    console.print(f"Paused {strategy_id}.")


@app.command()
def resume(strategy_id: str) -> None:
    """Resume a paused strategy (human only)."""
    _store().resume(strategy_id, actor="human")
    console.print(f"Resumed {strategy_id}.")


@jurisdiction_app.command("show")
def jurisdiction_show(
    name: Annotated[str | None, typer.Argument(help="Profile to show (default: active)")] = None,
) -> None:
    """What each venue allows under a jurisdiction profile."""
    settings = load_settings()
    profile = settings.jurisdictions[name] if name else settings.active_jurisdiction
    table = Table(title=f"Jurisdiction: {profile.name}  (max leverage {profile.max_leverage}x)")
    for col in ("venue", "read", "trades", "note"):
        table.add_column(col)
    for venue, perm in sorted(profile.venues.items()):
        products = [
            p
            for p in ("spot", "perps", "futures", "options", "stocks", "etfs", "prediction")
            if getattr(perm, p)
        ]
        table.add_row(venue, "yes" if perm.read else "no", ", ".join(products) or "-", perm.note)
    console.print(table)
    for note in profile.notes:
        console.print(f"- {note}")


@jurisdiction_app.command("set")
def jurisdiction_set(name: str) -> None:
    """Change the active profile. Human only: edit config/base.yaml directly."""
    settings = load_settings()
    if name not in settings.jurisdictions:
        console.print(
            f"Unknown profile '{name}'. Have: {', '.join(sorted(settings.jurisdictions))}"
        )
        raise typer.Exit(code=1)
    console.print(
        "The active jurisdiction is a human decision and is changed by editing "
        f"`jurisdiction.active` in config/base.yaml to '{name}'. "
        "This command deliberately does not write it, so no agent can change it."
    )


@db_app.command("init")
def db_init() -> None:
    """Create tables (idempotent)."""
    engine = make_engine()
    init_db(engine)
    console.print(f"Database ready: {engine.url.render_as_string(hide_password=True)}")


@data_app.command("sync")
def data_sync(
    job: Annotated[str | None, typer.Option(help="Run one job by name (default: all)")] = None,
) -> None:
    """Fetch new data from official sources, quality-check it and write it to the lake."""
    from mm.data.catalog import Catalog
    from mm.data.http import PoliteClient
    from mm.data.quality import QualityReport
    from mm.data.sync import load_jobs, run_job

    settings = load_settings()
    jobs = [j for j in load_jobs() if job is None or j.name == job]
    if not jobs:
        console.print(f"No job named '{job}'.")
        raise typer.Exit(code=1)
    cat = Catalog()

    def show(rep: QualityReport) -> None:
        mark = "[green]ok[/green]" if rep.ok else "[red]FAIL[/red]"
        extra = "; ".join(rep.errors + rep.warnings)
        console.print(f"  {mark} {rep.name} rows={rep.rows} {extra}")

    failures = 0
    with PoliteClient() as client:
        for j in jobs:
            console.print(f"[bold]{j.name}[/bold] ({j.source})")
            failures += sum(not r.ok for r in run_job(j, settings, cat, client, on_report=show))
    manifest = cat.write_manifest()
    console.print(f"Snapshot {manifest['snapshot_id']}  failures={failures}")
    if failures:
        raise typer.Exit(code=1)


@data_app.command("status")
def data_status() -> None:
    """What is in the lake: rows and date range per file, plus the snapshot ID."""
    from mm.data.catalog import Catalog

    cat = Catalog()
    entries = cat.entries()
    table = Table(title=f"Data lake  snapshot {cat.snapshot_id(entries)}")
    for col in ("file", "rows", "start", "end"):
        table.add_column(col)
    for e in entries:
        table.add_row(e.path, str(e.rows), (e.start or "")[:10], (e.end or "")[:10])
    console.print(table)


@data_app.command("check")
def data_check() -> None:
    """Re-run quality checks on everything in the lake."""
    import polars as pl

    from mm.data.catalog import Catalog
    from mm.data.quality import check_bars, check_funding

    cat = Catalog()
    bad = 0
    for path in sorted(cat.root.glob("*/*/*.parquet")):
        dataset = path.parts[-3]
        if dataset not in ("bars_1d", "funding"):
            continue
        df = pl.read_parquet(path)
        name = str(path.relative_to(cat.root))
        rep = check_funding(df, name) if dataset == "funding" else check_bars(df, name)
        if not rep.ok or rep.warnings:
            console.print(
                f"{'FAIL' if not rep.ok else 'warn'} {name}: {'; '.join(rep.errors + rep.warnings)}"
            )
        bad += not rep.ok
    console.print(f"{bad} files failing")
    if bad:
        raise typer.Exit(code=1)


@app.command()
def backtest(strategy: str) -> None:
    """Backtest a strategy with its base parameters and print the summary."""
    from mm.research.pipeline import _run
    from mm.strategies import get
    from mm.validation.metrics import summarize

    spec = get(strategy)
    res = _run(spec, spec.load_data(), dict(spec.base_params))
    s = summarize(res.net, spec.periods_per_year)
    table = Table(title=f"{strategy} base backtest (net of costs)", show_header=False)
    for k, v in s.as_dict().items():
        table.add_row(k, f"{v:.4f}")
    table.add_row("annual_turnover", f"{res.annual_turnover:.2f}")
    table.add_row("annual_cost_drag", f"{res.annual_cost_drag:.4f}")
    console.print(table)


@app.command()
def gate(
    strategy: str,
    max_variants: Annotated[int | None, typer.Option(help="Cap sweep size (dev only)")] = None,
) -> None:
    """Run gates G0 and G1 (sweep, walk-forward, DSR, PBO) and save the report."""
    from mm.research.pipeline import run_pipeline
    from mm.strategies import get
    from mm.validation.experiments import ExperimentLog

    engine = make_engine()
    init_db(engine)
    res = run_pipeline(
        get(strategy), ExperimentLog(engine), progress=console.print, max_variants=max_variants
    )
    console.print(res.g0.to_markdown())
    if res.g1:
        console.print(res.g1.to_markdown())
    passed = res.g0.passed and res.g1 is not None and res.g1.passed
    console.print("[green]PASSED[/green]" if passed else "[red]FAILED[/red]")
    raise typer.Exit(code=0 if passed else 1)


@app.command()
def strategies() -> None:
    """List registered strategies."""
    from mm.strategies import all_ids, get

    for sid in all_ids():
        sp = get(sid)
        console.print(f"{sid}  kind={sp.kind} venue={sp.venue} family={sp.family}")


@app.command()
def promote(strategy: str, to: str = typer.Option(..., "--to")) -> None:
    """Request promotion to the next stage (human approval workflow)."""
    _not_yet(6, f"`mm promote {strategy} --to {to}`")


@paper_app.command("run")
def paper_run(
    strategy: str,
    capital: Annotated[float, typer.Option(help="Starting paper capital in USD")] = 1500.0,
) -> None:
    """One paper rebalance: latest signal, live Hyperliquid prices, conservative taker fills."""
    from decimal import Decimal

    from mm.data.http import PoliteClient
    from mm.execution.hyperliquid_md import HyperliquidMD
    from mm.execution.paper import run_paper
    from mm.strategies import get

    engine = make_engine()
    init_db(engine)
    with PoliteClient() as client:
        rep = run_paper(
            get(strategy),
            load_settings(),
            engine,
            HyperliquidMD(client),
            capital=Decimal(str(capital)),
        )
    console.print(f"[bold]{strategy}[/bold] paper run {rep.ts:%Y-%m-%d %H:%M} UTC")
    console.print(
        f"equity ${rep.equity:.2f}  cash ${rep.cash:.2f}  funding paid ${rep.funding_paid:.4f}"
    )
    for f in rep.fills:
        console.print(f"  [green]fill[/green] {f}")
    for r in rep.rejections:
        console.print(f"  [red]rejected[/red] {r}")
    for k in rep.skipped:
        console.print(f"  [yellow]skipped[/yellow] {k}")


@paper_app.command("status")
def paper_status(strategy: str) -> None:
    """Paper positions, equity history and recent orders."""
    from sqlalchemy import select

    from mm.db.schema import EquitySnapshot, OrderRecord, SystemState
    from mm.db.session import session_scope

    engine = make_engine()
    init_db(engine)
    with session_scope(engine) as s:
        acct = s.get(SystemState, f"paper:{strategy}")
        snaps = s.scalars(
            select(EquitySnapshot)
            .where(EquitySnapshot.sleeve == strategy, EquitySnapshot.mode == "paper")
            .order_by(EquitySnapshot.ts)
        ).all()
        orders = s.scalars(
            select(OrderRecord)
            .where(OrderRecord.strategy_id == strategy)
            .order_by(OrderRecord.created_at.desc())
            .limit(10)
        ).all()
        if acct is None:
            console.print(f"No paper account for {strategy} yet. Run `mm paper run {strategy}`.")
            raise typer.Exit(code=1)
        v = dict(acct.value)
        console.print(f"capital ${float(v['capital']):.2f}  cash ${float(v['cash']):.2f}")
        for coin, pos in v.get("positions", {}).items():
            console.print(f"  {coin}: qty {pos['qty']} avg {float(pos['avg']):.4f}")
        if snaps:
            first, last = float(snaps[0].equity_usd), float(snaps[-1].equity_usd)
            console.print(
                f"equity: {len(snaps)} snapshots, ${first:.2f} -> ${last:.2f} "
                f"({last / float(v['capital']) - 1:+.2%} since start)"
            )
        for o in orders:
            console.print(
                f"  {o.created_at:%Y-%m-%d} {o.status:8} {o.side} {o.quantity} {o.symbol}"
            )


theme_app = typer.Typer(help="Theme-call sleeve: record manual theme calls, score them vs QQQ.")
app.add_typer(theme_app, name="theme")
exp_app = typer.Typer(help="Experiment log: trial counts per family, export, back-fill.")
app.add_typer(exp_app, name="experiments")


@theme_app.command("add")
def theme_add(
    ticker: str,
    thesis: Annotated[str, typer.Option(help="One line: why this theme, why now")],
    on: Annotated[
        str | None, typer.Option("--date", help="Call date YYYY-MM-DD (default today)")
    ] = None,
    horizon_days: Annotated[int, typer.Option(help="Days the call is scored over")] = 180,
) -> None:
    """Record a theme call in ledger/theme_calls.csv. Entry is the first close after the date."""
    from datetime import UTC, date, datetime

    from mm.research.theme_calls import ThemeCall, add_call

    d = date.fromisoformat(on) if on else datetime.now(UTC).date()
    add_call(ThemeCall(d, ticker.upper(), thesis, horizon_days))
    console.print(f"Recorded {ticker.upper()} on {d} ({horizon_days}d): {thesis}")


@theme_app.command("report")
def theme_report() -> None:
    """Score every recorded call against QQQ over the same dates."""
    from mm.research.theme_calls import load_calls, score, summary, yahoo_prices

    calls = load_calls()
    if not calls:
        console.print("No theme calls yet. Add one with `mm theme add TICKER --thesis '...'`.")
        return
    scored = score(calls, yahoo_prices)
    table = Table(title="Theme calls vs QQQ")
    for col in ("date", "ticker", "status", "ret", "qqq", "excess", "thesis"):
        table.add_column(col)
    for r in scored.iter_rows(named=True):

        def f(x: float | None) -> str:
            return "-" if x is None else f"{x:+.1%}"

        table.add_row(str(r["date"]), r["ticker"], r["status"], f(r["ret"]), f(r["qqq"]),
                      f(r["excess"]), str(r["thesis"])[:50])  # fmt: skip
    console.print(table)
    for k, v in summary(scored).items():
        console.print(f"{k}: {v:.3f}")


@exp_app.command("list")
def experiments_list() -> None:
    """Trial count per experiment family (the N in each Deflated Sharpe)."""
    from sqlalchemy import func, select

    from mm.db.schema import Experiment
    from mm.db.session import session_scope

    engine = make_engine()
    init_db(engine)
    with session_scope(engine) as s:
        rows = s.execute(select(Experiment.family, func.count()).group_by(Experiment.family)).all()
    for fam, n in sorted(rows):
        console.print(f"{fam}: {n}")


@exp_app.command("export")
def experiments_export(family: str, out: str) -> None:
    """Write every logged trial of a family to CSV (the local DB is not in git)."""
    from mm.validation.experiments import ExperimentLog

    engine = make_engine()
    init_db(engine)
    n = ExperimentLog(engine).export_csv(family, out)
    console.print(f"{n} trials of {family} -> {out}")


@exp_app.command("backfill")
def experiments_backfill(family: str, csv_path: str, strategy_id: str) -> None:
    """Log a research grid CSV (one row per variant) as trials, once. Keeps DSR counts honest
    when trials were run before the experiment DB existed or on another machine."""
    from mm.validation.experiments import ExperimentLog

    engine = make_engine()
    init_db(engine)
    n = ExperimentLog(engine).backfill_csv(family, csv_path, strategy_id)
    console.print(f"back-filled {n} trials into {family}")
