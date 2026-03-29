"""Unit tests for the entity registry."""

from siconfi.entities import Entity, EntityRegistry


def _make_entity(**kwargs) -> Entity:
    defaults = {
        "cod_ibge": 3550308,
        "name": "São Paulo",
        "uf": "SP",
        "sphere": "M",
        "region": "SE",
        "is_capital": True,
        "population": 12_300_000,
    }
    defaults.update(kwargs)
    return Entity(**defaults)


def test_by_state():
    registry = EntityRegistry(entities=[
        _make_entity(cod_ibge=1, uf="SP", name="City A"),
        _make_entity(cod_ibge=2, uf="RJ", name="City B"),
        _make_entity(cod_ibge=3, uf="SP", name="City C"),
    ])
    result = registry.by_state("SP")
    assert len(result) == 2
    assert all(e.uf == "SP" for e in result)


def test_by_states():
    registry = EntityRegistry(entities=[
        _make_entity(cod_ibge=1, uf="SP"),
        _make_entity(cod_ibge=2, uf="RJ"),
        _make_entity(cod_ibge=3, uf="MG"),
    ])
    result = registry.by_states(["SP", "RJ"])
    assert len(result) == 2


def test_by_population():
    registry = EntityRegistry(entities=[
        _make_entity(cod_ibge=1, population=50_000),
        _make_entity(cod_ibge=2, population=200_000),
        _make_entity(cod_ibge=3, population=500_000),
    ])
    result = registry.by_population(min_pop=100_000, max_pop=300_000)
    assert len(result) == 1
    assert result[0].cod_ibge == 2


def test_find():
    registry = EntityRegistry(entities=[
        _make_entity(cod_ibge=1, name="São Paulo"),
        _make_entity(cod_ibge=2, name="Campinas"),
        _make_entity(cod_ibge=3, name="Paulínia"),
    ])
    result = registry.find("paul")
    assert len(result) == 2  # São Paulo and Paulínia


def test_by_region():
    registry = EntityRegistry(entities=[
        _make_entity(cod_ibge=1, region="SE"),
        _make_entity(cod_ibge=2, region="NE"),
        _make_entity(cod_ibge=3, region="SE"),
    ])
    result = registry.by_region("SE")
    assert len(result) == 2


def test_by_codes():
    registry = EntityRegistry(entities=[
        _make_entity(cod_ibge=100),
        _make_entity(cod_ibge=200),
        _make_entity(cod_ibge=300),
    ])
    result = registry.by_codes([100, 300])
    assert len(result) == 2
    assert {e.cod_ibge for e in result} == {100, 300}


def test_from_api_format():
    raw = {
        "cod_ibge": 3550308,
        "ente": "São Paulo",
        "uf": "SP",
        "esfera": "M",
        "regiao": "SE",
        "capital": "1",
        "populacao": 12300000,
    }
    entity = Entity.from_api(raw)
    assert entity.cod_ibge == 3550308
    assert entity.name == "São Paulo"
    assert entity.is_capital is True
    assert entity.sphere == "M"
