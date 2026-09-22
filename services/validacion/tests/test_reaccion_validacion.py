import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from soporte_validacion import (
    ClienteAutenticacionFalso,
    RedisStreamsFalso,
    configuracion,
    evento_seguridad_dict,
)

from validacion import reaccion
from validacion.cliente_autenticacion import ErrorContencion
from validacion.config import Config
from validacion.contracts import (
    AccionSeguridad,
    Alerta,
    EventoSeguridad,
    MotivoSeguridad,
    ahora_utc,
)
from validacion.repositorio import Repositorio

STREAM = "seguridad"
GRUPO = "reaccion"


@pytest.fixture
def repo(tmp_path: Path) -> Repositorio:
    repositorio = Repositorio(tmp_path / "validacion.db")
    repositorio.inicializar()
    return repositorio


@pytest.fixture
def streams() -> RedisStreamsFalso:
    return RedisStreamsFalso()


@pytest.fixture
def cliente_auth() -> ClienteAutenticacionFalso:
    return ClienteAutenticacionFalso()


def _publicar(streams: RedisStreamsFalso, **cambios: object) -> str:
    campos = {"data": json.dumps(evento_seguridad_dict(**cambios), ensure_ascii=False)}
    return streams.xadd(STREAM, campos)


def _config(tmp_path: Path) -> Config:
    return configuracion(tmp_path, stream_seguridad=STREAM, grupo_reaccion=GRUPO)


# --- consumidor ---------------------------------------------------------------


