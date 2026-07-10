"""Extracao da projecao de receita da propria prefeitura (benchmark).

Cruza com o realizado anual para produzir a tabela analitica usada no
benchmark da prefeitura (Subsecao 4.3.2 do TCC) e no confronto com
Oliveira (2024).

NOTA METODOLOGICA IMPORTANTE
----------------------------
Oliveira (2024) usou a "Previsao Inicial" (valor da LOA, fixo durante o
exercicio). Verificamos que o RREO-Anexo 01 ("Balanco Orcamentario") so
expoe a linha agregada "Impostos" --- nao discrimina IPTU/ISSQN/ITBI ---
portanto a "Previsao Inicial" por tributo NAO esta disponivel ali.

O RREO-Anexo 03 ("Demonstrativo da Receita Corrente Liquida"), por outro
lado, traz uma coluna ``PREVISAO ATUALIZADA <ano>`` por categoria de
receita, incluindo IPTU, ISS e ITBI individualmente. Adotamos essa coluna
como benchmark da prefeitura, com a ressalva de que e a previsao
*atualizada* (revisada ao longo do exercicio), nao a *inicial*. Quando ha
mais de um bimestre coletado para o mesmo ano, prefere-se o de menor
numero (o P1 e o mais proximo da Previsao Inicial da LOA, pois ainda nao
sofreu revisoes de meio de ano).

O realizado anual e calculado somando os doze meses do calendario
extraidos das colunas ``<MR-n>`` do proprio Anexo 03 (mesma logica de
``transform.extract_monthly_revenue``), garantindo coerencia com a serie
mensal usada na modelagem.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from siconfi.transform import _load_raw_csvs, extract_monthly_revenue

logger = logging.getLogger(__name__)


# ---------- Mapeamento cod_conta (Anexo 03) -> nome de tributo do TCC -----
# O Anexo 03 chama o ISSQN de "ISS"; o TCC usa "ISSQN". Aqui ja normalizamos
# para o nome usado no TCC.
ANEXO3_TRIBUTO_NAMES = {
    "IPTULiquidoExcetoTransferenciasEFUNDEB": "IPTU",
    "ISSLiquidoExcetoTransferenciasEFUNDEB": "ISSQN",
    "ITBILiquidoExcetoTransferenciasEFUNDEB": "ITBI",
}

_PREVISAO_COL_RE = re.compile(r"^\s*PREVIS[ÃA]O\s+ATUALIZADA\b", re.IGNORECASE)


# ---------- API publica ---------------------------------------------------


def extract_prefeitura_forecast(
    data_dir: Path | str,
    annex: str = "RREO-Anexo_03",
) -> pd.DataFrame:
    """Extrai a PREVISAO ATUALIZADA por (entidade, ano, tributo) do RREO-Anexo 03.

    Le todos os CSVs em ``<data_dir>/rreo/<annex>/``. Para cada
    (cod_ibge, exercicio, cod_conta) com mais de um bimestre coletado,
    mantem o de menor ``periodo`` (mais proximo da Previsao Inicial).

    Returns
    -------
    DataFrame com colunas:
      cod_ibge, entity_name, year, tributo, previsao_prefeitura, periodo_fonte
    """
    data_dir = Path(data_dir)
    raw = _load_raw_csvs(data_dir / "rreo" / annex)

    # Apenas a coluna de previsao e apenas as contas IPTU/ISS/ITBI.
    mask_col = raw["coluna"].astype(str).str.match(_PREVISAO_COL_RE)
    mask_acc = raw["cod_conta"].isin(ANEXO3_TRIBUTO_NAMES)
    df = raw[mask_col & mask_acc].copy()
    if df.empty:
        logger.warning("Nenhuma linha 'PREVISAO ATUALIZADA' para IPTU/ISS/ITBI.")
        return pd.DataFrame(
            columns=["cod_ibge", "entity_name", "year", "tributo",
                     "previsao_prefeitura", "periodo_fonte"]
        )

    # Mantem apenas o ente municipal (descarta consorcios, camara, etc.).
    if "instituicao" in df.columns:
        main = df["instituicao"].astype(str).str.contains(
            r"Prefeitura|Governo|Poder Executivo", case=False, na=False
        )
        if main.any():
            df = df[main]

    df["year"] = df["exercicio"].astype(int)
    df["periodo"] = df["periodo"].astype(int)
    df["tributo"] = df["cod_conta"].map(ANEXO3_TRIBUTO_NAMES)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df = df.dropna(subset=["valor"])

    # Para cada (cod_ibge, year, tributo), escolhe o menor periodo coletado.
    df = df.sort_values("periodo")
    df = df.drop_duplicates(subset=["cod_ibge", "year", "tributo"], keep="first")

    out = df.rename(columns={
        "instituicao": "entity_name",
        "valor": "previsao_prefeitura",
        "periodo": "periodo_fonte",
    })[["cod_ibge", "entity_name", "year", "tributo",
        "previsao_prefeitura", "periodo_fonte"]]
    return out.sort_values(["cod_ibge", "tributo", "year"]).reset_index(drop=True)


def extract_realizado_anual(
    data_dir: Path | str,
    annex: str = "RREO-Anexo_03",
) -> pd.DataFrame:
    """Soma os doze meses do calendario para obter o realizado anual por tributo.

    Usa ``transform.extract_monthly_revenue`` (mesma logica da serie mensal)
    e agrega por (cod_ibge, year). Apenas anos com os 12 meses presentes
    entram no resultado.

    Returns
    -------
    DataFrame com colunas: cod_ibge, year, tributo, realizado_anual
    """
    data_dir = Path(data_dir)
    raw = _load_raw_csvs(data_dir / "rreo" / annex)
    monthly = extract_monthly_revenue(raw)

    tributo_cols = {"IPTU": "iptu", "ISSQN": "iss", "ITBI": "itbi"}
    have = {t: c for t, c in tributo_cols.items() if c in monthly.columns}
    if not have:
        return pd.DataFrame(columns=["cod_ibge", "year", "tributo", "realizado_anual"])

    counts = monthly.groupby(["cod_ibge", "year"])["month"].nunique()
    full_years = counts[counts == 12].index  # MultiIndex (cod_ibge, year)

    rows = []
    grouped = monthly.groupby(["cod_ibge", "year"])
    for (cod, year), g in grouped:
        if (cod, year) not in full_years:
            continue
        for tributo, col in have.items():
            total = pd.to_numeric(g[col], errors="coerce").sum(min_count=1)
            if pd.notna(total):
                rows.append({"cod_ibge": cod, "year": int(year),
                             "tributo": tributo, "realizado_anual": float(total)})
    return pd.DataFrame(rows)


def cross_with_realizado(
    prefeitura: pd.DataFrame,
    realizado_anual: pd.DataFrame,
) -> pd.DataFrame:
    """Cruza previsao da prefeitura com realizado anual de cada tributo.

    Adiciona colunas:
      realizado_anual       valor realizado no ano (soma dos 12 meses)
      erro_pct_prefeitura   abs(realizado - previsao) / realizado * 100
      vies_prefeitura       sinal(realizado - previsao)  (+1 = subestimacao)
    """
    if prefeitura.empty:
        return prefeitura
    df = prefeitura.merge(
        realizado_anual, on=["cod_ibge", "year", "tributo"], how="left"
    )
    realiz = pd.to_numeric(df["realizado_anual"], errors="coerce")
    prev = pd.to_numeric(df["previsao_prefeitura"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        df["erro_pct_prefeitura"] = (realiz - prev).abs() / realiz.replace(0, np.nan) * 100.0
    df["vies_prefeitura"] = np.sign(realiz - prev)
    return df.sort_values(["cod_ibge", "tributo", "year"]).reset_index(drop=True)
