# siconfi-collector

A robust, production-grade data collector for Brazil's **SICONFI** (Sistema de Informações Contábeis e Fiscais do Setor Público) public finance API, maintained by the Brazilian National Treasury (Tesouro Nacional).

SICONFI aggregates fiscal reports from all 5,570 Brazilian municipalities, 26 states, the Federal District, and the Union. This tool provides a clean command-line interface for downloading, organizing, and storing these reports locally for research, policy analysis, or forecasting applications.

## Features

- **Flexible entity selection** — collect data for individual municipalities, entire states, geographic regions, or the whole country
- **Population filtering** — target municipalities by population range (e.g., mid-sized cities between 100k–500k)
- **Multiple report types** — supports RREO (budget execution), RGF (fiscal management), and DCA (annual accounts)
- **Resume capability** — automatically skips already-downloaded files, enabling safe interruption and restart of large collection jobs
- **Rate limiting** — configurable delay between requests to respect the API server
- **Automatic retry** — exponential backoff on transient HTTP errors (429, 5xx)
- **Structured output** — organized directory tree by report type, annex, state, and entity
- **Entity registry cache** — fetches the full municipality/state list once and caches it locally
- **Progress tracking** — real-time progress bars with entity-level status

## Supported Reports

| Report | Full Name | Periodicity | Key Contents |
|--------|-----------|-------------|--------------|
| **RREO** | Relatório Resumido da Execução Orçamentária | Bimonthly (6/year) | Budget revenue, expenditure by function, fiscal results |
| **RGF** | Relatório de Gestão Fiscal | Quadrimestral (3/year) or Semestral (2/year) | Personnel spending, debt, credit operations |
| **DCA** | Declaração de Contas Anuais | Annual | Balance sheet, equity changes, cash flow |

### RREO Annexes

| Annex | Description |
|-------|-------------|
| `RREO-Anexo 01` | Budget Revenue (Receitas Orçamentárias) |
| `RREO-Anexo 02` | Expenditure by Function and Subfunction |
| `RREO-Anexo 03` | Net Current Revenue (Receita Corrente Líquida) |
| `RREO-Anexo 06` | Primary and Nominal Fiscal Result |
| `RREO-Anexo 07` | Remaining Payables (Restos a Pagar) |
| `RREO-Anexo 14` | Simplified Net Revenue |

### DCA Annexes

| Annex | Description |
|-------|-------------|
| `DCA-Anexo I-AB` | Balance Sheet (Assets and Liabilities) |
| `DCA-Anexo I-C` | Statement of Equity Changes |
| `DCA-Anexo I-D` | Budget Balance (Balanço Orçamentário) |
| `DCA-Anexo I-E` | Cash Flow Statement |
| `DCA-Anexo I-F` | Statement of Changes in Net Equity |
| `DCA-Anexo I-HI` | Supplementary Statistics |

## Installation

**Requirements:** Python 3.10 or later.

```bash
# Clone the repository
git clone https://github.com/danieljcksn/siconfi-collector.git
cd siconfi-collector

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in editable mode
pip install -e .

# (Optional) Install Parquet support
pip install -e ".[parquet]"

# (Optional) Install development tools
pip install -e ".[dev]"
```

## Quick Start

### 1. Explore available entities

```bash
# List all municipalities in Rio Grande do Sul
siconfi entities --state RS

# Search for a municipality by name
siconfi entities --search "Campinas"

# List municipalities with population between 100k and 500k in São Paulo
siconfi entities --state SP --min-pop 100000 --max-pop 500000

# List state capitals
siconfi entities --search "" --min-pop 0  # then filter manually, or:
siconfi entities --state SP --search "São Paulo"
```

### 2. Collect revenue data (RREO)

```bash
# Single municipality — Campinas/SP (IBGE code 3509502)
siconfi collect rreo --entity 3509502 --years 2015-2024

# All municipalities in a state
siconfi collect rreo --state RS --years 2020-2024

# Multiple states
siconfi collect rreo --state SP --state RJ --state MG --years 2020-2024

# Entire geographic region
siconfi collect rreo --region SE --years 2022-2024

# Entire country (be mindful of API load — use a higher delay)
siconfi collect rreo --all --years 2023-2024 --delay 1.0

# Only mid-sized municipalities (100k–500k population)
siconfi collect rreo --all --min-pop 100000 --max-pop 500000 --years 2020-2024

# Specific annex and periods
siconfi collect rreo --state SP --years 2023 --annex "RREO-Anexo 03" --periods 1,2,3
```

### 3. Collect fiscal management data (RGF)

