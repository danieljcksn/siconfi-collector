"""Command-line interface for the SICONFI data collector.

Usage examples::

    # List all municipalities in São Paulo
    siconfi entities --state SP

    # Search for a municipality by name
    siconfi entities --search "Campinas"

    # Collect RREO revenue data for a single city (2015–2024)
    siconfi collect rreo --entity 3509502 --years 2015-2024

    # Collect RREO data for all municipalities in a state
    siconfi collect rreo --state SP --years 2020-2024

    # Collect RREO data for multiple states
    siconfi collect rreo --state SP --state RJ --state MG --years 2020-2024

    # Collect RREO data for the entire country
    siconfi collect rreo --all --years 2020-2024

    # Collect DCA data for cities above 100k population
    siconfi collect dca --state RS --min-pop 100000 --years 2015-2024
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from siconfi.entities import EntityRegistry, Entity, STATE_NAMES, REGIONS

# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_year_range(value: str) -> list[int]:
    """Parse a year or year range like ``"2020"`` or ``"2015-2024"``."""
    if "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(value)]


def _parse_periods(value: str | None, default: list[int]) -> list[int]:
    """Parse a comma-separated list of periods like ``"1,2,3"``."""
    if value is None:
        return default
    return [int(p.strip()) for p in value.split(",")]


def _get_registry(cache_dir: Path) -> EntityRegistry:
    """Load entity registry from cache or fetch from API."""
    cache_file = cache_dir / "entities.json"
    if cache_file.exists():
        click.echo(f"Loading entity registry from cache ({cache_file})…")
        return EntityRegistry.from_cache(cache_file)

    click.echo("Fetching entity registry from SICONFI API (first run)…")
    registry = EntityRegistry.from_api()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    registry.save_cache(cache_file)
    click.echo(f"Cached {len(registry.entities)} entities to {cache_file}")
    return registry


def _resolve_entities(
    registry: EntityRegistry,
    entity_codes: tuple[int, ...],
    states: tuple[str, ...],
    region: str | None,
    all_flag: bool,
    min_pop: int,
    max_pop: int | None,
) -> list[Entity]:
    """Resolve CLI flags into a concrete list of entities to collect."""
    if entity_codes:
        entities = registry.by_codes(list(entity_codes))
        if not entities:
            click.echo("Error: no entities found for the given IBGE codes.", err=True)
            sys.exit(1)
        return entities

    if all_flag:
        entities = registry.municipalities()
    elif region:
        entities = registry.by_region(region)
    elif states:
        entities = registry.by_states(list(states))
    else:
        click.echo(
            "Error: specify --entity, --state, --region, or --all to select targets.",
            err=True,
        )
        sys.exit(1)

    # Apply population filters.
    if min_pop > 0:
        entities = [e for e in entities if e.population >= min_pop]
    if max_pop is not None:
        entities = [e for e in entities if e.population <= max_pop]

    if not entities:
        click.echo("Error: no entities match the given filters.", err=True)
        sys.exit(1)

    return entities


def _print_result(result) -> None:
    """Print a human-readable summary of a collection run."""
    click.echo()
    click.echo("─── Collection Summary ───")
    click.echo(f"  Total requests : {result.total_requests}")
    click.echo(f"  Successful     : {result.successful}")
    click.echo(f"  Empty responses: {result.empty}")
    click.echo(f"  Failed         : {result.failed}")
    if result.errors:
        click.echo(f"  First 5 errors:")
        for err in result.errors[:5]:
            click.echo(f"    • {err}")
    click.echo("──────────────────────────")


# ── CLI Definition ───────────────────────────────────────────────────────────


@click.group()
@click.option(
    "--data-dir", type=click.Path(), default="data", show_default=True,
    help="Root directory for output data and caches.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, data_dir: str, verbose: bool) -> None:
    """SICONFI Collector — Download Brazilian public finance data."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = Path(data_dir)


# ── `entities` command ───────────────────────────────────────────────────────


