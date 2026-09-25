import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from auditor.config import Config  # noqa: E402
from auditor.repositorio import Repositorio  # noqa: E402


def configuracion(tmp_path: Path, **cambios: object) -> Config:
    base: dict[str, object] = {
        "redis_url": "redis://localhost:6379/0",
        "stream_auditoria": "auditoria",
        "url_validacion": "http://validacion:8000",
        "periodo_auditoria_s": 5.0,
        "lote": 100,
        "timeout_http_ms": 2000,
        "ruta_db": tmp_path / "auditor.db",
        "grupo": "auditor",
        "consumidor": "auditor-test",
        "log_level": "WARNING",
    }
    base.update(cambios)
    return Config(**base)  # type: ignore[arg-type]


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return configuracion(tmp_path)


@pytest.fixture
def repositorio(config: Config) -> Repositorio:
    repo = Repositorio(config.ruta_db)
    repo.inicializar()
    return repo
