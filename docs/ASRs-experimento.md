# ASRs del experimento

ASRs seleccionados del backlog inicial (`ASR.md`) para el experimento de
arquitectura: detección y enmascaramiento de un cálculo erróneo de prima en el
motor de cotización.

---

| ASR | Act. | Nombre | Fuente | Estímulo | Modo de operación | Artefacto | Respuesta | Medida |
|:---:|:---:|---|---|---|---|---|---|---|
| **ASR-11** | DET | Detección de un cálculo erróneo de prima | Director comercial | El motor de cotización produce un valor de prima inconsistente con las reglas actuariales o fuera del rango válido | Operación normal en horario pico de cotización | Sistema | El sistema identifica que el resultado es erróneo **antes** de entregarlo al canal que lo solicitó |**≥ 99 %** de los cálculos erróneos inyectados detectados|
| **ASR-12** | ENM | Enmascaramiento del cálculo erróneo de prima | Cliente asegurado | Solicita una cotización mientras uno de los componentes de cálculo está produciendo resultados incorrectos | Operación normal con falla activa en un componente de cálculo | Sistema | El sistema resuelve cuál es el valor correcto y responde con él, sin exponer el error ni interrumpir el journey | retardo total añadido **≤ 300 ms** sobre el p95 del journey|
