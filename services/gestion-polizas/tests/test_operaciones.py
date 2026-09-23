from datetime import UTC, datetime
from pathlib import Path

from gestion_polizas.contracts import Actor, CodigoRespuesta, EstadoRespuesta, SobreOperacion
from gestion_polizas.operaciones import ejecutar
from gestion_polizas.repositorio import Repositorio
from gestion_polizas.seed import sembrar

AHORA = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)


def _repositorio(tmp_path: Path) -> Repositorio:
    repositorio = Repositorio(tmp_path / "polizas.db")
    repositorio.inicializar()
    sembrar(repositorio)
    return repositorio


def _sobre(operacion: str, parametros: dict[str, object], rol: str = "asesor") -> SobreOperacion:
    return SobreOperacion(
        correlation_id="c1",
        tipo="operacion.solicitada",
        version="1",
        emitido_en="2026-09-21T00:00:00.000Z",
        actor=Actor(employee_id="E-ASN-01", session_id="s1", rol=rol),
        operacion=operacion,
        parametros=parametros,
    )


def test_consultar_poliza_existente(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    sobre = _sobre("consultar_poliza", {"poliza_id": "POL-NOR-001"})

    resultado = ejecutar(repositorio, sobre, AHORA)

    assert resultado.estado is EstadoRespuesta.OK
    assert resultado.codigo is CodigoRespuesta.OK
    assert resultado.resultado is not None
    assert resultado.resultado["poliza_id"] == "POL-NOR-001"
    assert resultado.resultado["estado"] == "PENDIENTE"
    assert resultado.region == "norte"
    assert resultado.cliente_id == "CLI-NOR-001"


def test_consultar_poliza_inexistente(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    sobre = _sobre("consultar_poliza", {"poliza_id": "POL-NOR-999"})

    resultado = ejecutar(repositorio, sobre, AHORA)

    assert resultado.estado is EstadoRespuesta.ERROR
    assert resultado.codigo is CodigoRespuesta.NO_ENCONTRADA
    assert resultado.resultado is None
    assert resultado.region is None
    assert resultado.cliente_id is None
    assert resultado.poliza_id == "POL-NOR-999"


def test_aprobar_poliza_pendiente(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    sobre = _sobre("aprobar_poliza", {"poliza_id": "POL-NOR-001"}, rol="supervisor")

    resultado = ejecutar(repositorio, sobre, AHORA)

    assert resultado.estado is EstadoRespuesta.OK
    assert resultado.codigo is CodigoRespuesta.OK
    assert resultado.resultado == {
        "poliza_id": "POL-NOR-001",
        "estado": "APROBADA",
        "aprobada_por": "E-ASN-01",
        "aprobada_en": "2026-09-21T14:00:00Z",
    }

    consulta = ejecutar(
        repositorio, _sobre("consultar_poliza", {"poliza_id": "POL-NOR-001"}), AHORA
    )
    assert consulta.resultado is not None
    assert consulta.resultado["estado"] == "APROBADA"


def test_aprobar_poliza_ya_emitida_es_estado_invalido(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    sobre = _sobre("aprobar_poliza", {"poliza_id": "POL-NOR-011"}, rol="supervisor")

    resultado = ejecutar(repositorio, sobre, AHORA)

    assert resultado.codigo is CodigoRespuesta.ESTADO_INVALIDO
    assert resultado.resultado is None
    assert resultado.region == "norte"
    assert resultado.cliente_id == "CLI-NOR-011"


def test_aprobar_poliza_inexistente(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    sobre = _sobre("aprobar_poliza", {"poliza_id": "POL-NOR-999"}, rol="supervisor")

    resultado = ejecutar(repositorio, sobre, AHORA)

    assert resultado.codigo is CodigoRespuesta.NO_ENCONTRADA
    assert resultado.region is None
    assert resultado.cliente_id is None


def test_operacion_desconocida_es_validacion(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    sobre = _sobre("cotizar", {"poliza_id": "POL-NOR-001"})

    resultado = ejecutar(repositorio, sobre, AHORA)

    assert resultado.estado is EstadoRespuesta.ERROR
    assert resultado.codigo is CodigoRespuesta.VALIDACION


def test_parametros_invalidos_es_validacion(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    sobre = _sobre("consultar_poliza", {})

    resultado = ejecutar(repositorio, sobre, AHORA)

    assert resultado.estado is EstadoRespuesta.ERROR
    assert resultado.codigo is CodigoRespuesta.VALIDACION
    assert resultado.poliza_id is None
