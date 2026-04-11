from pathlib import Path

import typer
from rich.console import Console
from trademachine.metalabelingmaster.core import process_report

app = typer.Typer(help="Metalabeling Master CLI")
console = Console()


@app.command()
def process(
    report_path: Path = typer.Argument(
        ..., help="Path to the MT5 HTML report", exists=True, dir_okay=False
    ),
):
    """
    Process an MT5 HTML report, extract trades and generate meta-labels.
    """
    console.print(f"[bold blue]Processing report:[/bold blue] {report_path}")

    try:
        trades_df = process_report(str(report_path))

        if trades_df.empty:
            console.print("[bold red]No trades found or failed to parse.[/bold red]")
            raise typer.Exit(1)

        console.print(
            f"[bold green]Successfully extracted {len(trades_df)} trades.[/bold green]"
        )
        console.print(trades_df.to_string())

    except Exception as e:
        console.print(f"[bold red]Error processing report: {e}[/bold red]")
        raise typer.Exit(1)


def main():
    app()


if __name__ == "__main__":
    main()