```bash
# Executive branch, quadrimestral
siconfi collect rgf --entity 3550308 --years 2020-2024

# Legislative branch, semestral
siconfi collect rgf --state RS --years 2020-2024 --power L --periodicity S
```

### 4. Collect annual accounts (DCA)

```bash
# Balance sheet for a municipality
siconfi collect dca --entity 3550308 --years 2015-2024

# Cash flow statement for an entire state
siconfi collect dca --state MG --years 2020-2024 --annex "DCA-Anexo I-E"
```

### 5. Transform raw data into clean time series

The raw CSV files contain one row per (account x column_type) combination, which is
hard to work with. The `transform` command pivots this into a clean, analysis-ready
format with one row per (entity, year, bimonthly period) and revenue categories as columns.

```bash
# Transform collected RREO data into bimonthly revenue increments
siconfi transform

# Output cumulative year-to-date totals instead
siconfi transform --cumulative

# Save to a specific file
siconfi transform --output my_analysis/revenue.csv
```

**Example output** (bimonthly increments for a municipality):

| year | period | period_label | Impostos | Taxas | TransferenciasCorrentes | TotalReceitas |
|------|--------|-------------|----------|-------|------------------------|---------------|
| 2024 | 1 | Jan-Feb | 375,814 | 39,878 | 13,829,615 | 14,674,161 |
| 2024 | 2 | Mar-Apr | 740,399 | 14,025 | 15,808,247 | 18,523,297 |
| 2024 | 3 | May-Jun | 630,948 | 49,533 | 13,770,674 | 15,900,638 |
| ... | ... | ... | ... | ... | ... | ... |

### 6. Extract monthly revenue time series (recommended for forecasting)

**RREO-Anexo 03** (Net Current Revenue) contains individual monthly values encoded
in `<MR>` columns.  This gives you 12 data points per year instead of 6, with
individual tax categories (IPTU, ISS, ITBI, FPM, ICMS, IPVA, FUNDEB, etc.) broken out.

```bash
# Step 1: Collect Anexo 03 data (only period 6 needed — it contains all 12 months)
siconfi collect rreo --entity 3509502 --years 2015-2024 --annex "RREO-Anexo 03" --periods 6

# Step 2: Transform to monthly time series
siconfi transform-monthly
```

**Example output** — one row per month, revenue broken down by tax:

| year | month | month_name | iptu | iss | fpm | icms | net_current_revenue |
|------|-------|------------|------|-----|-----|------|-------------------|
| 2024 | 1 | Jan | 9,122 | 159,210 | 2,426,875 | 349,878 | 7,534,280 |
| 2024 | 2 | Feb | 2,138 | 64,430 | 3,299,946 | 296,368 | 7,139,881 |
| 2024 | 3 | Mar | 4,434 | 81,527 | 2,057,335 | 310,482 | 5,267,543 |
| ... | ... | ... | ... | ... | ... | ... | ... |

This is the recommended format for time series forecasting research — 120+ monthly
observations over 10 years, with granular tax category breakdown.

### 7. Extract the municipality's own budget forecast (benchmark)

**RREO-Anexo 03** also carries a `PREVISÃO ATUALIZADA <year>` column per revenue
category. The `transform-prefeitura-forecast` command extracts it per
(entity, year, tax), crosses it with the realized annual total (sum of the twelve
`<MR>` months of the same annex), and computes the municipality's own forecast
error — a natural benchmark for any forecasting model.

When more than one bimonthly period was collected for the same year, the command
keeps the LOWEST period number (P1 is the closest to the original LOA budget
forecast, before mid-year revisions). Collect period 1 alongside period 6 if you
want this benchmark:

```bash
# Step 1: collect periods 1 (forecast source) and 6 (all 12 realized months)
siconfi collect rreo --entity 3509502 --years 2015-2024 --annex "RREO-Anexo 03" --periods 1,6

# Step 2: build the benchmark table
siconfi transform-prefeitura-forecast
```

Output columns: `cod_ibge`, `entity_name`, `year`, `tributo`,
`previsao_prefeitura`, `periodo_fonte` (1 = closest to the LOA),
`realizado_anual`, `erro_pct_prefeitura`, `vies_prefeitura`.

### 8. View available report types and codes

```bash
siconfi info
```

## Output Structure

Data is saved as CSV files in a structured directory tree:

