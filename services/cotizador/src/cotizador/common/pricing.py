"""Cálculo de la prima y reglas de validez del resultado.

Determinismo, en el orden en que importa:

1. Todo el dinero se maneja con `Decimal`, nunca `float`.
2. Un único redondeo explícito al final, `ROUND_HALF_UP` a dos decimales. Los
   pasos intermedios no se redondean.
3. Las tablas son constantes versionadas (`tarifario.py`).
4. No hay entradas implícitas: `fecha_calculo` se recibe, no se consulta al
   reloj; no hay aleatoriedad.
5. El orden de las operaciones lo fija la fórmula, no la iteración sobre un
   diccionario.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from cotizador.common import tarifario as tarifario_mod
from cotizador.common.contracts import (
    EDAD_MAX,
    EDAD_MIN,
    VIGENCIA_DIAS,
    Explicacion,
    Factores,
    ResultadoCotizacion,
    SolicitudCotizacion,
)
from cotizador.common.errors import ErrorValidacion

CENTAVO = Decimal("0.01")

# Cotas del cociente prima_mensual / suma_asegurada. Fuera de ellas el resultado
# es estructuralmente imposible, sin necesidad de comparar con otras réplicas:
# es la vía de detección que funciona incluso con una sola respuesta.
RATIO_MIN = Decimal("0.00005")
RATIO_MAX = Decimal("0.02")


@dataclass(frozen=True, slots=True)
class Violacion:
    """Incumplimiento de una regla de validez del resultado."""

    regla: str
    detalle: str


def redondear(valor: Decimal) -> Decimal:
    """Único punto de redondeo del sistema."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def edad_cumplida(fecha_nacimiento: date, fecha_calculo: date) -> int:
    """Años cumplidos, sin aproximaciones por días ni divisiones por 365.25."""
    años = fecha_calculo.year - fecha_nacimiento.year
    if (fecha_calculo.month, fecha_calculo.day) < (
        fecha_nacimiento.month,
        fecha_nacimiento.day,
    ):
        años -= 1
    return años


def calcular(
    solicitud: SolicitudCotizacion,
    fecha_calculo: date,
    version: str = tarifario_mod.VERSION_VIGENTE,
) -> ResultadoCotizacion:
    """Aplica la fórmula del plan (§2.3) y devuelve el resultado con su explicación."""
    return calcular_con_tabla(solicitud, fecha_calculo, tarifario_mod.obtener(version))


def calcular_con_tabla(
    solicitud: SolicitudCotizacion,
    fecha_calculo: date,
    tabla: tarifario_mod.Tarifario,
) -> ResultadoCotizacion:
    """Misma fórmula, con la tabla ya resuelta.

    Existe para que la inyección de fallos del cotizador pueda corromper una
    tabla y reutilizar este cálculo, en lugar de duplicar la fórmula. Dos copias
    de la fórmula divergirían por mantenimiento y el experimento mediría el bug
    equivocado.
    """
    edad = edad_cumplida(solicitud.asegurado.fecha_nacimiento, fecha_calculo)
    if not EDAD_MIN <= edad <= EDAD_MAX:
        raise ErrorValidacion(
            "asegurado.fecha_nacimiento",
            f"produce una edad de {edad} años; el rango asegurable es {EDAD_MIN}-{EDAD_MAX}",
        )

    tasa = tabla.tasa_base_mil(edad)
    f_fumador = tabla.factores_fumador[solicitud.asegurado.fumador]
    f_clase = tabla.factor_clase_ocupacional(solicitud.asegurado.clase_ocupacional)
    f_plazo = tabla.factor_plazo(solicitud.plazo_meses)
    f_canal = tabla.factores_canal[solicitud.canal]

    prima_pura = (solicitud.suma_asegurada / 1000) * tasa * f_fumador * f_clase * f_plazo
    prima_comercial = prima_pura * f_canal * (1 + tabla.gasto_administrativo) * (1 + tabla.margen)

    prima_mensual = redondear(prima_comercial)
    prima_anual = redondear(prima_mensual * 12)

    return ResultadoCotizacion(
        moneda=solicitud.moneda,
        suma_asegurada=solicitud.suma_asegurada,
        prima_mensual=prima_mensual,
        prima_anual=prima_anual,
        plazo_meses=solicitud.plazo_meses,
        vigencia_dias=VIGENCIA_DIAS,
        tarifario_version=tabla.version,
        explicacion=Explicacion(
            edad_calculada=edad,
            tasa_base_mil=tasa,
            factores=Factores(
                fumador=f_fumador,
                clase_ocupacional=f_clase,
                plazo=f_plazo,
                canal=f_canal,
            ),
            gasto_administrativo=tabla.gasto_administrativo,
            margen=tabla.margen,
        ),
    )


def validar(
    resultado: ResultadoCotizacion,
    solicitud: SolicitudCotizacion,
    tarifario_esperado: str = tarifario_mod.VERSION_VIGENTE,
) -> list[Violacion]:
    """Reglas de validez del plan (§2.4).

    Devuelve la lista de incumplimientos; vacía significa resultado válido. No
    lanza excepciones: Votación necesita descartar réplicas una a una, no abortar.
    """
    violaciones: list[Violacion] = []

    if resultado.prima_mensual <= 0:
        violaciones.append(Violacion("prima_positiva", f"prima_mensual={resultado.prima_mensual}"))

    if solicitud.suma_asegurada > 0:
        ratio = resultado.prima_mensual / solicitud.suma_asegurada
        if not RATIO_MIN <= ratio <= RATIO_MAX:
            violaciones.append(
                Violacion(
                    "ratio_prima_suma",
                    f"ratio={ratio:.8f} fuera de [{RATIO_MIN}, {RATIO_MAX}]",
                )
            )

    anual_esperada = redondear(resultado.prima_mensual * 12)
    if resultado.prima_anual != anual_esperada:
        violaciones.append(
            Violacion(
                "coherencia_anual",
                f"prima_anual={resultado.prima_anual}, esperada {anual_esperada}",
            )
        )

    if resultado.tarifario_version != tarifario_esperado:
        violaciones.append(
            Violacion(
                "tarifario_vigente",
                f"usó {resultado.tarifario_version}, se esperaba {tarifario_esperado}",
            )
        )

    return violaciones
