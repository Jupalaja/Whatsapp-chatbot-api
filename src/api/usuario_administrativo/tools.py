from typing import Optional


def es_consulta_retefuente(es_retefuente: bool) -> bool:
    """Llama a esta función con `es_retefuente=True` si la consulta tiene que ver con solicitud de certificados de retefuente (Retención en la fuente)."""
    return es_retefuente


def es_consulta_certificado_laboral(es_certificado_laboral: bool) -> bool:
    """Llama a esta función con `es_certificado_laboral=True` si la consulta tiene que ver con solicitud de certificados laborales."""
    return es_certificado_laboral


def obtener_informacion_administrativo(
    nit_cedula: Optional[str] = None, nombre: Optional[str] = None
):
    """
    Se debe llamar a esta función para guardar el NIT/Cédula y el nombre del usuario.
    El modelo debe preguntar por esta información después de haber obtenido el tipo de necesidad.
    """
    return {k: v for k, v in locals().items() if v is not None}