@cli.command()
@click.option("--state", "-s", "states", multiple=True, help="Filter by state (e.g. SP, RJ).")
@click.option("--region", "-r", help="Filter by region (NO/NE/SE/SU/CO).")
@click.option("--search", "-q", help="Search by name (substring match).")
@click.option("--sphere", type=click.Choice(["M", "E", "U", "D"]), help="Filter by sphere.")
@click.option("--min-pop", type=int, default=0, help="Minimum population.")
@click.option("--max-pop", type=int, default=None, help="Maximum population.")
@click.option("--refresh", is_flag=True, help="Force refresh from API (ignore cache).")
@click.pass_context
def entities(
    ctx: click.Context,
    states: tuple[str, ...],
    region: str | None,
    search: str | None,
    sphere: str | None,
    min_pop: int,
    max_pop: int | None,
    refresh: bool,
) -> None:
    """List and search SICONFI entities (municipalities, states)."""
    data_dir = ctx.obj["data_dir"]
    cache_file = data_dir / "entities.json"

    if refresh and cache_file.exists():
        cache_file.unlink()

    registry = _get_registry(data_dir)
    results = registry.entities

    if search:
        results = [e for e in results if search.lower() in e.name.lower()]
    if states:
        uf_set = {s.upper() for s in states}
        results = [e for e in results if e.uf in uf_set]
    if region:
        results = [e for e in results if e.region == region.upper()]
    if sphere:
        results = [e for e in results if e.sphere == sphere]
    if min_pop > 0:
        results = [e for e in results if e.population >= min_pop]
    if max_pop is not None:
        results = [e for e in results if e.population <= max_pop]

    if not results:
        click.echo("No entities found matching the given filters.")
        return

    # Sort by state, then name.
    results.sort(key=lambda e: (e.uf, e.name))

    click.echo(f"\n{'Code':<10} {'Name':<40} {'UF':<4} {'Sphere':<8} {'Population':>12}")
    click.echo("─" * 78)
    for e in results:
        click.echo(
            f"{e.cod_ibge:<10} {e.name:<40} {e.uf:<4} {e.sphere:<8} {e.population:>12,}"
        )
    click.echo(f"\nTotal: {len(results)} entities")


# ── `collect` command group ──────────────────────────────────────────────────

# Shared options for all collect subcommands.
_entity_options = [
    click.option("--entity", "-e", "entity_codes", multiple=True, type=int,
                 help="IBGE code(s) of specific entities."),
    click.option("--state", "-s", "states", multiple=True,
                 help="Collect all municipalities in state(s) (e.g. SP, RJ)."),
    click.option("--region", "-r", help="Collect all municipalities in a region (NO/NE/SE/SU/CO)."),
    click.option("--all", "all_flag", is_flag=True,
                 help="Collect data for ALL municipalities in Brazil."),
    click.option("--min-pop", type=int, default=0, show_default=True,
                 help="Minimum population filter."),
    click.option("--max-pop", type=int, default=None, help="Maximum population filter."),
    click.option("--years", "-y", required=True,
                 help="Year or range (e.g. 2020 or 2015-2024)."),
    click.option("--delay", "-d", type=float, default=0.5, show_default=True,
                 help="Seconds between API requests."),
    click.option("--no-resume", is_flag=True,
                 help="Disable resume (re-download existing files)."),
]


def _add_options(options):
    """Decorator to apply a list of click options to a command."""
    def decorator(func):
        for option in reversed(options):
            func = option(func)
        return func
    return decorator


@cli.group()
def collect() -> None:
    """Collect fiscal reports from SICONFI."""
    pass


@collect.command()
@_add_options(_entity_options)
@click.option("--annex", default="RREO-Anexo 01", show_default=True,
              help="RREO annex to collect.")
@click.option("--periods", default=None,
              help="Bimonthly periods (e.g. '1,2,3'). Default: all (1–6).")
@click.option("--report-type", type=click.Choice(["RREO", "RREO Simplificado"]),
              default="RREO", show_default=True)
@click.pass_context
def rreo(
    ctx: click.Context,
    entity_codes: tuple[int, ...],
    states: tuple[str, ...],
    region: str | None,
    all_flag: bool,
    min_pop: int,
    max_pop: int | None,
    years: str,
    delay: float,
    no_resume: bool,
    annex: str,
    periods: str | None,
    report_type: str,
) -> None:
    """Collect RREO (budget execution) data.

    The RREO is published bimonthly (6 periods per year) and contains revenue
    and expenditure data. Annex 01 covers budget revenue (receitas orçamentárias).
    """
    from siconfi.collector import collect_rreo

    data_dir = ctx.obj["data_dir"]
    registry = _get_registry(data_dir)
    targets = _resolve_entities(
        registry, entity_codes, states, region, all_flag, min_pop, max_pop,
    )
    year_list = _parse_year_range(years)
    period_list = _parse_periods(periods, list(range(1, 7)))

    click.echo(f"\nCollecting RREO [{annex}]")
    click.echo(f"  Entities : {len(targets)}")
    click.echo(f"  Years    : {year_list[0]}–{year_list[-1]}")
    click.echo(f"  Periods  : {period_list}")
    click.echo(f"  Output   : {data_dir}/rreo/")
    click.echo()

    result = collect_rreo(
        entities=targets,
        years=year_list,
        periods=period_list,
        annex=annex,
        report_type=report_type,
        output_dir=data_dir,
        delay=delay,
        resume=not no_resume,
    )
    _print_result(result)


