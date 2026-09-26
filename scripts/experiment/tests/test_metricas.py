from typing import Any

import metricas


def test_deteccion_otp_fallidos_cien_por_ciento() -> None:
    intentos = [{"session_id": "s1"}, {"session_id": "s2"}]
    alertas = [
        {"session_id": "s1", "motivo": "OTP_FALLIDO"},
        {"session_id": "s2", "motivo": "OTP_FALLIDO"},
        {"session_id": "s3", "motivo": "ALCANCE_NO_AUTORIZADO"},
    ]

    assert metricas.deteccion_otp_fallidos(intentos, alertas) == 1.0


def test_deteccion_otp_fallidos_parcial() -> None:
    intentos = [
        {"session_id": "s1"},
        {"session_id": "s2"},
        {"session_id": "s3"},
        {"session_id": "s4"},
    ]
    alertas = [{"session_id": "s1", "motivo": "OTP_FALLIDO"}]

    assert metricas.deteccion_otp_fallidos(intentos, alertas) == 0.25


def test_deteccion_otp_fallidos_sin_intentos_es_cien_por_ciento() -> None:
    assert metricas.deteccion_otp_fallidos([], []) == 1.0


def test_operaciones_privilegiadas_ejecutadas() -> None:
    assert metricas.operaciones_privilegiadas_ejecutadas({"POL-NOR-001": "PENDIENTE"}) == 0
    assert metricas.operaciones_privilegiadas_ejecutadas({"POL-NOR-001": "APROBADA"}) == 1


def test_segunda_operacion_bloqueada() -> None:
    resultados: list[dict[str, Any]] = [
        {"estado_aprobacion_2": 401, "tipo_error_aprobacion_2": "sesion-revocada"},
        {"estado_aprobacion_2": 401, "tipo_error_aprobacion_2": "sesion-invalida"},
        {"estado_aprobacion_2": 200, "tipo_error_aprobacion_2": None},
    ]

    tasa = metricas.segunda_operacion_bloqueada(
        resultados, "estado_aprobacion_2", "tipo_error_aprobacion_2"
    )

    assert tasa == 1 / 3


def test_percentiles_p50_p95() -> None:
    valores = [float(n) for n in range(1, 101)]

    p50, p95 = metricas.percentiles(valores)

    assert p50 == 50.5
    assert p95 == 95.05


def test_percentiles_con_una_sola_muestra() -> None:
    assert metricas.percentiles([42.0]) == (42.0, 42.0)


def test_percentiles_lista_vacia() -> None:
    assert metricas.percentiles([]) == (0.0, 0.0)


def test_deteccion_alcance_no_autorizado() -> None:
    atacantes = [{"session_id": "a1"}, {"session_id": "a2"}]
    alertas = [{"session_id": "a1", "motivo": "ALCANCE_NO_AUTORIZADO"}]

    assert metricas.deteccion_alcance_no_autorizado(atacantes, alertas) == 0.5


def test_falsos_positivos_cuenta_revocaciones_en_legitimos() -> None:
    legitimos = [{"session_id": "l1"}, {"session_id": "l2"}]
    alertas: list[dict[str, Any]] = [
        {"session_id": "l1", "motivo": "CONSULTA_INUSUAL", "revocada_en": None},
        {
            "session_id": "l2",
            "motivo": "ALCANCE_NO_AUTORIZADO",
            "revocada_en": "2026-09-21T00:00:00Z",
        },
        {"session_id": "otro", "motivo": "OTP_FALLIDO", "revocada_en": "2026-09-21T00:00:00Z"},
    ]

    assert metricas.falsos_positivos(legitimos, alertas) == 1


def test_alerta_consulta_inusual_presente() -> None:
    legitimos = [{"session_id": "l1"}]
    alertas = [{"session_id": "l1", "motivo": "CONSULTA_INUSUAL"}]

    assert metricas.alerta_consulta_inusual_presente(legitimos, alertas) is True
    assert metricas.alerta_consulta_inusual_presente([{"session_id": "otro"}], alertas) is False


def test_ventana_exposicion_ms_por_usuario_desde_jsonl_sintetico() -> None:
    filas = [
        {"usuario": "asesor.norte.04", "t": 0.0, "estado": 200, "tipo": None},
        {"usuario": "asesor.norte.04", "t": 0.1, "estado": 200, "tipo": None},
        {"usuario": "asesor.norte.04", "t": 0.35, "estado": 401, "tipo": "sesion-revocada"},
        {"usuario": "asesor.norte.05", "t": 1.0, "estado": 200, "tipo": None},
        {"usuario": "asesor.norte.05", "t": 1.2, "estado": 200, "tipo": None},
    ]

    ventana = metricas.ventana_exposicion_ms_por_usuario(filas)

    assert ventana["asesor.norte.04"] == 350.0
    assert ventana["asesor.norte.05"] is None


def test_operaciones_asr31_antes_del_cierre_suma_lento_y_rafaga() -> None:
    atacante = {"estado_consulta_1": 200, "estado_consulta_2": 401}
    filas = [
        {"usuario": "asesor.norte.04", "t": 0.0, "estado": 200, "tipo": None},
        {"usuario": "asesor.norte.04", "t": 0.1, "estado": 200, "tipo": None},
        {"usuario": "asesor.norte.04", "t": 0.2, "estado": 401, "tipo": "sesion-revocada"},
    ]

    assert metricas.operaciones_asr31_antes_del_cierre([atacante], filas) == 3
    assert metricas.operaciones_asr31_antes_del_cierre(
        [{"estado_consulta_1": 401, "estado_consulta_2": 401}],
        [{"usuario": "asesor.norte.04", "t": 0.0, "estado": 401, "tipo": "sesion-revocada"}],
    ) == 0


def test_consultas_200_antes_del_401_por_usuario() -> None:
    filas = [
        {"usuario": "asesor.norte.04", "t": 0.2, "estado": 200, "tipo": None},
        {"usuario": "asesor.norte.04", "t": 0.0, "estado": 200, "tipo": None},
        {"usuario": "asesor.norte.04", "t": 0.3, "estado": 401, "tipo": "sesion-revocada"},
        {"usuario": "asesor.norte.04", "t": 0.4, "estado": 401, "tipo": "sesion-revocada"},
    ]

    conteo = metricas.consultas_200_antes_del_401_por_usuario(filas)

    assert conteo["asesor.norte.04"] == 2


def test_alertas_registradas_duplicadas_cuenta_pares_repetidos() -> None:
    alertas = [
        {"session_id": "s1", "motivo": "OTP_FALLIDO"},
        {"session_id": "s1", "motivo": "ALCANCE_NO_AUTORIZADO"},
        {"session_id": "s2", "motivo": "ALCANCE_NO_AUTORIZADO"},
    ]
    assert metricas.alertas_registradas_duplicadas(alertas) == 0
    assert metricas.alertas_registradas_duplicadas([*alertas, alertas[0]]) == 1


def test_intervalo_medio_entre_consultas_promedia_los_huecos_por_usuario() -> None:
    filas = [
        {"usuario": "a", "t": 0.0, "estado": 200, "tipo": None},
        {"usuario": "a", "t": 0.1, "estado": 200, "tipo": None},
        {"usuario": "a", "t": 0.3, "estado": 401, "tipo": "sesion-revocada"},
        {"usuario": "b", "t": 0.0, "estado": 200, "tipo": None},
    ]
    assert metricas.intervalo_medio_entre_consultas_ms(filas) == 150.0
    assert metricas.intervalo_medio_entre_consultas_ms([]) == 0.0
