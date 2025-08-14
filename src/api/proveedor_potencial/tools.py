from typing import Optional


def obtener_tipo_de_servicio(tipo_de_servicio: str) -> str:
    """
    Se debe llamar a esta función cuando se haya recopilado la información sobre el tipo de servicio que ofrece el proveedor.
    Esta función guarda el tipo de servicio.

    Args:
        tipo_de_servicio: El tipo de servicio que ofrece el proveedor.
    """
    return tipo_de_servicio


def obtener_informacion_proveedor(
    nombre_legal: Optional[str] = None, nit: Optional[str] = None
):
    """
    Se debe llamar a esta función para guardar el nombre de la empresa (razón social) y el NIT del proveedor.
    El modelo debe preguntar por esta información después de haber obtenido el tipo de servicio que ofrece el proveedor.
    """
    return {k: v for k, v in locals().items() if v is not None}