@collect.command()
@_add_options(_entity_options)
@click.option("--annex", default="RGF-Anexo 01", show_default=True,
              help="RGF annex to collect.")
@click.option("--periods", default=None,
              help="Periods (e.g. '1,2,3'). Default depends on periodicity.")
@click.option("--periodicity", type=click.Choice(["Q", "S"]),
              default="Q", show_default=True,
              help="Q = quadrimestral (3 periods), S = semestral (2 periods).")
@click.option("--power", type=click.Choice(["E", "L", "J", "M", "D"]),
              default="E", show_default=True,
              help="Branch of government.")
@click.option("--report-type", type=click.Choice(["RGF", "RGF Simplificado"]),
              default="RGF", show_default=True)
@click.pass_context
def rgf(
    ctx: click.Context,
    entity_codes: tuple[int, ...],
    states: tuple[str, ...],
    region: str | None,
    all_flag: bool,
    min_pop: int,
    max_pop: int | None,
    years: str,
    delay: float,
    no_resume: bool,
    annex: str,
    periods: str | None,
    periodicity: str,
    power: str,
    report_type: str,
) -> None:
    """Collect RGF (fiscal management) data.

    The RGF tracks fiscal responsibility indicators such as personnel spending,
    debt limits, and credit operations.
    """
    from siconfi.collector import collect_rgf

    data_dir = ctx.obj["data_dir"]
    registry = _get_registry(data_dir)
    targets = _resolve_entities(
        registry, entity_codes, states, region, all_flag, min_pop, max_pop,
    )
    year_list = _parse_year_range(years)
    default_periods = list(range(1, 4)) if periodicity == "Q" else list(range(1, 3))
    period_list = _parse_periods(periods, default_periods)

    click.echo(f"\nCollecting RGF [{annex}] (periodicity={periodicity}, power={power})")
    click.echo(f"  Entities : {len(targets)}")
    click.echo(f"  Years    : {year_list[0]}–{year_list[-1]}")
    click.echo(f"  Periods  : {period_list}")
    click.echo(f"  Output   : {data_dir}/rgf/")
    click.echo()

    result = collect_rgf(
        entities=targets,
        years=year_list,
        periods=period_list,
        periodicity=periodicity,
        power=power,
        annex=annex,
        report_type=report_type,
        output_dir=data_dir,
        delay=delay,
        resume=not no_resume,
    )
    _print_result(result)


@collect.command()
@_add_options(_entity_options)
@click.option("--annex", default="DCA-Anexo I-AB", show_default=True,
              help="DCA annex to collect.")
@click.pass_context
def dca(
    ctx: click.Context,
    entity_codes: tuple[int, ...],
    states: tuple[str, ...],
    region: str | None,
    all_flag: bool,
    min_pop: int,
    max_pop: int | None,
    years: str,
    delay: float,
    no_resume: bool,
    annex: str,
) -> None:
    """Collect DCA (annual accounts) data.

    The DCA contains balance sheets, budget balances, cash flow statements,
    and other annual financial declarations.
    """
    from siconfi.collector import collect_dca

    data_dir = ctx.obj["data_dir"]
    registry = _get_registry(data_dir)
    targets = _resolve_entities(
        registry, entity_codes, states, region, all_flag, min_pop, max_pop,
    )
    year_list = _parse_year_range(years)

    click.echo(f"\nCollecting DCA [{annex}]")
    click.echo(f"  Entities : {len(targets)}")
    click.echo(f"  Years    : {year_list[0]}–{year_list[-1]}")
    click.echo(f"  Output   : {data_dir}/dca/")
    click.echo()

    result = collect_dca(
        entities=targets,
        years=year_list,
        annex=annex,
        output_dir=data_dir,
        delay=delay,
        resume=not no_resume,
    )
    _print_result(result)


# ── `transform` command ──────────────────────────────────────────────────────


@cli.command()
@click.option("--annex", default="RREO-Anexo_01", show_default=True,
              help="Annex subdirectory name (use underscores, e.g. RREO-Anexo_01).")
