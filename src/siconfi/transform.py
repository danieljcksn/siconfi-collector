"""Transform raw SICONFI CSV files into clean, analysis-ready datasets.

The raw RREO data is a long-format table with one row per (account × column_type)
combination, making it hard to read and analyze. This module pivots the data into
wide-format tables suitable for time series analysis and forecasting.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ── Bimonthly period mappings ────────────────────────────────────────────────

PERIOD_LABELS = {
    1: "Jan-Feb",
    2: "Mar-Apr",
    3: "May-Jun",
    4: "Jul-Aug",
    5: "Sep-Oct",
    6: "Nov-Dec",
}

PERIOD_START_MONTH = {1: 1, 2: 3, 3: 5, 4: 7, 5: 9, 6: 11}
PERIOD_END_MONTH = {1: 2, 2: 4, 3: 6, 4: 8, 5: 10, 6: 12}

# Revenue accounts to extract (in hierarchical order).
# These are the cod_conta values from the RREO-Anexo 01.
REVENUE_ACCOUNTS = [
    "ReceitasExcetoIntraOrcamentarias",
    "ReceitasCorrentes",
    "ReceitaTributaria",
    "Impostos",
    "IPTU",
    "ISS",
    "ITBI",
    "IRRF",
    "Taxas",
    "ReceitaDeContribuicoes",
    "ContribuicaoDeIluminacaoPublica",
    "ReceitaPatrimonial",
    "ReceitasDeValoresMobiliarios",
    "TransferenciasCorrentes",
    "TransferenciasCorrentesDaUniaoEDeSuasEntidades",
    "TransferenciasCorrentesDosEstadosEDoDistritoFederalEDeSuasEntidades",
    "TransferenciasCorrentesDeOutrasInstituicoesPublicas",
    "OutrasReceitasCorrentes",
    "ReceitasDeCapital",
    "TransferenciasDeCapital",
    "TotalReceitas",
]


def _load_raw_csvs(directory: Path) -> pd.DataFrame:
    """Load and concatenate all CSV files under a directory tree."""
    csv_files = sorted(directory.rglob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found under {directory}")

    frames = []
    for path in csv_files:
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
            frames.append(df)
        except Exception as exc:
            logger.warning("Skipping %s: %s", path, exc)

    if not frames:
        raise FileNotFoundError(f"No readable CSV files found under {directory}")

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d rows from %d files.", len(combined), len(frames))
    return combined


def extract_revenue_realized(
    raw: pd.DataFrame,
    column: str = "Até o Bimestre (c)",
) -> pd.DataFrame:
    """Extract cumulative realized revenue from raw RREO data.

    Filters to the specified column type (default: cumulative YTD),
    keeps only revenue accounts, and pivots to wide format.

    Returns a DataFrame with columns:
        cod_ibge, year, period, period_label, <account_1>, <account_2>, ...
    """
    # Filter to the target column type (cumulative realized revenue).
    mask = raw["coluna"] == column
    df = raw[mask].copy()

    if df.empty:
        logger.warning("No rows found for column '%s'.", column)
        return pd.DataFrame()

    # Exclude consortium / inter-municipal entities — keep only the main
    # municipal government (Prefeitura / Governo).  Consortia (CONSÓRCIO,
    # Câmara, Instituto, etc.) produce duplicate rows for the same cod_ibge.
    if "instituicao" in df.columns:
        main_mask = df["instituicao"].str.contains(
            r"Prefeitura|Governo|Poder Executivo", case=False, na=False
        )
        if main_mask.any():
            n_before = len(df)
            df = df[main_mask]
            n_dropped = n_before - len(df)
            if n_dropped > 0:
                logger.info(
                    "Filtered out %d rows from non-municipal institutions "
                    "(consortia, legislature, etc.).", n_dropped
                )

    # Keep only revenue accounts that exist in the data.
    available = set(df["cod_conta"].unique())
    accounts = [a for a in REVENUE_ACCOUNTS if a in available]

    # Also include any revenue accounts not in our predefined list.
    extra = sorted(available - set(REVENUE_ACCOUNTS))
    # Filter extras to likely revenue accounts (exclude expenditure).
    expenditure_prefixes = ("Despesas", "Pessoal", "Juros", "Outras Despesas",
                            "Investimentos", "Amortizacao", "Reserva",
                            "Subtotal Das Despesas", "Superavit", "Total Despesas",
                            "TotalDespesas", "SubtotalDasDespesas",
                            "DespesasCorrentes", "DespesasDeCapital",
                            "PessoalEEncargosSociais", "JurosEEncargosDaDivida",
                            "OutrasDespesasCorrentes", "Investimentos",
                            "AmortizacaoDaDivida", "ReservaDeContingencia",
                            "TotalDespesasComSuperavit", "Superavit")
    extra = [a for a in extra if a not in expenditure_prefixes]
    accounts.extend(extra)

    df = df[df["cod_conta"].isin(accounts)]

    # Pivot: one row per (entity, year, period), one column per account.
    pivot = df.pivot_table(
        index=["cod_ibge", "instituicao", "uf", "exercicio", "periodo"],
        columns="cod_conta",
        values="valor",
        aggfunc="first",
    ).reset_index()

    # Rename columns for clarity.
    pivot = pivot.rename(columns={
        "exercicio": "year",
        "periodo": "period",
        "instituicao": "entity_name",
    })

    # Add human-readable period label.
    pivot["period_label"] = pivot["period"].map(PERIOD_LABELS)

    # Sort by entity, year, period.
    pivot = pivot.sort_values(["cod_ibge", "year", "period"]).reset_index(drop=True)

    # Reorder columns: identifiers first, then accounts.
    id_cols = ["cod_ibge", "entity_name", "uf", "year", "period", "period_label"]
    account_cols = [c for c in accounts if c in pivot.columns]
    pivot = pivot[id_cols + account_cols]

    return pivot


def compute_bimonthly_increments(cumulative: pd.DataFrame) -> pd.DataFrame:
    """Compute bimonthly increments from cumulative YTD revenue.

    For each entity and year, period 1 stays as-is (Jan-Feb cumulative = Jan-Feb actual).
    For periods 2–6, the increment is: value(period N) - value(period N-1).

    This gives the actual revenue collected in each bimonthly period.
    """
    id_cols = ["cod_ibge", "entity_name", "uf", "year", "period", "period_label"]
    value_cols = [c for c in cumulative.columns if c not in id_cols]

    result = cumulative.copy()

    # Process each entity and year independently.
    for (ibge, year), group in cumulative.groupby(["cod_ibge", "year"]):
        group = group.sort_values("period")

        for col in value_cols:
            values = group[col].values
            increments = values.copy()
            for i in range(1, len(increments)):
                if pd.notna(values[i]) and pd.notna(values[i - 1]):
                    increments[i] = values[i] - values[i - 1]

            result.loc[group.index, col] = increments

    return result


def build_time_series(
    data_dir: Path,
    annex: str = "RREO-Anexo_01",
    incremental: bool = True,
) -> pd.DataFrame:
    """Build a clean time series from raw RREO files.

    Parameters
    ----------
    data_dir : Path
        Root data directory (containing ``rreo/<annex>/...``).
    annex : str
        Annex subdirectory name.
    incremental : bool
        If True, compute bimonthly increments from cumulative values.
        If False, return cumulative YTD values.

    Returns
    -------
    pd.DataFrame
        Clean wide-format DataFrame with one row per (entity, year, period).
    """
    rreo_dir = data_dir / "rreo" / annex
    raw = _load_raw_csvs(rreo_dir)
    cumulative = extract_revenue_realized(raw)

    if cumulative.empty:
        return cumulative

    if incremental:
        return compute_bimonthly_increments(cumulative)
    return cumulative


# ── Monthly extraction from RREO-Anexo 03 ───────────────────────────────────

# The <MR-k> columns in Anexo 03 encode a rolling 12-month window relative to
# the last month of each bimonthly period.  For period P of year Y:
#   MR  = month 2*P            (the last month of the bimester)
#   MR-k = month (2*P - k)    (if ≤ 0, wraps to previous year)
#
# Strategy: use only the highest available period per (entity, year) to avoid
# double-counting.  Period 6 gives Jan–Dec cleanly; earlier periods give a
# partial year (only months belonging to that year are kept).

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

# Revenue accounts in Anexo 03 (Net Current Revenue breakdown).
ANEXO3_ACCOUNTS = [
    "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB",
    "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB",
    "IPTULiquidoExcetoTransferenciasEFUNDEB",
    "ISSLiquidoExcetoTransferenciasEFUNDEB",
    "ITBILiquidoExcetoTransferenciasEFUNDEB",
    "IRRFLiquidoExcetoTransferenciasEFUNDEB",
    "OutrasReceitasTributarias",
    "RREO3ReceitaDeContribuicoes",
    "RREO3ReceitaPatrimonial",
    "RendimentosDeAplicacaoFinanceira",
    "OutrasReceitasPatrimoniais",
    "RREO3ReceitaDeServicos",
    "RREO3TransferenciasCorrentes",
    "RREO3CotaParteDoFPM",
    "RREO3CotaParteDoICMS",
    "RREO3CotaParteDoIPVA",
    "RREO3CotaParteDoITR",
    "RREO3TransferenciasDaLC611989",
    "RREO3TransferenciasDoFUNDEB",
    "RREO3OutrasTransferenciasCorrentes",
    "RREO3OutrasReceitasCorrentes",
    "DeducoesDaReceitaCorrenteLiquida",
    "RREO3ReceitaCorrenteLiquida",
]

# Short display names for Anexo 03 accounts.
ANEXO3_DISPLAY_NAMES = {
    "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB": "current_revenue",
    "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB": "tax_revenue",
    "IPTULiquidoExcetoTransferenciasEFUNDEB": "iptu",
    "ISSLiquidoExcetoTransferenciasEFUNDEB": "iss",
    "ITBILiquidoExcetoTransferenciasEFUNDEB": "itbi",
    "IRRFLiquidoExcetoTransferenciasEFUNDEB": "irrf",
    "OutrasReceitasTributarias": "other_taxes",
    "RREO3ReceitaDeContribuicoes": "contributions",
    "RREO3ReceitaPatrimonial": "property_revenue",
    "RendimentosDeAplicacaoFinanceira": "financial_returns",
    "OutrasReceitasPatrimoniais": "other_property_revenue",
    "RREO3ReceitaDeServicos": "service_revenue",
    "RREO3TransferenciasCorrentes": "current_transfers",
    "RREO3CotaParteDoFPM": "fpm",
    "RREO3CotaParteDoICMS": "icms",
    "RREO3CotaParteDoIPVA": "ipva",
    "RREO3CotaParteDoITR": "itr",
    "RREO3TransferenciasDaLC611989": "lc61_transfers",
    "RREO3TransferenciasDoFUNDEB": "fundeb",
    "RREO3OutrasTransferenciasCorrentes": "other_transfers",
    "RREO3OutrasReceitasCorrentes": "other_current_revenue",
    "DeducoesDaReceitaCorrenteLiquida": "deductions",
    "RREO3ReceitaCorrenteLiquida": "net_current_revenue",
}


def _mr_to_month_year(mr_offset: int, period: int, year: int) -> tuple[int, int]:
    """Convert a <MR-k> offset to (month, year) given the RREO period and fiscal year.

    Parameters
    ----------
    mr_offset : int
        The k in <MR-k>.  0 for <MR>.
    period : int
        Bimonthly period (1–6).
    year : int
        Fiscal year of the RREO report.

    Returns
    -------
    tuple[int, int]
        (month, actual_year) where month is 1–12.
    """
    end_month = 2 * period  # MR = last month of the bimester
    m = end_month - mr_offset
    if m <= 0:
        return (m + 12, year - 1)
    return (m, year)


def extract_monthly_revenue(raw: pd.DataFrame) -> pd.DataFrame:
    """Extract monthly revenue from RREO-Anexo 03 raw data.

    The <MR-k> columns encode monthly values in a rolling 12-month window.
    This function resolves them to actual (year, month) pairs and produces a
    clean wide-format DataFrame with one row per (entity, year, month).

    Uses the highest available period per (entity, year) to get the most
    complete data, then keeps only months belonging to the fiscal year.
    """
    # Only keep <MR-k> and <MR> columns (monthly data).
    mr_columns = [c for c in raw["coluna"].unique() if c.startswith("<MR")]
    df = raw[raw["coluna"].isin(mr_columns)].copy()

    if df.empty:
        logger.warning("No <MR> columns found. Is this RREO-Anexo 03 data?")
        return pd.DataFrame()

    # Filter to main municipal institution.
    if "instituicao" in df.columns:
        main_mask = df["instituicao"].str.contains(
            r"Prefeitura|Governo|Poder Executivo", case=False, na=False
        )
        if main_mask.any():
            df = df[main_mask]

    # Parse the MR offset from column names.
    def _parse_mr(col: str) -> int:
        """'<MR-5>' -> 5, '<MR>' -> 0."""
        col = col.strip("<>")
        if "-" in col:
            return int(col.split("-", 1)[1])
        return 0

    df["mr_offset"] = df["coluna"].apply(_parse_mr)

    # For each (entity, year), keep only the highest period (most complete data).
    idx_max_period = df.groupby(["cod_ibge", "exercicio"])["periodo"].transform("max")
    df = df[df["periodo"] == idx_max_period]

    # Resolve (mr_offset, period, year) → (actual_month, actual_year).
    resolved = df.apply(
        lambda row: _mr_to_month_year(row["mr_offset"], row["periodo"], row["exercicio"]),
        axis=1,
        result_type="expand",
    )
    df["month"] = resolved[0]
    df["actual_year"] = resolved[1]

    # Keep only months belonging to the fiscal year (drop trailing months from Y-1).
    df = df[df["actual_year"] == df["exercicio"]]

    # Determine which accounts to include.
    available = set(df["cod_conta"].unique())
    accounts = [a for a in ANEXO3_ACCOUNTS if a in available]
    extra = sorted(available - set(ANEXO3_ACCOUNTS))
    accounts.extend(extra)

    df = df[df["cod_conta"].isin(accounts)]

    # Pivot to wide format: one row per (entity, year, month).
    pivot = df.pivot_table(
        index=["cod_ibge", "instituicao", "uf", "exercicio", "month"],
        columns="cod_conta",
        values="valor",
        aggfunc="first",
    ).reset_index()

    pivot = pivot.rename(columns={
        "exercicio": "year",
        "instituicao": "entity_name",
    })

    # Rename account columns to short display names.
    rename_map = {k: v for k, v in ANEXO3_DISPLAY_NAMES.items() if k in pivot.columns}
    pivot = pivot.rename(columns=rename_map)

    # Also rename any extra accounts not in our predefined list (keep as-is).

    # Add month name and date column for easy time series use.
    pivot["month_name"] = pivot["month"].map(MONTH_NAMES)
    pivot["date"] = pd.to_datetime(
        pivot["year"].astype(str) + "-" + pivot["month"].astype(str) + "-01"
    )

    # Sort chronologically.
    pivot = pivot.sort_values(["cod_ibge", "year", "month"]).reset_index(drop=True)

    # Reorder columns.
    id_cols = ["cod_ibge", "entity_name", "uf", "year", "month", "month_name", "date"]
    account_cols = [c for c in pivot.columns if c not in id_cols]
    pivot = pivot[id_cols + account_cols]

    return pivot


def build_monthly_time_series(data_dir: Path, annex: str = "RREO-Anexo_03") -> pd.DataFrame:
    """Build a clean monthly revenue time series from RREO-Anexo 03 files.

    Parameters
    ----------
    data_dir : Path
        Root data directory (containing ``rreo/<annex>/...``).
    annex : str
        Annex subdirectory name (default: ``"RREO-Anexo_03"``).

    Returns
    -------
    pd.DataFrame
        Wide-format DataFrame with one row per (entity, year, month), with
        columns for each revenue category (IPTU, ISS, ITBI, FPM, ICMS, etc.).
    """
    rreo_dir = data_dir / "rreo" / annex
    raw = _load_raw_csvs(rreo_dir)
    return extract_monthly_revenue(raw)
