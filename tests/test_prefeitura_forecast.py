from pathlib import Path

import numpy as np
import pandas as pd

from siconfi.prefeitura_forecast import (
    cross_with_realizado,
    extract_prefeitura_forecast,
)


def _write_annex3(data_dir: Path, rows: list[dict]) -> None:
    path = data_dir / "rreo" / "RREO-Anexo_03" / "BA" / "2927408"
    path.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(path / "2024_P1.csv", index=False, encoding="utf-8-sig")


def test_extract_prefeitura_forecast_keeps_earliest_period(tmp_path: Path):
    rows = [
        {
            "cod_ibge": 2927408,
            "instituicao": "Prefeitura Municipal de Salvador",
            "uf": "BA",
            "exercicio": 2024,
            "periodo": 2,
            "coluna": "PREVISAO ATUALIZADA 2024",
            "cod_conta": "IPTULiquidoExcetoTransferenciasEFUNDEB",
            "valor": 120.0,
        },
        {
            "cod_ibge": 2927408,
            "instituicao": "Prefeitura Municipal de Salvador",
            "uf": "BA",
            "exercicio": 2024,
            "periodo": 1,
            "coluna": "PREVISÃO ATUALIZADA 2024",
            "cod_conta": "IPTULiquidoExcetoTransferenciasEFUNDEB",
            "valor": 100.0,
        },
        {
            "cod_ibge": 2927408,
            "instituicao": "Camara Municipal de Salvador",
            "uf": "BA",
            "exercicio": 2024,
            "periodo": 1,
            "coluna": "PREVISÃO ATUALIZADA 2024",
            "cod_conta": "IPTULiquidoExcetoTransferenciasEFUNDEB",
            "valor": 999.0,
        },
    ]
    _write_annex3(tmp_path, rows)

    result = extract_prefeitura_forecast(tmp_path)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["tributo"] == "IPTU"
    assert row["previsao_prefeitura"] == 100.0
    assert row["periodo_fonte"] == 1


def test_cross_with_realizado_computes_error_and_bias():
    prefeitura = pd.DataFrame(
        [
            {
                "cod_ibge": 2927408,
                "entity_name": "Prefeitura Municipal de Salvador",
                "year": 2024,
                "tributo": "ISSQN",
                "previsao_prefeitura": 90.0,
                "periodo_fonte": 1,
            }
        ]
    )
    realizado = pd.DataFrame(
        [{"cod_ibge": 2927408, "year": 2024, "tributo": "ISSQN", "realizado_anual": 100.0}]
    )

    result = cross_with_realizado(prefeitura, realizado)

    assert result.loc[0, "erro_pct_prefeitura"] == 10.0
    assert result.loc[0, "vies_prefeitura"] == 1.0


def test_cross_with_realizado_ignores_zero_denominator():
    prefeitura = pd.DataFrame(
        [
            {
                "cod_ibge": 2927408,
                "entity_name": "Prefeitura Municipal de Salvador",
                "year": 2024,
                "tributo": "IPTU",
                "previsao_prefeitura": 90.0,
                "periodo_fonte": 1,
            }
        ]
    )
    realizado = pd.DataFrame(
        [{"cod_ibge": 2927408, "year": 2024, "tributo": "IPTU", "realizado_anual": 0.0}]
    )

    result = cross_with_realizado(prefeitura, realizado)

    assert np.isnan(result.loc[0, "erro_pct_prefeitura"])
    assert result.loc[0, "vies_prefeitura"] == -1.0
