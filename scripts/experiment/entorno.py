"""Configuración del experimento: lectura de `.env` y catálogo de empleados y
pólizas usados por los escenarios (PLAN-IMPLEMENTACION.md §1.4, §2.2, §2.3, §6).

Autocontenido, como cada servicio del monorepo: no importa nada de
`services/*`, solo habla con el sistema por HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RUTA_ENV = RAIZ / ".env"

PASSWORD = "solventa"


def leer_env(ruta: Path = RUTA_ENV) -> dict[str, str]:
    """Parseo simple `CLAVE=VALOR`: ignora comentarios y líneas vacías, y solo
    separa por el primer `=` para que un valor con `=` no se trunque."""
    if not ruta.is_file():
        raise RuntimeError(f"falta {ruta}: copiar desde example.env")
    variables: dict[str, str] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        despojada = linea.strip()
        if not despojada or despojada.startswith("#"):
            continue
        clave, separador, valor = despojada.partition("=")
        if not separador:
            continue
        variables[clave.strip()] = valor.strip()
    return variables


@dataclass(frozen=True, slots=True)
class Entorno:
    puerto_gateway: int
    puerto_autenticacion: int
    puerto_validacion: int
    periodo_auditoria_s: int

    @property
    def url_gateway(self) -> str:
        return f"http://localhost:{self.puerto_gateway}"

    @property
    def url_autenticacion(self) -> str:
        return f"http://localhost:{self.puerto_autenticacion}"

    @property
    def url_validacion(self) -> str:
        return f"http://localhost:{self.puerto_validacion}"


def desde_env(variables: dict[str, str] | None = None) -> Entorno:
    datos = variables if variables is not None else leer_env()
    return Entorno(
        puerto_gateway=int(datos.get("PUERTO_GATEWAY", "8000")),
        puerto_autenticacion=int(datos.get("PUERTO_AUTENTICACION", "8001")),
        puerto_validacion=int(datos.get("PUERTO_VALIDACION", "8002")),
        periodo_auditoria_s=int(datos.get("PERIODO_AUDITORIA_S", "5")),
    )


@dataclass(frozen=True, slots=True)
class Empleado:
    employee_id: str
    usuario: str


def _asesor_norte(n: int) -> Empleado:
    return Empleado(employee_id=f"E-ASN-{n:02d}", usuario=f"asesor.norte.{n:02d}")


def _asesor_mixto(n: int) -> Empleado:
    return Empleado(employee_id=f"E-ASM-{n:02d}", usuario=f"asesor.mixto.{n:02d}")


#: Empleados de §2.2, asignados uno a uno a cada papel del experimento: ningún
#: empleado se reutiliza entre escenarios dentro de la misma corrida, porque
#: uno revocado o bloqueado no se puede reutilizar.
SUPERVISOR = Empleado(employee_id="E-SUP-01", usuario="supervisor.01")
ATACANTE_ASR23 = _asesor_norte(1)
LEGITIMO_ASR23 = _asesor_norte(2)
ATACANTE_ASR31_SECUENCIAL = _asesor_norte(3)
LEGITIMO_INUSUAL_ASR31 = _asesor_mixto(1)
POOL_RAFAGA_ASR31: tuple[Empleado, ...] = tuple(_asesor_norte(n) for n in range(4, 9))
POOL_HABITUAL: tuple[Empleado, ...] = (_asesor_norte(9), _asesor_norte(10), SUPERVISOR)

POLIZA_ATACANTE_ASR23 = "POL-NOR-001"
POLIZA_LEGITIMO_ASR23 = "POL-NOR-002"
POLIZA_SUR_SECUENCIAL = "POL-SUR-001"
POLIZA_CENTRO_INUSUAL = "POL-CEN-001"
POLIZA_NORTE_HABITUAL = "POL-NOR-011"
POLIZAS_SUR_RAFAGA: tuple[str, ...] = tuple(f"POL-SUR-{n:03d}" for n in range(1, 21))
