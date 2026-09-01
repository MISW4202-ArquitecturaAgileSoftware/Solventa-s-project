"""Votación: detecta (ASR-11) y enmascara (ASR-12) un cálculo erróneo de prima.

Difunde una solicitud a las tres réplicas del cotizador a través de la cola,
compara sus resultados y responde con el valor de consenso, registrando la
divergencia sin exponerla al cliente.
"""
