# Manual breve del experimento

Ejecuta todos los comandos desde la carpeta raíz del proyecto (donde está
`README.md`).

**1. Preparar el equipo — solo la primera vez**

Necesitas Python 3.14, Docker encendido y Docker Compose v2 con soporte de
`include:`. La primera preparación requiere conexión a internet para descargar
dependencias e imágenes.

```bash
bash scripts/bootstrap.sh
docker compose build
```

El primer comando crea `.env` y `.venv` si no existen e instala las dependencias.
El segundo construye las imágenes. Si ya preparaste el proyecto, pasa al punto 2.

**2. Elegir la ejecución**

Prueba rápida: una repetición con periodo de auditoría de 2 segundos
(aproximadamente 1 minuto, según el equipo y el arranque de Docker):

```bash
bash scripts/experiment/correr.sh --rapido
```

Experimento completo: periodos de 2, 5 y 10 segundos, con 5 repeticiones por
periodo; 15 repeticiones en total (aproximadamente 20 minutos):

```bash
bash scripts/experiment/correr.sh
```

Ejecuta solo uno de estos comandos a la vez. Cada repetición reinicia los
servicios y borra sus volúmenes para empezar con datos de prueba limpios.
Las carpetas de evidencias de ejecuciones anteriores se conservan.

**3. Ver el avance**

El navegador se abre automáticamente en <http://127.0.0.1:8090>.
Si no se abre, entra manualmente a esa dirección. Si cambiaste `PUERTO_TABLERO`,
usa la URL que muestra la consola.

El tablero se actualiza cada segundo: muestra la repetición, el paso actual,
los criterios evaluados y las respuestas de los atacantes durante la ráfaga.
Mantén abierta la terminal hasta que termine. Al finalizar aparecen los mensajes
`informe escrito en ...` y `evidencia guardada en ...` con las rutas exactas.

**4. Encontrar las evidencias**

Todas las rutas siguientes parten de la raíz del proyecto:

| Ruta o archivo | Qué contiene |
|---|---|
| `docs/RESULTADOS-EXPERIMENTO.md` | Informe final con resultados y análisis; se genera al completar el experimento. |
| `scripts/experiment/resultados/<fecha-hora>/` | Evidencias de una ejecución. Ejemplo de nombre: `20260926T142558Z` (fecha y hora UTC). |
| Dentro de esa carpeta: `p2-r1.json` | Resultados de escenarios, alertas y estados de pólizas para el periodo de 2 segundos, repetición 1. Los demás siguen el mismo patrón. |
| `p2-r1-locust.jsonl` | Respuestas registradas por los atacantes durante la ráfaga. |
| `p2-r1-locust_*.csv` | Estadísticas, fallos y excepciones exportados por Locust. |
| `estado.json` | Avance de esa ejecución y estado de sus pasos. |
| `meta.json` | Fecha, periodos, repeticiones y versiones de imágenes; se escribe al finalizar las repeticiones. |
| `scripts/experiment/resultados/actual.json` | Indica la carpeta de la última ejecución iniciada; no contiene todo el resultado. |

Para entregar o conservar una prueba, guarda **su carpeta completa de evidencias
y una copia del informe Markdown**. El informe se sobrescribe con cada ejecución
que llega a generarlo, incluida la rápida. Si la prueba se interrumpe, pueden quedar
evidencias parciales y el informe puede seguir siendo el de una ejecución anterior.

**5. Consultar el tablero después de terminar**

El servidor del tablero se cierra al terminar el experimento. Para consultar la
última ejecución guardada, ejecuta:

```bash
.venv/bin/python scripts/experiment/tablero.py
```

En este modo abre manualmente <http://127.0.0.1:8090>. No vuelve a ejecutar la
prueba. Usa `Ctrl+C` para cerrar este visor.

Para detener los servicios Docker cuando hayas terminado:

```bash
bash scripts/down.sh
```

Las evidencias guardadas en el proyecto permanecen disponibles.
