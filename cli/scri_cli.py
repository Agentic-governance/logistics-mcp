"""SCRI Platform CLI -- サプライチェーンリスク分析ツール

Usage:
    python -m cli.scri_cli risk China
    python -m cli.scri_cli screen "Huawei"
    python -m cli.scri_cli route Yokohama Rotterdam
    python -m cli.scri_cli alerts --limit 5
    python -m cli.scri_cli bom sample_bom.csv --format json
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console()


def _risk_color(score: int) -> str:
    """スコアに応じた色を返す"""
    if score >= 80:
        return "red"
    elif score >= 60:
        return "yellow"
    elif score >= 40:
        return "cyan"
    elif score >= 20:
        return "green"
    return "dim"


def _risk_level(score: int) -> str:
    """スコアからリスクレベル文字列を返す"""
    if score >= 80:
        return "CRITICAL"
    elif score >= 60:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    elif score >= 20:
        return "LOW"
    return "MINIMAL"


@click.group()
@click.version_option(version="0.9.0", prog_name="scri")
def cli():
    """SCRI Platform CLI -- Supply Chain Risk Intelligence

    24-dimensional passive supply chain risk detection platform.
    """
    pass


@cli.command()
@click.argument("country")
@click.option("--detail", "-d", is_flag=True, help="Show all 24 dimensions")
def risk(country, detail):
    """Get risk score for a country.

    Example: scri risk China
    """
    from scoring.engine import calculate_risk_score, SupplierRiskScore

    with console.status(f"[bold green]Calculating risk for {country}..."):
        score = calculate_risk_score(
            f"cli_{country}", f"CLI: {country}",
            country=country, location=country,
        )
        d = score.to_dict()

    # Summary panel
    overall = d["overall_score"]
    level = d["risk_level"]
    color = _risk_color(overall)

    console.print(Panel(
        f"[bold {color}]{country}[/bold {color}]\n"
        f"Overall Risk Score: [{color}]{overall}/100[/{color}]\n"
        f"Risk Level: [{color}]{level}[/{color}]",
        title="SCRI Risk Assessment",
        border_style=color,
    ))

    if detail:
        # Full dimension table
        table = Table(title="24-Dimension Risk Breakdown")
        table.add_column("Dimension", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Weight", justify="right")
        table.add_column("Level")

        scores = d.get("scores", {})
        sorted_dims = sorted(scores.items(), key=lambda x: -x[1])
        for dim, val in sorted_dims:
            weight = SupplierRiskScore.WEIGHTS.get(dim, 0.0)
            dc = _risk_color(val)
            table.add_row(
                dim,
                f"[{dc}]{val}[/{dc}]",
                f"{weight:.0%}",
                f"[{dc}]{_risk_level(val)}[/{dc}]",
            )
        console.print(table)
    else:
        # Top 5 risks
        table = Table(title="Top Risk Dimensions")
        table.add_column("Dimension", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Level")

        scores = d.get("scores", {})
        sorted_dims = sorted(
            [(k, v) for k, v in scores.items() if v > 0],
            key=lambda x: -x[1],
        )[:5]
        for dim, val in sorted_dims:
            dc = _risk_color(val)
            table.add_row(dim, f"[{dc}]{val}[/{dc}]", f"[{dc}]{_risk_level(val)}[/{dc}]")
        console.print(table)


@cli.command()
@click.argument("entity_name")
@click.option("--country", "-c", default="", help="Country hint for screening")
def screen(entity_name, country):
    """Screen entity against sanctions lists.

    Example: scri screen 'Huawei'
    """
    from pipeline.sanctions.screener import screen_entity

    with console.status(f"[bold green]Screening {entity_name}..."):
        result = screen_entity(entity_name, country if country else None)

    if result.matched:
        console.print(Panel(
            f"[bold red]MATCH FOUND[/bold red]\n"
            f"Entity: {entity_name}\n"
            f"Matched: {result.matched_entity}\n"
            f"Score: {result.match_score:.0%}\n"
            f"Source: {result.source}",
            title="Sanctions Screening Result",
            border_style="red",
        ))
    else:
        console.print(Panel(
            f"[bold green]NO MATCH[/bold green]\n"
            f"Entity: {entity_name}\n"
            f"Score: {result.match_score:.0%}",
            title="Sanctions Screening Result",
            border_style="green",
        ))

    if result.evidence:
        console.print("\n[bold]Evidence:[/bold]")
        for ev in result.evidence:
            console.print(f"  - {ev}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", default="json", type=click.Choice(["json", "csv"]))
def bom(file, fmt):
    """Analyze BOM risk from a file.

    Example: scri bom sample_bom.csv --format csv
    """
    import csv as csv_mod
    from features.analytics.bom_analyzer import BOMAnalyzer, BOMNode

    with open(file, "r") as fh:
        if fmt == "csv" or file.endswith(".csv"):
            reader = csv_mod.DictReader(fh)
            items = list(reader)
        else:
            items = json.load(fh)
            if isinstance(items, dict):
                items = items.get("bom", items.get("parts", items.get("components", [])))

    bom_nodes = []
    for item in items:
        bom_nodes.append(BOMNode(
            part_id=item.get("part_id", ""),
            part_name=item.get("part_name", ""),
            supplier_name=item.get("supplier_name", ""),
            supplier_country=item.get("supplier_country", ""),
            material=item.get("material", ""),
            hs_code=item.get("hs_code", ""),
            tier=int(item.get("tier", 1)),
            quantity=float(item.get("quantity", 1)),
            unit_cost_usd=float(item.get("unit_cost_usd", 0)),
            is_critical=str(item.get("is_critical", "false")).lower() in ("true", "1", "yes"),
        ))

    with console.status("[bold green]Analyzing BOM risk..."):
        analyzer = BOMAnalyzer()
        result = analyzer.analyze_bom(bom_nodes, os.path.basename(file))

    rd = result.to_dict()

    # Summary
    overall = rd.get("overall_risk_score", 0)
    color = _risk_color(overall)
    console.print(Panel(
        f"Product: {rd.get('product_name', file)}\n"
        f"Parts: {rd.get('total_parts', len(items))}\n"
        f"Overall Risk: [{color}]{overall}/100[/{color}]\n"
        f"Risk Level: [{color}]{rd.get('risk_level', 'N/A')}[/{color}]",
        title="BOM Risk Analysis",
        border_style=color,
    ))

    # Part details table
    table = Table(title="Part Risk Details")
    table.add_column("Part", style="bold")
    table.add_column("Supplier")
    table.add_column("Country")
    table.add_column("Risk", justify="right")

    for part in rd.get("parts", [])[:15]:
        dc = _risk_color(part.get("risk_score", 0))
        table.add_row(
            part.get("part_name", ""),
            part.get("supplier_name", ""),
            part.get("supplier_country", ""),
            f"[{dc}]{part.get('risk_score', 0)}[/{dc}]",
        )
    console.print(table)


@cli.command()
@click.argument("origin")
@click.argument("destination")
def route(origin, destination):
    """Analyze route risk between two locations.

    Example: scri route Yokohama Rotterdam
    """
    from features.route_risk.analyzer import RouteRiskAnalyzer

    with console.status(f"[bold green]Analyzing route {origin} -> {destination}..."):
        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route(origin, destination)

    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/red]")
        return

    risk = result.get("route_risk", 0)
    color = _risk_color(risk)
    console.print(Panel(
        f"Route: {origin} -> {destination}\n"
        f"Distance: {result.get('distance_km', 'N/A')} km\n"
        f"Route Risk: [{color}]{risk}/100[/{color}]\n"
        f"Risk Level: [{color}]{result.get('risk_level', 'N/A')}[/{color}]",
        title="Route Risk Analysis",
        border_style=color,
    ))

    # Chokepoints
    chokepoints = result.get("chokepoints_passed", [])
    if chokepoints:
        table = Table(title="Chokepoints Passed")
        table.add_column("Name", style="bold")
        table.add_column("Risk", justify="right")
        for cp in chokepoints:
            cp_risk = cp.get("risk", {}).get("risk_score", 0)
            dc = _risk_color(cp_risk)
            table.add_row(cp.get("name", ""), f"[{dc}]{cp_risk}[/{dc}]")
        console.print(table)

    # Alternative routes
    alts = result.get("alternative_routes", [])
    if alts:
        console.print("\n[bold]Alternative Routes:[/bold]")
        for alt in alts:
            alt_risk = alt.get("risk_score", 0)
            dc = _risk_color(alt_risk)
            console.print(f"  - {alt['route_name']}: [{dc}]risk {alt_risk}[/{dc}]")


@cli.command()
@click.option("--limit", "-n", default=10, help="Number of alerts to show")
@click.option("--hours", "-h", "since_hours", default=24, help="Hours back to search")
@click.option("--min-score", "-s", default=50, help="Minimum alert score")
def alerts(limit, since_hours, min_score):
    """List recent risk alerts.

    Example: scri alerts --limit 5
    """
    from pipeline.db import Session
    from pipeline.gdelt.monitor import RiskAlert
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(hours=since_hours)

    with Session() as session:
        alert_list = (
            session.query(RiskAlert)
            .filter(
                RiskAlert.created_at >= since,
                RiskAlert.score >= min_score,
            )
            .order_by(RiskAlert.created_at.desc())
            .limit(limit)
            .all()
        )

        if not alert_list:
            console.print("[dim]No alerts found in the specified time range.[/dim]")
            return

        table = Table(title=f"Risk Alerts (last {since_hours}h, score >= {min_score})")
        table.add_column("ID", style="dim")
        table.add_column("Supplier", style="bold")
        table.add_column("Type")
        table.add_column("Score", justify="right")
        table.add_column("Severity")
        table.add_column("Time")

        for a in alert_list:
            dc = _risk_color(a.score)
            table.add_row(
                str(a.id),
                a.company_name or "",
                a.alert_type or "",
                f"[{dc}]{a.score}[/{dc}]",
                a.severity or "",
                a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
            )
        console.print(table)


@cli.command()
@click.option("--countries", "-c", default="Japan,China,United States,Germany,South Korea",
              help="Comma-separated country list")
def dashboard(countries):
    """Show risk dashboard for multiple countries.

    Example: scri dashboard --countries "Japan,China,Vietnam"
    """
    from scoring.engine import calculate_risk_score

    country_list = [c.strip() for c in countries.split(",")]

    table = Table(title="SCRI Risk Dashboard")
    table.add_column("Country", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Level")
    table.add_column("Top Risk")

    results = []
    with console.status("[bold green]Calculating risk scores..."):
        for country in country_list:
            try:
                score = calculate_risk_score(
                    f"dash_{country}", f"Dashboard: {country}",
                    country=country, location=country,
                )
                d = score.to_dict()
                scores = d.get("scores", {})
                top_risk = max(scores.items(), key=lambda x: x[1]) if scores else ("N/A", 0)
                results.append((country, d["overall_score"], d["risk_level"], top_risk))
            except Exception as e:
                results.append((country, 0, "ERROR", ("error", 0)))

    results.sort(key=lambda x: -x[1])
    for country, overall, level, top_risk in results:
        dc = _risk_color(overall)
        table.add_row(
            country,
            f"[{dc}]{overall}[/{dc}]",
            f"[{dc}]{level}[/{dc}]",
            f"{top_risk[0]} ({top_risk[1]})",
        )
    console.print(table)


if __name__ == "__main__":
    cli()
