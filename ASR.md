# Architecture Significant Requirements (ASR)

## Solventa – Aseguradora Digital

Este documento define los Architecture Significant Requirements (ASR) de la plataforma Solventa. Cada ASR describe un escenario de calidad medible que influye directamente en las decisiones arquitectónicas del sistema.

---

## ASR-01 · Latencia en cotización embebida

**Historia:**  
Como socio de distribución (banco, aerolínea, retailer), quiero recibir el precio de una cotización en tiempo real dentro de mi propio flujo de compra, para no perder al cliente por demoras que rompan la experiencia embebida.

- **Fuente:** Socio de distribución vía API.
- **Estímulo:** Solicitud de cotización en horario pico.
- **Artefacto:** Servicio de cotización (Rating).
- **Ambiente:** Operación normal, carga pico.
- **Respuesta:** Cálculo combinando reglas actuariales, riesgo y señales de Open Finance.
- **Medida:** p95 ≤ 250 ms, p99 ≤ 500 ms extremo a extremo.
- **Atributo:** Latencia.
- **Prioridad:** Alta (afecta conversión, meta ≥25%).
- **Riesgo arquitectónico:** Alto.

---

## ASR-02 · Perfilamiento en línea con Open Data/Open Finance

**Historia:**  
Como cliente que está originando un crédito hipotecario, quiero recibir una oferta de seguro de vida hipotecario personalizada dentro del mismo flujo de crédito, para no tener que iniciar un trámite separado.

- **Fuente:** Cliente (a través del flujo de originación del banco aliado).
- **Estímulo:** Se recibe el consentimiento del cliente y se dispara el perfilamiento.
- **Artefacto:** Motor de perfilamiento / personalización.
- **Ambiente:** Operación normal, múltiples fuentes externas.
- **Respuesta:** Perfil de riesgo individualizado + precio explicable.
- **Medida:** p95 ≤ 400 ms, p99 ≤ 800 ms.
- **Atributo:** Latencia (tensiona también Seguridad y Explicabilidad).
- **Prioridad:** Alta (caso insignia).
- **Riesgo arquitectónico:** Muy alto.

---

## ASR-03 · Degradación elegante ante dependencia externa lenta

**Historia:**  
Como arquitecto del sistema, quiero que cada llamada a un proveedor externo tenga un presupuesto de latencia y una estrategia de degradación, para que una falla de un tercero no tumbe el journey completo de venta.

- **Fuente:** Proveedor externo de datos (KYC, Open Finance).
- **Estímulo:** El proveedor supera 700 ms o falla.
- **Artefacto:** Capa de integración / orquestador de dependencias externas.
- **Ambiente:** Degradación parcial del ecosistema.
- **Respuesta:** Timeout duro, fallback a caché o valor por defecto, circuit breaker.
- **Medida:** No se excede el presupuesto total del journey; disponibilidad del journey ≥ 99,9% aun con la dependencia caída.
- **Atributo:** Latencia + Disponibilidad.
- **Prioridad:** Alta.
- **Riesgo arquitectónico:** Alto (afecta múltiples journeys).

---

## ASR-04 · Escalamiento ante campaña masiva de un socio

**Historia:**  
Como CTO, quiero que la plataforma escale automáticamente cuando un socio lance una promoción masiva, para no perder ventas ni degradar la experiencia de otros socios.

- **Fuente:** Tráfico entrante de un socio embebido.
- **Estímulo:** El tráfico de cotización crece 100× (de 500 a 50.000 cotizaciones/min).
- **Artefacto:** Servicio de cotización y su infraestructura de autoescalado.
- **Ambiente:** Pico de campaña, horario específico.
- **Respuesta:** Autoescalado que conserva el p95 de latencia sin intervención manual.
- **Medida:** Autoescalado ≤ 60 s; p95 se mantiene dentro de ASR-01.
- **Atributo:** Escalabilidad.
- **Prioridad:** Alta.
- **Riesgo arquitectónico:** Alto.

---

## ASR-05 · Absorción de eventos paramétricos masivos

**Historia:**  
Como cliente asegurado con una póliza paramétrica (vuelo/clima), quiero que mi pago se procese automáticamente incluso cuando miles de clientes son afectados por el mismo evento, para recibir la indemnización sin retrasos.

- **Fuente:** Evento externo (clima, retraso de vuelos).
- **Estímulo:** Un evento climático o de vuelos dispara ≥1.000.000 de pólizas paramétricas simultáneamente.
- **Artefacto:** Pipeline de eventos / motor de siniestros paramétricos.
- **Ambiente:** Pico de eventos, ventana de 10 minutos.
- **Respuesta:** Absorción con contrapresión (backpressure), sin pérdida de eventos, pago automático.
- **Medida:** ≥1.000.000 eventos procesados en 10 min sin pérdida.
- **Atributo:** Escalabilidad (tensiona Disponibilidad e integridad transaccional).
- **Prioridad:** Media-Alta.
- **Riesgo arquitectónico:** Alto (arquitectura orientada a eventos casi obligatoria).

