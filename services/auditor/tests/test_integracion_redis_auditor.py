"""El ciclo contra un Redis real. Se omite si `REDIS_URL_PRUEBAS` no está definida.

    REDIS_URL_PRUEBAS=redis://localhost:6379/15 pytest -m integracion services/auditor

Usa una base aparte y la vacía: no apuntar nunca a la base del stack.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from redis import Redis
from soporte_auditor import RelojFalso, ValidacionFalsa, campos, configuracion, evento_dict

from auditor import ciclo, seed
from auditor.cliente_validacion import ErrorValidacionRemota
from auditor.config import Config
from auditor.repositorio import Repositorio

URL = os.environ.get("REDIS_URL_PRUEBAS")

pytestmark = [
    pytest.mark.integracion,
    pytest.mark.skipif(URL is None, reason="REDIS_URL_PRUEBAS no definida"),
]


@pytest.fixture
def redis_real() -> Iterator[Redis]:
    assert URL is not None
    cliente = Redis.from_url(URL, decode_responses=True)
    cliente.flushdb()
    yield cliente
    cliente.flushdb()
    cliente.close()


@pytest.fixture
def entorno(tmp_path: Path) -> tuple[Config, Repositorio]:
    config = configuracion(tmp_path, tamano_lote=2)
    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    seed.sembrar(repositorio)
    return config, repositorio


def _publicar(cliente: Redis, config: Config, evento: dict[str, Any]) -> None:
    # redis-py tipa `fields` con un dict invariante de alias genéricos que
    # ningún dict[str, str] concreto satisface.
    datos: Any = campos(evento)
    cliente.xadd(config.stream_auditoria, datos)


def _pendientes(cliente: Redis, config: Config) -> int:
    return int(cliente.xpending(config.stream_auditoria, config.grupo)["pending"])


def test_ciclo_completo_con_redis_real(
    redis_real: Redis, entorno: tuple[Config, Repositorio]
) -> None:
    config, repositorio = entorno
    validacion = ValidacionFalsa()
    # Publicado antes de crear el grupo: el grupo nace en `0` y no lo pierde.
    _publicar(redis_real, config, evento_dict("E-ASN-01", "sur", "a-1"))
    ciclo.asegurar_grupo(redis_real, config)
    ciclo.asegurar_grupo(redis_real, config)  # BUSYGROUP tolerado
    for n, (eid, region) in enumerate([("E-ASN-01", "norte"), ("E-ASM-01", "centro")], 2):
        _publicar(redis_real, config, evento_dict(eid, region, f"a-{n}"))

    primero = ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())
    assert primero.repetir_sin_dormir  # lote de 2, venía lleno
    segundo = ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())
    assert not segundo.repetir_sin_dormir

    assert [c.evento_id for c in validacion.llamadas] == ["a-1", "a-3"]
    assert _pendientes(redis_real, config) == 0
    assert {h.region for h in repositorio.habitos("E-ASM-01")} == {"norte", "centro"}


def test_pendiente_por_validacion_caida_se_relee_con_redis_real(
    redis_real: Redis, entorno: tuple[Config, Repositorio]
) -> None:
    config, repositorio = entorno
    ciclo.asegurar_grupo(redis_real, config)
    _publicar(redis_real, config, evento_dict("E-ASN-01", "sur", "a-1"))
    validacion = ValidacionFalsa(fallo=ErrorValidacionRemota("caída", definitivo=False))

    ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())
    assert _pendientes(redis_real, config) == 1

    validacion.fallo = None
    ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())
    assert _pendientes(redis_real, config) == 0
    assert [c.evento_id for c in validacion.llamadas] == ["a-1", "a-1"]


def test_pendiente_recortado_por_maxlen_no_bloquea(
    redis_real: Redis, entorno: tuple[Config, Repositorio]
) -> None:
    """Si MAXLEN recorta un evento que seguía pendiente, Redis lo devuelve sin
    campos. Debe confirmarse y no bloquear para siempre la relectura."""
    config, repositorio = entorno
    ciclo.asegurar_grupo(redis_real, config)
    _publicar(redis_real, config, evento_dict("E-ASN-01", "sur", "a-1"))
    validacion = ValidacionFalsa(fallo=ErrorValidacionRemota("caída", definitivo=False))
    ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())
    _publicar(redis_real, config, evento_dict("E-ASN-02", "sur", "a-2"))
    redis_real.xtrim(config.stream_auditoria, maxlen=1, approximate=False)

    validacion.fallo = None
    ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())

    assert _pendientes(redis_real, config) == 0
    assert [c.evento_id for c in validacion.llamadas] == ["a-1", "a-2"]


def test_grupo_borrado_se_recrea_con_redis_real(
    redis_real: Redis, entorno: tuple[Config, Repositorio]
) -> None:
    config, repositorio = entorno
    ciclo.asegurar_grupo(redis_real, config)
    redis_real.xgroup_destroy(config.stream_auditoria, config.grupo)
    _publicar(redis_real, config, evento_dict("E-ASN-01", "sur", "a-1"))
    validacion = ValidacionFalsa()

    ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())
    ciclo.un_ciclo(redis_real, config, repositorio, validacion, RelojFalso())

    assert [c.evento_id for c in validacion.llamadas] == ["a-1"]
