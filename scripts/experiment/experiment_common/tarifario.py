"""Tablas actuariales versionadas.

Son constantes en código, no consultas a base de datos ni a servicios externos.
Esa es la condición que hace determinista el cálculo: dos réplicas sanas con la
misma versión de tarifario producen resultados idénticos bit a bit.

Se mantienen dos versiones vivas a propósito: `2026.02` es la vigente y
`2025.11` es la anterior, que usa el modo de fallo `rate_table_stale` para
simular una réplica que quedó con la tabla desactualizada.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from experiment_common.contracts import Canal
from experiment_common.errors import ErrorValidacion, TarifarioDesconocido

VERSION_VIGENTE = "2026.02"
VERSION_ANTERIOR = "2025.11"

# Tramo de edad -> tasa mensual por mil de suma asegurada.
type TramoEdad = tuple[int, int, Decimal]


@dataclass(frozen=True, slots=True)
class Tarifario:
    version: str
    tasas: tuple[TramoEdad, ...]
    factores_fumador: Mapping[bool, Decimal]
    factores_clase_ocupacional: Mapping[int, Decimal]
    factores_plazo: tuple[tuple[int, Decimal], ...]
    factores_canal: Mapping[Canal, Decimal]
    gasto_administrativo: Decimal
    margen: Decimal

    def tasa_base_mil(self, edad: int) -> Decimal:
        for desde, hasta, tasa in self.tasas:
            if desde <= edad <= hasta:
                return tasa
        raise ErrorValidacion(
            "asegurado.fecha_nacimiento",
            f"produce una edad de {edad} años, fuera del rango asegurable",
        )

    def factor_plazo(self, plazo_meses: int) -> Decimal:
        for tope, factor in self.factores_plazo:
            if plazo_meses <= tope:
                return factor
        # El último tramo es abierto por construcción.
        return self.factores_plazo[-1][1]

    def factor_clase_ocupacional(self, clase: int) -> Decimal:
        try:
            return self.factores_clase_ocupacional[clase]
        except KeyError as err:
            raise ErrorValidacion(
                "asegurado.clase_ocupacional", "no tiene factor en este tarifario"
            ) from err


_2026_02 = Tarifario(
    version=VERSION_VIGENTE,
    tasas=(
        (18, 29, Decimal("0.18")),
        (30, 39, Decimal("0.26")),
        (40, 49, Decimal("0.45")),
        (50, 59, Decimal("0.92")),
        (60, 69, Decimal("1.85")),
        (70, 75, Decimal("3.40")),
    ),
    factores_fumador={False: Decimal("1.00"), True: Decimal("1.45")},
    factores_clase_ocupacional={
        1: Decimal("1.00"),
        2: Decimal("1.12"),
        3: Decimal("1.35"),
        4: Decimal("1.80"),
    },
    factores_plazo=(
        (120, Decimal("1.00")),
        (240, Decimal("1.08")),
        (360, Decimal("1.15")),
    ),
    factores_canal={
        Canal.BANCO_ALIADO: Decimal("0.95"),
        Canal.RETAIL: Decimal("1.00"),
        Canal.DIRECTO: Decimal("0.97"),
    },
    gasto_administrativo=Decimal("0.12"),
    margen=Decimal("0.08"),
)

# Tabla anterior: tasas y gasto ligeramente menores. Solo se usa para inyectar
# el fallo `rate_table_stale`; ninguna réplica sana debe seleccionarla.
_2025_11 = Tarifario(
    version=VERSION_ANTERIOR,
    tasas=(
        (18, 29, Decimal("0.17")),
        (30, 39, Decimal("0.24")),
        (40, 49, Decimal("0.42")),
        (50, 59, Decimal("0.88")),
        (60, 69, Decimal("1.78")),
        (70, 75, Decimal("3.25")),
    ),
    factores_fumador=_2026_02.factores_fumador,
    factores_clase_ocupacional=_2026_02.factores_clase_ocupacional,
    factores_plazo=_2026_02.factores_plazo,
    factores_canal=_2026_02.factores_canal,
    gasto_administrativo=Decimal("0.11"),
    margen=Decimal("0.08"),
)

_TARIFARIOS: Mapping[str, Tarifario] = {
    VERSION_VIGENTE: _2026_02,
    VERSION_ANTERIOR: _2025_11,
}


def obtener(version: str) -> Tarifario:
    try:
        return _TARIFARIOS[version]
    except KeyError as err:
        raise TarifarioDesconocido(f"no existe el tarifario {version!r}") from err
