"""Low-level HTTP client for the SICONFI REST API.

Handles pagination, retries with exponential backoff, and rate limiting.
All public functions return raw Python dicts/lists parsed from JSON responses.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"

# Default page size used by the API when no limit is specified.
DEFAULT_PAGE_SIZE = 5_000

# Seconds to wait between consecutive API requests to avoid overloading the server.
DEFAULT_DELAY = 0.5


def _build_session(max_retries: int = 5, backoff_factor: float = 1.0) -> requests.Session:
    """Create a requests session with automatic retry on transient errors."""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Accept": "application/json"})
    return session


# Module-level session reused across calls.
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


def fetch_paginated(
    endpoint: str,
    params: dict[str, Any],
    *,
    delay: float = DEFAULT_DELAY,
) -> list[dict[str, Any]]:
    """Fetch all pages from a paginated SICONFI endpoint.

    Parameters
    ----------
    endpoint : str
        Endpoint path relative to ``BASE_URL`` (e.g. ``"entes"``).
    params : dict
        Query parameters forwarded to the API.
    delay : float
        Seconds to sleep between page requests.

    Returns
    -------
    list[dict]
        Concatenated ``items`` from all response pages.
    """
    session = _get_session()
    url = f"{BASE_URL}/{endpoint}"
    all_items: list[dict[str, Any]] = []
    offset = 0

    while True:
        paginated_params = {**params, "offset": offset, "limit": DEFAULT_PAGE_SIZE}
        logger.debug("GET %s params=%s", url, paginated_params)

        resp = session.get(url, params=paginated_params, timeout=120)
        resp.raise_for_status()
        body = resp.json()

        items = body.get("items", [])
        all_items.extend(items)

        has_more = body.get("hasMore", False)
        if not has_more or not items:
            break

        offset += len(items)
        time.sleep(delay)

    return all_items


# ── Convenience wrappers for each SICONFI endpoint ──────────────────────────


def fetch_entities(year: int | None = None) -> list[dict[str, Any]]:
    """Fetch the registry of all government entities (municipalities, states, union)."""
    params: dict[str, Any] = {}
    if year is not None:
        params["an_referencia"] = year
    return fetch_paginated("entes", params)


def fetch_rreo(
    entity_id: int,
    year: int,
    period: int,
    annex: str,
    report_type: str = "RREO",
    *,
    delay: float = DEFAULT_DELAY,
) -> list[dict[str, Any]]:
    """Fetch an RREO annex for a given entity, year, and bimonthly period.

    Parameters
    ----------
    entity_id : int
        IBGE code of the municipality or state.
    year : int
        Fiscal year (e.g. 2023).
    period : int
        Bimonthly period (1–6).
    annex : str
        Annex identifier (e.g. ``"RREO-Anexo 01"``).
    report_type : str
        ``"RREO"`` or ``"RREO Simplificado"``.
    delay : float
        Seconds to sleep between page requests.
    """
    params = {
        "an_exercicio": year,
        "nr_periodo": period,
        "co_tipo_demonstrativo": report_type,
        "id_ente": entity_id,
        "no_anexo": annex,
    }
    return fetch_paginated("rreo", params, delay=delay)


def fetch_rgf(
    entity_id: int,
    year: int,
    period: int,
    periodicity: str = "Q",
    power: str = "E",
    annex: str = "RGF-Anexo 01",
    report_type: str = "RGF",
    *,
    delay: float = DEFAULT_DELAY,
) -> list[dict[str, Any]]:
    """Fetch an RGF annex for a given entity, year, and period.

    Parameters
    ----------
    entity_id : int
        IBGE code.
    year : int
        Fiscal year.
    period : int
        1–3 for quadrimestral (Q), 1–2 for semestral (S).
    periodicity : str
        ``"Q"`` (quadrimestral) or ``"S"`` (semestral).
    power : str
        Branch of government: ``"E"`` (executive), ``"L"`` (legislative),
        ``"J"`` (judiciary), ``"M"`` (public ministry), ``"D"`` (public defense).
    annex : str
        Annex identifier (e.g. ``"RGF-Anexo 01"``).
    report_type : str
        ``"RGF"`` or ``"RGF Simplificado"``.
    delay : float
        Seconds to sleep between page requests.
    """
    params = {
        "an_exercicio": year,
        "nr_periodo": period,
        "in_periodicidade": periodicity,
        "co_poder": power,
        "co_tipo_demonstrativo": report_type,
        "id_ente": entity_id,
        "no_anexo": annex,
    }
    return fetch_paginated("rgf", params, delay=delay)


def fetch_dca(
    entity_id: int,
    year: int,
    annex: str = "DCA-Anexo I-AB",
    *,
    delay: float = DEFAULT_DELAY,
) -> list[dict[str, Any]]:
    """Fetch a DCA annex for a given entity and year.

    Parameters
    ----------
    entity_id : int
        IBGE code.
    year : int
        Fiscal year.
    annex : str
        Annex identifier (e.g. ``"DCA-Anexo I-AB"``).
    delay : float
        Seconds to sleep between page requests.
    """
    params = {
        "an_exercicio": year,
        "id_ente": entity_id,
        "no_anexo": annex,
    }
    return fetch_paginated("dca", params, delay=delay)


def fetch_extracts(
    entity_id: int,
    year: int,
    *,
    delay: float = DEFAULT_DELAY,
) -> list[dict[str, Any]]:
    """Fetch delivery status for a given entity and year."""
    params = {
        "an_referencia": year,
        "id_ente": entity_id,
    }
    return fetch_paginated("extrato_entregas", params, delay=delay)


def fetch_report_annexes() -> list[dict[str, Any]]:
    """Fetch the catalog of all available report annexes."""
    return fetch_paginated("anexos-relatorios", {})