```
data/
├── entities.json                          # Cached entity registry
├── rreo/
│   └── RREO-Anexo_01/
│       ├── SP/
│       │   ├── 3509502/                   # Campinas
│       │   │   ├── 2020_P1.csv
│       │   │   ├── 2020_P2.csv
│       │   │   └── ...
│       │   └── 3550308/                   # São Paulo
│       │       └── ...
│       └── RS/
│           └── ...
├── rgf/
│   └── RGF-Anexo_01/
│       └── ...
└── dca/
    └── DCA-Anexo_I-AB/
        └── ...
```

Each CSV file corresponds to a single API response (one entity, one year, one period) and contains the following columns:

| Column | Description |
|--------|-------------|
| `exercicio` | Fiscal year |
| `demonstrativo` | Report type |
| `periodo` | Period number |
| `periodicidade` | Periodicity code |
| `instituicao` | Institution name |
| `cod_ibge` | IBGE entity code |
| `uf` | State abbreviation |
| `populacao` | Population |
| `anexo` | Annex identifier |
| `esfera` | Sphere (M/E/U/D) |
| `rotulo` | Row label |
| `coluna` | Column header from the original report |
| `cod_conta` | Account code |
| `conta` | Account name |
| `valor` | Numeric value |

## Resume and Fault Tolerance

The collector is designed for long-running jobs across thousands of municipalities:

- **Resume by default** — if a CSV file already exists for a given (entity, year, period), it is skipped. This means you can safely interrupt with `Ctrl+C` and restart.
- **Automatic retry** — transient HTTP errors (429, 500, 502, 503, 504) trigger automatic retry with exponential backoff (up to 5 retries).
- **Error logging** — failed requests are counted and the first errors are displayed in the summary. Enable `--verbose` for full debug logging.
- **Disable resume** — use `--no-resume` to force re-downloading all data.

## Collection Scale Estimates

| Scope | Entities | Years | Periods | Total Requests | Estimated Time (0.5s delay) |
|-------|----------|-------|---------|----------------|---------------------------|
| Single city, 10 years | 1 | 10 | 6 | 60 | ~1 min |
| One state (avg. ~200 cities), 5 years | 200 | 5 | 6 | 6,000 | ~1 hour |
| Whole country, 1 year | 5,570 | 1 | 6 | 33,420 | ~5 hours |
| Whole country, 10 years | 5,570 | 10 | 6 | 334,200 | ~46 hours |

For large-scale collection, consider increasing `--delay` to 1.0 or higher to be respectful of the API infrastructure.

## Programmatic Usage

The package can be used as a library in Python scripts or Jupyter notebooks:

```python
from siconfi.entities import EntityRegistry
from siconfi.collector import collect_rreo
from pathlib import Path

# Load entity registry
registry = EntityRegistry.from_api()

# Select targets
cities = registry.by_state("RS")
cities = [c for c in cities if c.population >= 100_000]

# Collect RREO Annex 01 for 2020–2024
result = collect_rreo(
    entities=cities,
    years=list(range(2020, 2025)),
    annex="RREO-Anexo 01",
    output_dir=Path("data"),
    delay=0.5,
)

print(f"Collected {result.successful} files, {result.failed} failures")
```

## API Reference

This tool interfaces with the SICONFI REST API provided by the Brazilian National Treasury:

- **Base URL:** `https://apidatalake.tesouro.gov.br/ords/siconfi/tt/`
- **Authentication:** None required (public data)
- **Documentation:** [SICONFI API Docs](https://apidatalake.tesouro.gov.br/docs/siconfi/)
- **Data portal:** [Tesouro Transparente](https://www.tesourotransparente.gov.br/)

### Endpoints Used

| Endpoint | Description |
|----------|-------------|
| `GET /tt/entes` | Entity registry (municipalities, states) |
| `GET /tt/rreo` | Budget execution reports |
| `GET /tt/rgf` | Fiscal management reports |
| `GET /tt/dca` | Annual accounts declarations |
| `GET /tt/extrato_entregas` | Report delivery status |
| `GET /tt/anexos-relatorios` | Available report annexes catalog |

## Legal and Institutional Context

SICONFI data is published under Brazil's Access to Information Law (Lei nº 12.527/2011) and the Fiscal Responsibility Law (Lei Complementar nº 101/2000), which mandates transparency in public finance reporting. All data accessed through this tool is public information.

The fiscal reports collected here are the same documents that Brazilian municipalities and states are legally required to submit to the National Treasury. They are used for:

- Fiscal monitoring and compliance assessment
- Academic research on public finance
- Policy analysis and budget forecasting
- Civic transparency and accountability

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=siconfi

# Lint
ruff check src/ tests/
```

## License

MIT License. See [LICENSE](LICENSE) for details.