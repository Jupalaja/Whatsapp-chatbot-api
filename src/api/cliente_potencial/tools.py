from src.shared.enums import TipoDeServicio


def inferir_tipo_de_servicio(descripcion_servicio: str) -> str:
    """
    Infiere el tipo de servicio logístico formal a partir de una descripción en lenguaje natural.
    Utiliza esta función para convertir la descripción del servicio del usuario en un valor válido del enumerado TipoDeServicio ANTES de llamar a get_informacion_cliente_potencial.
    Por ejemplo, si un usuario dice 'transporte de maquinaria', esta función podría devolver 'DISTRIBUCION'.

    Args:
        descripcion_servicio: La descripción del servicio proporcionada por el usuario.

    Returns:
        Un valor válido del enumerado TipoDeServicio.
    """
    descripcion_lower = descripcion_servicio.lower()
    if "importacion" in descripcion_lower or "importar" in descripcion_lower:
        return TipoDeServicio.IMPORTACION.value
    if "exportacion" in descripcion_lower or "exportar" in descripcion_lower:
        return TipoDeServicio.EXPORTACION.value
    if "almacenamiento" in descripcion_lower or "guardar" in descripcion_lower:
        return TipoDeServicio.ALMACENAMIENTO.value
    if "itr" in descripcion_lower:
        return TipoDeServicio.ITR.value
    # Default to distribution if it involves moving stuff
    if (
        "distribucion" in descripcion_lower
        or "transporte" in descripcion_lower
        or "mover" in descripcion_lower
    ):
        return TipoDeServicio.DISTRIBUCION.value
    # Fallback if no keywords match. This shouldn't happen often with a good model.
    return TipoDeServicio.DISTRIBUCION.value


def search_nit(nit: str):
    """Busca información de una empresa por su NIT."""
    if nit == "901535329":
        return {
            "cliente": "Elevva Colombia S.A.S.",
            "estado": "PERDIDO_2_ANOS",
            "responsable_comercial": "TEGUA SIERRA DEISSY ROCIO",
            "telefono": "3057797223"
        }
    elif nit == "901534449":
        return {
            "cliente": "Insumos & Ingeniería S.A.S",
            "estado": "PERDIDO",
            "responsable_comercial": "CORTES LEON KEVIN DAVID",
            "telefono": "3146694888"
        }
    else:
        return {
            "cliente": "No encontrado",
            "estado": "No encontrado",
            "responsable_comercial": "No encontrado",
            "telefono": "No encontrado"
        }


def is_persona_natural():
    """Se debe llamar cuando el usuario indica que no es una empresa, por ejemplo si dice 'soy persona natural' o 'no tengo NIT'."""
    return True


def needs_freight_forwarder():
    """Se debe llamar si la persona natural indica que SÍ está interesada en agenciamiento de carga. Usar solo cuando la persona confirma que necesita un 'agente de carga' o que necesita 'agenciamiento de carga' o un 'freight forwarder'."""
    return True


def get_informacion_cliente_potencial(
    nombre_legal: str,
    nombre_persona_contacto: str,
    correo: str,
    telefono: str,
    tipo_de_servicio: str,
    tipo_mercancia: str,
    detalles_mercancia: str,
    ciudad_origen: str,
    ciudad_destino: str,
    promedio_viajes_mensuales: int,
):
    """
    Se debe llamar a esta función SOLO cuando se haya recopilado TODA la información
    requerida del cliente. Esta función guarda los detalles del cliente potencial.
    La información requerida es: nombre_legal, nombre_persona_contacto, correo, telefono,
    tipo_de_servicio, tipo_mercancia, detalles_mercancia, ciudad_origen, ciudad_destino,
    y promedio_viajes_mensuales.
    """
    TipoDeServicio(tipo_de_servicio)
    return locals()


def is_valid_item(tipo_mercancia: str):
    """Válida si el tipo de mercancía es transportable. Por ahora, siempre retorna True."""
    return True


def is_valid_city(ciudad: str):
    """Válida si una ciudad es un origen/destino válido. Por ahora, siempre retorna True."""
    return True
