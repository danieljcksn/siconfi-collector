"""Testes do trecho critico do coletor para o TCC: a extracao mensal do
Anexo 03 (serie usada na modelagem) e a regra P1 do benchmark da prefeitura
(base dos numeros canonicos 80%/73% do confronto anual).

Fixture: tests/fixtures/anexo03_minimo.csv, um Anexo 03 sintetico com:
  - 2023 P6 completo (iptu do mes m = 100+m; iss do mes m = 200+m);
  - 2023 P1 com valores DIVERGENTES (deve ser ignorado: vence o maior periodo)
    e um <MR-2> que cai em dez/2022 (mes de outro exercicio, descartado);
  - 2024 P3 incompleto (jan..jun) — nao pode entrar no realizado anual;
  - uma linha de consorcio duplicando o IPTU (deve ser filtrada);
  - PREVISAO ATUALIZADA do IPTU em P1 (1200) e P6 (1400) — P1 vence;
    do ISS apenas em P6.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from siconfi.prefeitura_forecast import (
    cross_with_realizado,
    extract_prefeitura_forecast,
    extract_realizado_anual,
)
from siconfi.transform import extract_monthly_revenue

FIXTURE = Path(__file__).parent / "fixtures" / "anexo03_minimo.csv"


@pytest.fixture()
def raw() -> pd.DataFrame:
    return pd.read_csv(FIXTURE, encoding="utf-8-sig")


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Replica o layout data/rreo/<annex>/ esperado pelas funcoes file-level."""
    d = tmp_path / "rreo" / "RREO-Anexo_03"
    d.mkdir(parents=True)
    shutil.copy(FIXTURE, d / "fixture.csv")
    return tmp_path


# ---------- extract_monthly_revenue (serie mensal da modelagem) ----------


def test_ano_completo_resolve_12_meses_na_ordem(raw):
    monthly = extract_monthly_revenue(raw)
    m23 = monthly[monthly["year"] == 2023]
    assert sorted(m23["month"]) == list(range(1, 13))
    # <MR-11> do P6 e janeiro; <MR> e dezembro.
    assert float(m23.loc[m23["month"] == 1, "iptu"].iloc[0]) == 101.0
    assert float(m23.loc[m23["month"] == 12, "iptu"].iloc[0]) == 112.0
    assert float(m23["iptu"].sum()) == 1278.0
    assert float(m23["iss"].sum()) == 2478.0


def test_maior_periodo_vence_e_mes_de_outro_exercicio_e_descartado(raw):
    monthly = extract_monthly_revenue(raw)
    m23 = monthly[monthly["year"] == 2023]
    # Os valores do P1 (55/44) nao podem vazar para a serie: vence o P6.
    assert 55.0 not in m23["iptu"].to_numpy()
    assert 44.0 not in m23["iptu"].to_numpy()
    # O <MR-2> do P1 cai em dez/2022: nenhum mes de 2022 na saida.
    assert 2022 not in monthly["year"].to_numpy()


def test_ano_incompleto_traz_so_os_meses_existentes(raw):
    monthly = extract_monthly_revenue(raw)
    m24 = monthly[monthly["year"] == 2024]
    assert sorted(m24["month"]) == [1, 2, 3, 4, 5, 6]


def test_consorcio_e_filtrado(raw):
    monthly = extract_monthly_revenue(raw)
    assert 999999.0 not in monthly["iptu"].to_numpy()


# ---------- benchmark da prefeitura (regra P1 e realizado anual) ----------


def test_previsao_usa_o_menor_periodo_p1(data_dir):
    pf = extract_prefeitura_forecast(data_dir)
    iptu23 = pf[(pf["year"] == 2023) & (pf["tributo"] == "IPTU")]
    assert len(iptu23) == 1
    assert int(iptu23["periodo_fonte"].iloc[0]) == 1
    assert float(iptu23["previsao_prefeitura"].iloc[0]) == 1200.0
    # ISS so tem P6 coletado: usa o que existe.
    iss23 = pf[(pf["year"] == 2023) & (pf["tributo"] == "ISSQN")]
    assert int(iss23["periodo_fonte"].iloc[0]) == 6


def test_realizado_anual_exige_12_meses(data_dir):
    ra = extract_realizado_anual(data_dir)
    anos_iptu = set(ra[ra["tributo"] == "IPTU"]["year"])
    assert anos_iptu == {2023}  # 2024 (6 meses) fica fora
    assert float(ra[(ra["year"] == 2023) & (ra["tributo"] == "IPTU")]
                 ["realizado_anual"].iloc[0]) == 1278.0


def test_erro_pct_e_vies_da_prefeitura(data_dir):
    pf = extract_prefeitura_forecast(data_dir)
    ra = extract_realizado_anual(data_dir)
    crossed = cross_with_realizado(pf, ra)
    row = crossed[(crossed["year"] == 2023) & (crossed["tributo"] == "IPTU")].iloc[0]
    esperado = abs(1278 - 1200) / 1278 * 100
    assert float(row["erro_pct_prefeitura"]) == pytest.approx(esperado)
    assert int(row["vies_prefeitura"]) == 1  # realizado > previsao: subestimacao
