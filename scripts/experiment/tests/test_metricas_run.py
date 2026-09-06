"""El JSON de la corrida conserva el contrato que consume reporte.py."""

from locust_carga.metricas_run import MetricasCorrida


def test_modo_none_no_cuenta_fallos_efectivos() -> None:
    metricas = MetricasCorrida("baseline", "none")
    metricas.registrar(
        indice=0,
        estado_http=200,
        latencia_ms=9.09,
        estado_cotizacion="COTIZADO",
        prima_entregada="90348.41",
        prima_esperada="90348.41",
        erronea=False,
    )
    resumen = metricas.resumen()
    assert resumen["etiqueta"] == "baseline"
    assert resumen["enviadas"] == 1
    assert resumen["alcanzaron_votacion"] == 1
    assert resumen["fallos_efectivos"] == 0
    assert resumen["primas_erroneas"] == 0
    assert resumen["latencia_ms"]["p95"] == 9.09
    assert resumen["por_estado_cotizacion"] == {"COTIZADO": 1}


def test_fallo_efectivo_solo_si_alcanzo_votacion() -> None:
    metricas = MetricasCorrida("deteccion-premium_offset", "premium_offset")
    metricas.registrar(
        indice=0,
        estado_http=200,
        latencia_ms=10.0,
        estado_cotizacion="COTIZADO",
        fallo_efectivo=True,
    )
    metricas.registrar(indice=1, estado_http=0, latencia_ms=5.0, fallo_efectivo=True)
    resumen = metricas.resumen()
    assert resumen["enviadas"] == 2
    assert resumen["alcanzaron_votacion"] == 1
    assert resumen["fallos_efectivos"] == 1
    assert resumen["latencia_ms"]["n"] == 1


def test_factor_skip_clase_1_no_suma_denominador() -> None:
    metricas = MetricasCorrida("deteccion-factor_skip", "factor_skip")
    metricas.registrar(indice=0, estado_http=200, latencia_ms=8.0, fallo_efectivo=False)
    metricas.registrar(indice=1, estado_http=200, latencia_ms=8.0, fallo_efectivo=True)
    assert metricas.resumen()["fallos_efectivos"] == 1
    assert metricas.resumen()["alcanzaron_votacion"] == 2


def test_guarda_hasta_cinco_muestras_erroneas() -> None:
    metricas = MetricasCorrida("enmascaramiento", "premium_offset")
    for indice in range(6):
        metricas.registrar(
            indice=indice,
            estado_http=200,
            latencia_ms=1.0,
            prima_entregada="1.00",
            prima_esperada="90348.41",
            erronea=True,
        )
    resumen = metricas.resumen()
    assert resumen["primas_erroneas"] == 6
    assert len(resumen["muestras_erroneas"]) == 5
    assert resumen["muestras_erroneas"][0]["indice"] == 0
