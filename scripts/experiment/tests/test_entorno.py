from pathlib import Path

from entorno import desde_env, leer_env


def test_leer_env_ignora_comentarios_y_lineas_vacias(tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    ruta.write_text(
        "\n".join(
            [
                "# comentario",
                "",
                "STACK=solventa",
                "  PUERTO_GATEWAY=8000  ",
                "",
            ]
        ),
        encoding="utf-8",
    )

    variables = leer_env(ruta)

    assert variables == {"STACK": "solventa", "PUERTO_GATEWAY": "8000"}


def test_leer_env_solo_separa_por_el_primer_igual(tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    ruta.write_text("JWT_SECRET=abc=def=ghi\n", encoding="utf-8")

    variables = leer_env(ruta)

    assert variables["JWT_SECRET"] == "abc=def=ghi"


def test_leer_env_falla_si_no_existe(tmp_path: Path) -> None:
    try:
        leer_env(tmp_path / "no-existe.env")
    except RuntimeError as err:
        assert "no-existe.env" in str(err)
    else:
        raise AssertionError("debía fallar")


def test_desde_env_usa_los_valores_leidos() -> None:
    entorno = desde_env(
        {
            "PUERTO_GATEWAY": "9000",
            "PUERTO_AUTENTICACION": "9001",
            "PUERTO_VALIDACION": "9002",
            "PERIODO_AUDITORIA_S": "7",
        }
    )

    assert entorno.puerto_gateway == 9000
    assert entorno.periodo_auditoria_s == 7
    assert entorno.url_gateway == "http://localhost:9000"
    assert entorno.url_autenticacion == "http://localhost:9001"
    assert entorno.url_validacion == "http://localhost:9002"


def test_desde_env_usa_valores_por_defecto_si_faltan() -> None:
    entorno = desde_env({})

    assert entorno.puerto_gateway == 8000
    assert entorno.puerto_autenticacion == 8001
    assert entorno.puerto_validacion == 8002
    assert entorno.periodo_auditoria_s == 5
