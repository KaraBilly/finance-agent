"""CLI entry — `python -m finance_agent ask "..."`

Subcommands:
  ask "..."             Run one turn and print answer.
  chat                  Start interactive multi-turn chat session.
  prefs                 Show stored user preferences.
  clear-prefs           Wipe stored user preferences.
  init                  Initialise DB & data dirs.
  bootstrap-indices     Pre-download 20y A-share indices.
"""
from __future__ import annotations
import logging

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from .agent import AgentLoop
from .config import CONFIG
from .render import write_outputs
from .providers import SQLiteStorageProvider

console = Console()


def _configure_logging():
    logging.basicConfig(
        level=getattr(logging, CONFIG.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )


@click.group()
def cli():
    """Finance Personal Agent (A-share) — doubao + deepseek."""
    _configure_logging()


@cli.command()
@click.argument("question", nargs=-1, required=True)
@click.option("--quiet", is_flag=True, help="Suppress plan/trace panels.")
def ask(question, quiet):
    """Ask a single question."""
    q = " ".join(question)
    console.rule(f"[bold cyan]Q: {q}")
    loop = AgentLoop()
    result = loop.ask(q)

    if not quiet:
        # Plan panel
        tbl = Table(title="Tool Plan", show_header=True, header_style="bold magenta")
        tbl.add_column("tool")
        tbl.add_column("args")
        for t in result.plan.get("tools", []):
            tbl.add_row(str(t.get("tool")), str(t.get("args")))
        console.print(tbl)

    console.rule("[bold green]Answer")
    console.print(Markdown(result.answer_md))

    paths = write_outputs(result)
    console.rule("[bold]Saved")
    for k, v in paths.items():
        console.print(f"  {k}: {v}")

    if result.prefs_updated:
        console.print("[dim]memory updates:[/dim] "
                      + ", ".join(f"{p['topic']}={p['weight']:.2f}" for p in result.prefs_updated))

    if result.conversation_id:
        console.print(f"[dim]conversation: {result.conversation_id}[/dim]")


@cli.command()
@click.option("--conversation-id", help="Continue existing conversation")
def chat(conversation_id):
    """Start interactive multi-turn chat session."""
    loop = AgentLoop()
    current_conv_id = conversation_id
    
    console.print("[bold green]Finance Agent Chat[/bold green]")
    console.print("[dim]Type 'exit' or 'quit' to end, 'new' to start fresh conversation[/dim]")
    console.rule()
    
    while True:
        try:
            question = console.input("[bold cyan]You: [/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            break
        
        question = question.strip()
        if not question:
            continue
        if question.lower() in ("exit", "quit", "q"):
            break
        if question.lower() == "new":
            current_conv_id = None
            console.print("[dim]Starting new conversation...[/dim]")
            continue
        
        console.rule(f"[bold magenta]Thinking...[/bold magenta]")
        result = loop.ask(question, conversation_id=current_conv_id)
        current_conv_id = result.conversation_id
        
        console.rule("[bold green]Answer")
        console.print(Markdown(result.answer_md))
        
        if result.prefs_updated:
            console.print("[dim]memory updates:[/dim] "
                          + ", ".join(f"{p['topic']}={p['weight']:.2f}" for p in result.prefs_updated))
        
        console.print(f"[dim]conversation: {result.conversation_id}[/dim]")
        console.rule()


@cli.command()
def prefs():
    """Show current user preferences."""
    storage = SQLiteStorageProvider()
    storage.init()
    rows = storage.load_prefs()
    if not rows:
        console.print("[dim](no preferences yet)[/dim]")
        return
    tbl = Table(title="User Preferences")
    tbl.add_column("topic")
    tbl.add_column("weight")
    tbl.add_column("note")
    for r in rows:
        tbl.add_row(r["topic"], f"{r['weight']:.2f}", r.get("note") or "")
    console.print(tbl)


@cli.command("clear-prefs")
def clear_prefs():
    """Delete all stored user preferences."""
    storage = SQLiteStorageProvider()
    storage.init()
    # Direct SQL for clearing - could add to StorageCapability if needed
    import sqlite3
    conn = sqlite3.connect(CONFIG.db_path)
    conn.execute("DELETE FROM user_prefs")
    conn.commit()
    conn.close()
    console.print("[green]cleared.[/green]")


@cli.command()
def init():
    """Create DB and data directories."""
    storage = SQLiteStorageProvider()
    storage.init()
    console.print(f"[green]initialised[/green] db={CONFIG.db_path}")


@cli.command("bootstrap-indices")
@click.argument("symbols", nargs=-1)
def bootstrap_indices(symbols):
    """Pre-download ~20y daily data for major A-share indices."""
    from .providers import AkshareMarketProvider
    from datetime import datetime
    market = AkshareMarketProvider()
    catalog = market.list_available_indices()
    syms = list(symbols) or list(catalog.keys())
    end = datetime.now().strftime("%Y%m%d")
    start = str(int(end[:4]) - 20) + end[4:]
    for s in syms:
        try:
            df = market.get_index_daily(s, start=start, end=end)
            console.print(f"[green]{s}[/green] {catalog.get(s,'?')}: "
                          f"{len(df)} rows, {df['date'].min().date()}..{df['date'].max().date()}")
        except Exception as e:
            console.print(f"[red]{s} FAILED[/red]: {e}")


def main():
    cli(standalone_mode=True)


if __name__ == "__main__":
    main()
