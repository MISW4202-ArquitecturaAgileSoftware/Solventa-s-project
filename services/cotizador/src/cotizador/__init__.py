"""Réplica del cotizador: worker puro que consume solicitudes de la cola.

No expone HTTP. Su única interfaz es la cola: lee de `cot:req` a través de su
propio consumer group y deposita el resultado en `cot:resp:{correlation_id}`.
"""
