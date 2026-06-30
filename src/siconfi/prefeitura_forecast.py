"""Extract municipality forecast benchmarks from RREO Annex 03.

The annual budget forecast used by municipalities is not available by tax in
RREO Annex 01: that annex exposes the aggregate tax-revenue line, but not IPTU,
ISS, and ITBI separately. RREO Annex 03, however, includes an updated forecast
column by revenue category. This module extracts that benchmark and joins it to
the annual realized value reconstructed from the same monthly Annex 03 source.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from siconfi.transform import _load_raw_csvs, extract_monthly_revenue

logger = logging.getLogger(__name__)

ANEXO3_TAX_NAMES = {
    "IPTULiquidoExcetoTransferenciasEFUNDEB": "IPTU",
    "ISSLiquidoExcetoTransferenciasEFUNDEB": "ISSQN",
    "ITBILiquidoExcetoTransferenciasEFUNDEB": "ITBI",
}

_FORECAST_RE = re.compile(r"^\s*PREVISAO\s+ATUALIZADA\b", re.IGNORECASE)
_MAIN_INSTITUTION_RE = re.compile(r"Prefeitura|Governo|Poder Executivo", re.IGNORECASE)


def _strip_accents(value: object) -> str:
    """Return an uppercase ASCII approximation suitable for label matching."""
    text = "" if value is None else str(value)
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.upper()


def _is_updated_forecast_label(value: object) -> bool:
    """Match variants such as 'PREVISAO ATUALIZADA' and 'PREVISAO ATUALIZADA 2024'."""
    return bool(_FORECAST_RE.match(_strip_accents(value)))


def _filter_main_institution(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer the executive branch when Annex 03 contains other institutions."""
    if "instituicao" not in df.columns:
        return df

    main = df["instituicao"].astype(str).str.contains(_MAIN_INSTITUTION_RE, na=False)
    if main.any():
        return df[main].copy()
    return df


def extract_prefeitura_forecast(
    data_dir: Path | str,
    annex: str = "RREO-Anexo_03",
) -> pd.DataFrame:
    """Extract the updated municipal forecast by entity, year, and tax.

    When more than one bimonthly period is present for the same year and tax,
    the earliest period is retained because it is the closest available value to
    the initial budget forecast.
    """
    data_dir = Path(data_dir)
    raw = _load_raw_csvs(data_dir / "rreo" / annex)

    mask_col = raw["coluna"].map(_is_updated_forecast_label)
    mask_acc = raw["cod_conta"].isin(ANEXO3_TAX_NAMES)
    df = raw[mask_col & mask_acc].copy()
    if df.empty:
        logger.warning("No updated forecast rows found for IPTU, ISS, or ITBI.")
        return pd.DataFrame(
            columns=[
                "cod_ibge",
                "entity_name",
                "year",
                "tributo",
                "previsao_prefeitura",
                "periodo_fonte",
            ]
        )

    df = _filter_main_institution(df)
    df["year"] = df["exercicio"].astype(int)
    df["periodo"] = df["periodo"].astype(int)
    df["tributo"] = df["cod_conta"].map(ANEXO3_TAX_NAMES)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df = df.dropna(subset=["valor"])

    df = df.sort_values("periodo")
    df = df.drop_duplicates(subset=["cod_ibge", "year", "tributo"], keep="first")

    out = df.rename(
        columns={
            "instituicao": "entity_name",
            "valor": "previsao_prefeitura",
            "periodo": "periodo_fonte",
        }
    )
    cols = ["cod_ibge", "entity_name", "year", "tributo", "previsao_prefeitura", "periodo_fonte"]
    return out[cols].sort_values(["cod_ibge", "tributo", "year"]).reset_index(drop=True)


def extract_realizado_anual(
    data_dir: Path | str,
    annex: str = "RREO-Anexo_03",
) -> pd.DataFrame:
    """Aggregate the monthly Annex 03 series into annual realized values by tax."""
    data_dir = Path(data_dir)
    raw = _load_raw_csvs(data_dir / "rreo" / annex)
    monthly = extract_monthly_revenue(raw)

    tax_columns = {"IPTU": "iptu", "ISSQN": "iss", "ITBI": "itbi"}
    available = {tax: col for tax, col in tax_columns.items() if col in monthly.columns}
    if not available:
        return pd.DataFrame(columns=["cod_ibge", "year", "tributo", "realizado_anual"])

    counts = monthly.groupby(["cod_ibge", "year"])["month"].nunique()
    full_years = set(counts[counts == 12].index)

    rows: list[dict[str, object]] = []
    for (cod_ibge, year), group in monthly.groupby(["cod_ibge", "year"]):
        if (cod_ibge, year) not in full_years:
            continue
        for tax, col in available.items():
            total = pd.to_numeric(group[col], errors="coerce").sum(min_count=1)
            if pd.notna(total):
                rows.append(
                    {
                        "cod_ibge": cod_ibge,
                        "year": int(year),
                        "tributo": tax,
                        "realizado_anual": float(total),
                    }
                )
    return pd.DataFrame(rows)


def cross_with_realizado(
    prefeitura: pd.DataFrame,
    realizado_anual: pd.DataFrame,
) -> pd.DataFrame:
    """Join municipal forecasts to realized annual totals and compute errors."""
    if prefeitura.empty:
        return prefeitura

    df = prefeitura.merge(realizado_anual, on=["cod_ibge", "year", "tributo"], how="left")
    realized = pd.to_numeric(df["realizado_anual"], errors="coerce")
    forecast = pd.to_numeric(df["previsao_prefeitura"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        denominator = realized.replace(0, np.nan)
        df["erro_pct_prefeitura"] = (realized - forecast).abs() / denominator * 100.0
    df["vies_prefeitura"] = np.sign(realized - forecast)
    return df.sort_values(["cod_ibge", "tributo", "year"]).reset_index(drop=True)
