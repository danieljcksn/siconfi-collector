"""Entity registry: lookup municipalities and states by name, code, or region.

Provides a cached in-memory registry that is populated once from the API (or from
a local cache file) and then queried repeatedly during collection runs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from siconfi.api import fetch_entities

logger = logging.getLogger(__name__)

# Two-letter state codes → full names (for display purposes).
STATE_NAMES: dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais", "MS": "Mato Grosso do Sul",
    "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RO": "Rondônia", "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina",
    "SE": "Sergipe", "SP": "São Paulo", "TO": "Tocantins",
}

REGIONS: dict[str, str] = {
    "NO": "Norte", "NE": "Nordeste", "SE": "Sudeste", "SU": "Sul", "CO": "Centro-Oeste",
}


@dataclass
class Entity:
    """A government entity (municipality, state, or union)."""

    cod_ibge: int
    name: str
    uf: str
    sphere: str  # M = municipality, E = state, U = union, D = distrito federal
    region: str
    is_capital: bool
    population: int

    @classmethod
    def from_api(cls, raw: dict) -> Entity:
        return cls(
            cod_ibge=int(raw["cod_ibge"]),
            name=raw.get("ente", ""),
            uf=raw.get("uf", ""),
            sphere=raw.get("esfera", ""),
            region=raw.get("regiao", ""),
            is_capital=raw.get("capital") == "1",
            population=int(raw.get("populacao", 0) or 0),
        )


@dataclass
class EntityRegistry:
    """In-memory registry of all SICONFI entities with filtering helpers."""

    entities: list[Entity] = field(default_factory=list)

    # ── Loading ──────────────────────────────────────────────────────────────

    @classmethod
    def from_api(cls, year: int | None = None) -> EntityRegistry:
        """Fetch all entities from the SICONFI API."""
        logger.info("Fetching entity registry from SICONFI API (year=%s)…", year)
        raw = fetch_entities(year)
        entities = [Entity.from_api(r) for r in raw]
        logger.info("Loaded %d entities from API.", len(entities))
        return cls(entities=entities)

    @classmethod
    def from_cache(cls, path: Path) -> EntityRegistry:
        """Load previously saved entity registry from a JSON file."""
        with open(path) as fh:
            data = json.load(fh)
        entities = [Entity(**e) for e in data]
        logger.info("Loaded %d entities from cache %s.", len(entities), path)
        return cls(entities=entities)

    def save_cache(self, path: Path) -> None:
        """Persist the registry to a JSON file for offline reuse."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.__dict__ for e in self.entities]
        with open(path, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        logger.info("Saved %d entities to %s.", len(self.entities), path)

    # ── Queries ──────────────────────────────────────────────────────────────

    def municipalities(self) -> list[Entity]:
        return [e for e in self.entities if e.sphere == "M"]

    def states(self) -> list[Entity]:
        return [e for e in self.entities if e.sphere == "E"]

    def by_state(self, uf: str) -> list[Entity]:
        """Return all municipalities in a given state (two-letter code)."""
        uf = uf.upper()
        return [e for e in self.entities if e.uf == uf and e.sphere == "M"]

    def by_states(self, ufs: Sequence[str]) -> list[Entity]:
        """Return all municipalities in one or more states."""
        uf_set = {u.upper() for u in ufs}
        return [e for e in self.entities if e.uf in uf_set and e.sphere == "M"]

    def by_region(self, region: str) -> list[Entity]:
        """Return all municipalities in a given region (NO/NE/SE/SU/CO)."""
        region = region.upper()
        return [e for e in self.entities if e.region == region and e.sphere == "M"]

    def by_codes(self, codes: Sequence[int]) -> list[Entity]:
        """Return entities matching the given IBGE codes."""
        code_set = set(codes)
        return [e for e in self.entities if e.cod_ibge in code_set]

    def by_population(self, min_pop: int = 0, max_pop: int | None = None) -> list[Entity]:
        """Return municipalities within a population range."""
        result = [e for e in self.municipalities() if e.population >= min_pop]
        if max_pop is not None:
            result = [e for e in result if e.population <= max_pop]
        return result

    def find(self, query: str) -> list[Entity]:
        """Search entities by name (case-insensitive substring match)."""
        q = query.lower()
        return [e for e in self.entities if q in e.name.lower()]
