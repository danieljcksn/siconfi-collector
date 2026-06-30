"""High-level collection orchestrator.

Coordinates fetching data for many entities across multiple years and periods,
with progress tracking, resume capability, and structured output.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from siconfi.api import fetch_dca, fetch_rgf, fetch_rreo
from siconfi.entities import Entity

logger = logging.getLogger(__name__)


@dataclass
class CollectionResult:
    """Summary of a collection run."""

    total_requests: int = 0
    successful: int = 0
    empty: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _output_path(
    base_dir: Path,
    report: str,
    annex: str,
    entity: Entity,
    year: int,
    period: int | None = None,
) -> Path:
    """Build a deterministic output path for a single data file.

    Structure: ``<base>/<report>/<annex>/<UF>/<entity_code>/<year>_<period>.csv``
    """
    annex_slug = annex.replace(" ", "_").replace("/", "-")
    parts = [base_dir, report, annex_slug, entity.uf, str(entity.cod_ibge)]
    filename = f"{year}.csv" if period is None else f"{year}_P{period}.csv"
    path = Path(*parts) / filename
    return path


def _save_items(items: list[dict], path: Path) -> None:
    """Save a list of API response items to CSV."""
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(items)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def collect_rreo(
    entities: list[Entity],
    years: list[int],
    periods: list[int] | None = None,
    annex: str = "RREO-Anexo 01",
    report_type: str = "RREO",
    output_dir: Path = Path("data"),
    delay: float = 0.5,
    resume: bool = True,
) -> CollectionResult:
    """Collect RREO data for a list of entities across years and periods.

    Parameters
    ----------
    entities : list[Entity]
        Target municipalities/states.
    years : list[int]
        Fiscal years to collect.
    periods : list[int] | None
        Bimonthly periods (1–6). Defaults to all six.
    annex : str
        RREO annex identifier.
    report_type : str
        ``"RREO"`` or ``"RREO Simplificado"``.
    output_dir : Path
        Root directory for output files.
    delay : float
        Seconds between API requests.
    resume : bool
        If True, skip entities/years/periods that already have output files.
    """
    if periods is None:
        periods = list(range(1, 7))

    result = CollectionResult()
    total = len(entities) * len(years) * len(periods)

    with tqdm(total=total, desc="RREO", unit="req") as pbar:
        for entity in entities:
            for year in years:
                for period in periods:
                    pbar.set_postfix_str(
                        f"{entity.uf}/{entity.cod_ibge} {year}/P{period}"
                    )
                    result.total_requests += 1
                    out = _output_path(output_dir, "rreo", annex, entity, year, period)

                    if resume and out.exists():
                        result.successful += 1
                        pbar.update(1)
                        continue

                    try:
                        items = fetch_rreo(
                            entity.cod_ibge, year, period, annex,
                            report_type=report_type, delay=delay,
                        )
                        if items:
                            _save_items(items, out)
                            result.successful += 1
                        else:
                            result.empty += 1
                    except Exception as exc:
                        result.failed += 1
                        msg = f"RREO {entity.cod_ibge} {year}/P{period}: {exc}"
                        result.errors.append(msg)
                        logger.warning(msg)

                    pbar.update(1)
                    time.sleep(delay)

    return result


def collect_rgf(
    entities: list[Entity],
    years: list[int],
    periods: list[int] | None = None,
    periodicity: str = "Q",
    power: str = "E",
    annex: str = "RGF-Anexo 01",
    report_type: str = "RGF",
    output_dir: Path = Path("data"),
    delay: float = 0.5,
    resume: bool = True,
) -> CollectionResult:
    """Collect RGF data for a list of entities across years and periods."""
    if periods is None:
        periods = list(range(1, 4)) if periodicity == "Q" else list(range(1, 3))

    result = CollectionResult()
    total = len(entities) * len(years) * len(periods)

    with tqdm(total=total, desc="RGF", unit="req") as pbar:
        for entity in entities:
            for year in years:
                for period in periods:
                    pbar.set_postfix_str(
                        f"{entity.uf}/{entity.cod_ibge} {year}/P{period}"
                    )
                    result.total_requests += 1
                    out = _output_path(output_dir, "rgf", annex, entity, year, period)

                    if resume and out.exists():
                        result.successful += 1
                        pbar.update(1)
                        continue

                    try:
                        items = fetch_rgf(
                            entity.cod_ibge, year, period,
                            periodicity=periodicity, power=power,
                            annex=annex, report_type=report_type, delay=delay,
                        )
                        if items:
                            _save_items(items, out)
                            result.successful += 1
                        else:
                            result.empty += 1
                    except Exception as exc:
                        result.failed += 1
                        msg = f"RGF {entity.cod_ibge} {year}/P{period}: {exc}"
                        result.errors.append(msg)
                        logger.warning(msg)

                    pbar.update(1)
                    time.sleep(delay)

    return result


def collect_dca(
    entities: list[Entity],
    years: list[int],
    annex: str = "DCA-Anexo I-AB",
    output_dir: Path = Path("data"),
    delay: float = 0.5,
    resume: bool = True,
) -> CollectionResult:
    """Collect DCA (annual accounts) data for a list of entities."""
    result = CollectionResult()
    total = len(entities) * len(years)

    with tqdm(total=total, desc="DCA", unit="req") as pbar:
        for entity in entities:
            for year in years:
                pbar.set_postfix_str(f"{entity.uf}/{entity.cod_ibge} {year}")
                result.total_requests += 1
                out = _output_path(output_dir, "dca", annex, entity, year)

                if resume and out.exists():
                    result.successful += 1
                    pbar.update(1)
                    continue

                try:
                    items = fetch_dca(
                        entity.cod_ibge, year, annex=annex, delay=delay,
                    )
                    if items:
                        _save_items(items, out)
                        result.successful += 1
                    else:
                        result.empty += 1
                except Exception as exc:
                    result.failed += 1
                    msg = f"DCA {entity.cod_ibge} {year}: {exc}"
                    result.errors.append(msg)
                    logger.warning(msg)

                pbar.update(1)
                time.sleep(delay)

    return result