---

## ASR-06 · Disponibilidad 24/7 de los journeys críticos

**Historia:**  
Como cliente asegurado, quiero poder cotizar, comprar y reportar siniestros en cualquier momento del día, para confiar en que Solventa está disponible cuando la necesito.

- **Fuente:** Operación normal del negocio.
- **Estímulo:** Uso continuo 24/7 de venta y siniestros.
- **Artefacto:** Servicios de venta y de siniestros.
- **Ambiente:** Operación normal.
- **Respuesta:** El sistema permanece disponible sin interrupciones perceptibles.
- **Medida:** Disponibilidad ≥ 99,97% mensual (≈13 min de indisponibilidad/mes).
- **Atributo:** Disponibilidad.
- **Prioridad:** Alta.
- **Riesgo arquitectónico:** Medio.

---

## ASR-07 · Integridad y disponibilidad del recaudo/pago de indemnizaciones

**Historia:**  
Como CFO, quiero que ninguna transacción de cobro o pago se pierda ni se duplique aunque haya fallas transitorias, para proteger la integridad financiera de la aseguradora.

- **Fuente:** Flujo de cobro de primas / pago de indemnizaciones.
- **Estímulo:** Falla transitoria de red o reintento de una transacción de dinero.
- **Artefacto:** Servicio de cobros y pagos.
- **Ambiente:** Operación normal o con fallas parciales.
- **Respuesta:** Procesamiento idempotente, sin pérdida ni duplicación de transacciones confirmadas.
- **Medida:** Disponibilidad ≥ 99,99%; cero pérdida de transacciones confirmadas.
- **Atributo:** Disponibilidad + Seguridad transaccional.
- **Prioridad:** Muy alta (dinero real).
- **Riesgo arquitectónico:** Muy alto.

---

## ASR-08 · Continuidad ante caída de zona/región de nube

**Historia:**  
Como responsable de operaciones (SRE), quiero que el sistema se recupere automáticamente si falla una zona o una región completa de la nube, para garantizar continuidad del negocio ante desastres de infraestructura.

- **Fuente:** Proveedor de nube.
- **Estímulo:** Falla de una zona de disponibilidad / pérdida de una región completa.
- **Artefacto:** Infraestructura y datos replicados multi-zona/multi-región.
- **Ambiente:** Falla de infraestructura.
- **Respuesta:** Failover automático sin pérdida de transacciones confirmadas.
- **Medida:** Zona: RTO ≤10 min, RPO ≤30 s. Región: RTO ≤5 min, sin pérdida de transacciones confirmadas.
- **Atributo:** Disponibilidad.
- **Prioridad:** Alta.
- **Riesgo arquitectónico:** Alto (impacta decisión de despliegue multi-región).

---

## ASR-09 · Protección de datos personales y financieros sensibles

**Historia:**  
Como CISO, quiero que todos los datos personales y financieros estén cifrados y tokenizados en tránsito y en reposo, para cumplir la regulación y proteger la confianza del cliente.

- **Fuente:** Almacenamiento y procesamiento de datos del cliente.
- **Estímulo:** Se almacenan/transmiten datos sensibles (PII, datos financieros, medios de pago).
- **Artefacto:** Capa de persistencia, capa de comunicación, pasarela de pagos.
- **Ambiente:** Operación normal.
- **Respuesta:** Cifrado en tránsito y en reposo; tokenización de PII; cumplimiento PCI-DSS en pagos.
- **Medida:** 100% de datos sensibles cifrados/tokenizados; cero incidentes graves de datos (meta de negocio: retención ≥90%).
- **Atributo:** Seguridad.
- **Prioridad:** Muy alta (regulatoria).
- **Riesgo arquitectónico:** Alto.

---

## ASR-10 · Gestión y revocación de consentimiento de Open Finance

**Historia:**  
Como cliente, quiero poder otorgar o revocar en cualquier momento el acceso a mis datos financieros consentidos, para mantener el control sobre mi información personal.

- **Fuente:** Cliente, a través de la app web o móvil.
- **Estímulo:** El cliente otorga o revoca su consentimiento de acceso a datos de Open Finance.
- **Artefacto:** Servicio de gestión de identidad y consentimiento.
- **Ambiente:** Operación normal.
- **Respuesta:** El consentimiento queda verificable, auditable, y la revocación se propaga a todos los consumidores de ese dato.
- **Medida:** Revocación efectiva en ≤5 min; acceso de mínimo privilegio garantizado.
- **Atributo:** Seguridad.
- **Prioridad:** Alta (obligación de Habeas Data / Ley 1581).
- **Riesgo arquitectónico:** Medio-Alto.

---