@click.option("--cumulative", is_flag=True,
              help="Output cumulative YTD values instead of bimonthly increments.")
@click.option("--output", "-o", default=None,
              help="Output CSV path. Default: <data-dir>/transformed/<annex>_revenue.csv")
@click.pass_context
def transform(ctx: click.Context, annex: str, cumulative: bool, output: str | None) -> None:
    """Transform raw RREO data into a clean revenue time series.

    Reads all raw CSV files for the given annex, extracts realized revenue
    by tax category, and produces a single wide-format CSV with one row per
    (entity, year, bimonthly period).

    By default, outputs bimonthly increments (actual revenue per period).
    Use --cumulative for year-to-date totals.
    """
    from siconfi.transform import build_time_series

    data_dir = ctx.obj["data_dir"]
    incremental = not cumulative

    click.echo(f"\nTransforming RREO [{annex}]")
    click.echo(f"  Mode: {'bimonthly increments' if incremental else 'cumulative YTD'}")

    result = build_time_series(data_dir, annex=annex, incremental=incremental)

    if result.empty:
        click.echo("  No data found. Did you run `siconfi collect rreo` first?")
        return

    if output is None:
        suffix = "incremental" if incremental else "cumulative"
        out_path = data_dir / "transformed" / f"{annex}_revenue_{suffix}.csv"
    else:
        out_path = Path(output)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")

    n_entities = result["cod_ibge"].nunique()
    n_rows = len(result)
    accounts = [c for c in result.columns if c not in
                ["cod_ibge", "entity_name", "uf", "year", "period", "period_label"]]

    click.echo(f"  Entities : {n_entities}")
    click.echo(f"  Rows     : {n_rows}")
    click.echo(f"  Accounts : {len(accounts)}")
    click.echo(f"  Saved to : {out_path}")
    click.echo(f"\n  Revenue categories found:")
    for acc in accounts:
        click.echo(f"    - {acc}")


@cli.command("transform-monthly")
@click.option("--annex", default="RREO-Anexo_03", show_default=True,
              help="Annex subdirectory name.")
@click.option("--output", "-o", default=None,
              help="Output CSV path. Default: <data-dir>/transformed/monthly_revenue.csv")
@click.pass_context
def transform_monthly(ctx: click.Context, annex: str, output: str | None) -> None:
    """Transform RREO-Anexo 03 data into a monthly revenue time series.

    Anexo 03 (Net Current Revenue) contains <MR> columns that encode individual
    monthly values.  This command resolves them into actual calendar months and
    produces a clean CSV with one row per (entity, year, month) — ideal for
    time series forecasting.

    Revenue categories include IPTU, ISS, ITBI, IRRF, FPM, ICMS, IPVA, FUNDEB,
    and more.

    Requires data collected with: siconfi collect rreo --annex "RREO-Anexo 03"
    """
    from siconfi.transform import build_monthly_time_series

    data_dir = ctx.obj["data_dir"]

    click.echo(f"\nTransforming RREO [{annex}] → monthly revenue")

    result = build_monthly_time_series(data_dir, annex=annex)

    if result.empty:
        click.echo("  No data found.")
        click.echo('  Run: siconfi collect rreo --annex "RREO-Anexo 03" ... first.')
        return

    if output is None:
        out_path = data_dir / "transformed" / "monthly_revenue.csv"
    else:
        out_path = Path(output)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")

    n_entities = result["cod_ibge"].nunique()
    n_rows = len(result)
    id_cols = {"cod_ibge", "entity_name", "uf", "year", "month", "month_name", "date"}
    accounts = [c for c in result.columns if c not in id_cols]

    click.echo(f"  Entities : {n_entities}")
    click.echo(f"  Rows     : {n_rows} ({n_rows // max(n_entities, 1)} months/entity)")
    click.echo(f"  Accounts : {len(accounts)}")
    click.echo(f"  Saved to : {out_path}")
    click.echo(f"\n  Revenue categories:")
    for acc in accounts:
        click.echo(f"    - {acc}")


@cli.command("transform-prefeitura-forecast")
@click.option("--annex", default="RREO-Anexo_03", show_default=True,
              help="Annex subdirectory name (a previsao por tributo vem do Anexo 03).")
@click.option("--output", "-o", default=None,
              help="Output CSV path. Default: <data-dir>/transformed/prefeitura_forecast.csv")
