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
app.add_typer(jurisdiction_app, name="jurisdiction")
app.add_typer(db_app, name="db")

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


@app.command()
def data(action: str = typer.Argument("sync")) -> None:
    """Data ingestion."""
    _not_yet(2, f"`mm data {action}`")


@app.command()
def backtest(strategy: str, walkforward: bool = False) -> None:
    """Backtest a strategy."""
    _not_yet(4, f"`mm backtest {strategy}`")


@app.command()
def gate(strategy: str) -> None:
    """Run validation gates G0/G1 and print the report."""
    _not_yet(3, f"`mm gate {strategy}`")


@app.command()
def promote(strategy: str, to: str = typer.Option(..., "--to")) -> None:
    """Request promotion to the next stage (human approval workflow)."""
    _not_yet(6, f"`mm promote {strategy} --to {to}`")