def test_revocar_llama_revocacion_y_luego_bloqueo_y_marca_la_alerta(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    _publicar(streams, evento_id="ev-1", session_id="s-1", motivo="OTP_FALLIDO", accion="REVOCAR")

    hubo_fallo = reaccion.una_vuelta(streams, config, repo, cliente_auth)

    assert hubo_fallo is False
    assert [llamada[0] for llamada in cliente_auth.llamadas] == ["revocar", "bloquear"]
    alerta = repo.alerta_por_clave("s-1", MotivoSeguridad.OTP_FALLIDO)
    assert alerta is not None
    assert alerta.revocada_en is not None
    assert alerta.bloqueado_en is not None
    assert streams.pendientes(STREAM, GRUPO) == []


def test_alertar_no_llama_a_autenticacion_y_registra_la_alerta(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    _publicar(
        streams,
        evento_id="ev-1",
        session_id="s-1",
        motivo="CONSULTA_INUSUAL",
        accion="ALERTAR",
        detalle={"accion": "CONSULTA_POLIZA", "region_consultada": "centro"},
    )

    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is False
    assert cliente_auth.llamadas == []
    alerta = repo.alerta_por_clave("s-1", MotivoSeguridad.CONSULTA_INUSUAL)
    assert alerta is not None
    assert alerta.revocada_en is None
    assert streams.pendientes(STREAM, GRUPO) == []


def test_evento_duplicado_no_produce_segunda_llamada_y_hace_xack(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    _publicar(streams, evento_id="ev-1", session_id="s-1", motivo="OTP_FALLIDO", accion="REVOCAR")
    reaccion.una_vuelta(streams, config, repo, cliente_auth)
    assert len(cliente_auth.llamadas) == 2

    _publicar(streams, evento_id="ev-2", session_id="s-1", motivo="OTP_FALLIDO", accion="REVOCAR")
    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is False
    assert len(cliente_auth.llamadas) == 2
    assert len(repo.listar_alertas()) == 1
    assert streams.pendientes(STREAM, GRUPO) == []


def test_fallo_transitorio_deja_la_alerta_sin_revocar_y_no_hace_xack(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    cliente_auth.fallo_revocar = ErrorContencion("timeout", definitivo=False)
    mensaje_id = _publicar(
        streams, evento_id="ev-1", session_id="s-1", motivo="OTP_FALLIDO", accion="REVOCAR"
    )

    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is True
    assert [llamada[0] for llamada in cliente_auth.llamadas] == ["revocar"]
    alerta = repo.alerta_por_clave("s-1", MotivoSeguridad.OTP_FALLIDO)
    assert alerta is not None
    assert alerta.revocada_en is None
    assert streams.pendientes(STREAM, GRUPO) == [mensaje_id]


def test_reintento_tras_fallo_transitorio_completa_sin_duplicar(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    cliente_auth.fallo_revocar = ErrorContencion("timeout", definitivo=False)
    _publicar(streams, evento_id="ev-1", session_id="s-1", motivo="OTP_FALLIDO", accion="REVOCAR")
    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is True

    cliente_auth.fallo_revocar = None
    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is False
    assert [llamada[0] for llamada in cliente_auth.llamadas] == ["revocar", "revocar", "bloquear"]
    todas = repo.listar_alertas()
    assert len(todas) == 1
    assert todas[0].revocada_en is not None
    assert streams.pendientes(STREAM, GRUPO) == []


def test_fallo_definitivo_404_hace_xack_y_no_se_reintenta(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    cliente_auth.fallo_revocar = ErrorContencion("404", definitivo=True)
    _publicar(streams, evento_id="ev-1", session_id="s-1", motivo="OTP_FALLIDO", accion="REVOCAR")

    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is False
    assert [llamada[0] for llamada in cliente_auth.llamadas] == ["revocar"]
    alerta = repo.alerta_por_clave("s-1", MotivoSeguridad.OTP_FALLIDO)
    assert alerta is not None
    assert alerta.revocada_en is None
    assert streams.pendientes(STREAM, GRUPO) == []


def test_mensaje_corrupto_no_tumba_el_consumidor_y_hace_xack(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    corrupto = streams.xadd(STREAM, {"data": "no es JSON"})
    incompleto = streams.xadd(STREAM, {"data": json.dumps({"evento_id": "x"})})

    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is False
    assert cliente_auth.llamadas == []
    assert corrupto not in streams.pendientes(STREAM, GRUPO)
    assert incompleto not in streams.pendientes(STREAM, GRUPO)


def test_grupo_desaparecido_se_recrea(
    tmp_path: Path,
    repo: Repositorio,
    streams: RedisStreamsFalso,
    cliente_auth: ClienteAutenticacionFalso,
) -> None:
    config = _config(tmp_path)
    reaccion.asegurar_grupo(streams, config)
    streams.eliminar_grupo(STREAM, GRUPO)

    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is False
    _publicar(streams, evento_id="ev-1", session_id="s-1", motivo="OTP_FALLIDO", accion="REVOCAR")
    assert reaccion.una_vuelta(streams, config, repo, cliente_auth) is False
    assert repo.alerta_por_clave("s-1", MotivoSeguridad.OTP_FALLIDO) is not None


# --- contrato del evento ---------------------------------------------------------


def test_evento_seguridad_ida_y_vuelta() -> None:
    crudo = evento_seguridad_dict()
    evento = EventoSeguridad.desde_dict(crudo)
    assert evento.motivo is MotivoSeguridad.OTP_FALLIDO
    assert evento.accion is AccionSeguridad.REVOCAR
    assert evento.a_dict() == crudo


# --- tabla alertas -----------------------------------------------------------------


def _alerta(**cambios: object) -> Alerta:
    base: dict[str, object] = {
        "evento_id": "ev-1",
        "session_id": "s-1",
        "employee_id": "E-ASN-01",
        "motivo": MotivoSeguridad.OTP_FALLIDO,
        "accion": AccionSeguridad.REVOCAR,
        "correlation_id": "c-1",
        "detalle": {"operacion": "aprobar_poliza"},
        "recibida_en": ahora_utc(),
    }
    base.update(cambios)
    return Alerta(**base)  # type: ignore[arg-type]


def test_unique_session_motivo_impide_duplicados(repo: Repositorio) -> None:
    repo.insertar_alerta(_alerta(evento_id="ev-1"))
    with pytest.raises(sqlite3.IntegrityError):
        repo.insertar_alerta(_alerta(evento_id="ev-2"))


def test_listar_alertas_ordena_por_recibida_en(repo: Repositorio) -> None:
    t0 = ahora_utc()
    repo.insertar_alerta(
        _alerta(evento_id="ev-2", session_id="s-2", recibida_en=t0 + timedelta(seconds=1))
    )
    repo.insertar_alerta(_alerta(evento_id="ev-1", session_id="s-1", recibida_en=t0))
    assert [a.evento_id for a in repo.listar_alertas()] == ["ev-1", "ev-2"]


# --- endpoint ---------------------------------------------------------------------


def test_get_alertas_expone_la_tabla(cliente: FlaskClient) -> None:
    repositorio: Repositorio = cliente.application.extensions["repositorio"]
    repositorio.insertar_alerta(_alerta())
    ahora = ahora_utc()
    repositorio.marcar_alerta_contenida("ev-1", ahora, ahora)

    respuesta = cliente.get("/v1/alertas")

    assert respuesta.status_code == 200
    cuerpo = respuesta.get_json()
    assert cuerpo["total"] == 1
    assert cuerpo["alertas"][0]["session_id"] == "s-1"
    assert cuerpo["alertas"][0]["motivo"] == "OTP_FALLIDO"
    assert cuerpo["alertas"][0]["revocada_en"] is not None