@click.pass_context
def transform_prefeitura_forecast(ctx: click.Context, annex: str, output: str | None) -> None:
    """Extrai a projecao de receita da propria prefeitura por entidade/ano/tributo.

    Usa a coluna 'PREVISAO ATUALIZADA <ano>' do RREO-Anexo 03 (que, ao contrario
    do Anexo 01, discrimina IPTU/ISS/ITBI individualmente). Quando ha mais de um
    bimestre coletado para o mesmo ano, prefere o de menor numero (o P1 e o mais
    proximo da Previsao Inicial da LOA). Cruza com o realizado anual (soma dos 12
    meses do calendario) e calcula o erro percentual da prefeitura --- o benchmark
    usado no confronto com Oliveira (2024) (Subsecao 4.3.2 do TCC).

    Requires data collected with: siconfi collect rreo --annex "RREO-Anexo 03"
    (idealmente tambem com --periods 1 para aproximar a Previsao Inicial).
    """
    from siconfi.prefeitura_forecast import (
        extract_prefeitura_forecast,
        extract_realizado_anual,
        cross_with_realizado,
    )

    data_dir = ctx.obj["data_dir"]

    click.echo(f"\nExtracting PREVISAO ATUALIZADA from [{annex}]")

    prefeitura = extract_prefeitura_forecast(data_dir, annex=annex)
    realizado = extract_realizado_anual(data_dir, annex=annex)
    df = cross_with_realizado(prefeitura, realizado)

    if output is None:
        out_path = data_dir / "transformed" / "prefeitura_forecast.csv"
    else:
        out_path = Path(output)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    n_entities = df["cod_ibge"].nunique() if not df.empty else 0
    periodos = sorted(df["periodo_fonte"].unique()) if not df.empty else []
    click.echo(f"  Rows       : {len(df)}")
    click.echo(f"  Entities   : {n_entities}")
    click.echo(f"  Periodos   : {periodos}  (1 = mais proximo da Previsao Inicial)")
    click.echo(f"  Saved to   : {out_path}")


# ── `info` command ───────────────────────────────────────────────────────────


@cli.command()
def info() -> None:
    """Show available report types and annexes."""
    click.echo("\n╔══════════════════════════════════════════════════════════════╗")
    click.echo("║                  SICONFI Report Types                       ║")
    click.echo("╠══════════════════════════════════════════════════════════════╣")
    click.echo("║                                                             ║")
    click.echo("║  RREO — Relatório Resumido da Execução Orçamentária         ║")
    click.echo("║    Periodicity: Bimonthly (6 periods/year)                  ║")
    click.echo("║    Key annexes:                                             ║")
    click.echo("║      • RREO-Anexo 01  Budget Revenue (Receitas)             ║")
    click.echo("║      • RREO-Anexo 02  Expenditure by Function               ║")
    click.echo("║      • RREO-Anexo 03  Net Revenue                           ║")
    click.echo("║      • RREO-Anexo 06  Fiscal Result                         ║")
    click.echo("║      • RREO-Anexo 07  Remaining to Pay                      ║")
    click.echo("║      • RREO-Anexo 14  Simplified Net Revenue                ║")
    click.echo("║                                                             ║")
    click.echo("║  RGF — Relatório de Gestão Fiscal                           ║")
    click.echo("║    Periodicity: Quadrimestral (3) or Semestral (2)          ║")
    click.echo("║    Powers: E=Executive L=Legislative J=Judiciary            ║")
    click.echo("║    Key annexes:                                             ║")
    click.echo("║      • RGF-Anexo 01  Personnel Spending                     ║")
    click.echo("║      • RGF-Anexo 02  Consolidated Debt                      ║")
    click.echo("║      • RGF-Anexo 03  Credit Operations                      ║")
    click.echo("║                                                             ║")
    click.echo("║  DCA — Declaração de Contas Anuais                          ║")
    click.echo("║    Periodicity: Annual                                      ║")
    click.echo("║    Key annexes:                                             ║")
    click.echo("║      • DCA-Anexo I-AB  Balance Sheet                        ║")
    click.echo("║      • DCA-Anexo I-C   Equity Changes                       ║")
    click.echo("║      • DCA-Anexo I-D   Budget Balance                       ║")
    click.echo("║      • DCA-Anexo I-E   Cash Flow Statement                  ║")
    click.echo("║                                                             ║")
    click.echo("╚══════════════════════════════════════════════════════════════╝")
    click.echo()
    click.echo("States:")
    for code, name in sorted(STATE_NAMES.items()):
        click.echo(f"  {code}  {name}")
    click.echo()
    click.echo("Regions:")
    for code, name in REGIONS.items():
        click.echo(f"  {code}  {name}")
