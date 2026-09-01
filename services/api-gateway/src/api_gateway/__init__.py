"""API Gateway: única puerta de entrada del sistema.

Enruta hacia Votación, identifica al socio, genera el correlation_id del
journey y garantiza que el socio no vea nunca los detalles internos del
consenso.
"""
