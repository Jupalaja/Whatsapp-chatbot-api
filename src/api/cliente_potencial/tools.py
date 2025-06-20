from src.shared.enums import TipoDeServicio


def inferir_tipo_de_servicio(tipo_de_servicio: str) -> str:
    """
    Valída y estandariza el tipo de servicio logístico inferido por el modelo.
    El modelo debe analizar la descripción del servicio del usuario y llamar a esta función con el valor correspondiente del enumerado `TipoDeServicio`.
    Este valor estandarizado se utiliza luego para registrar la información del cliente potencial.
    Por ejemplo, si un usuario dice 'necesito transportar maquinaria', el modelo debe invocar esta función con `tipo_de_servicio='DISTRIBUCION'`.

    Args:
        tipo_de_servicio: El tipo de servicio inferido por el modelo. Debe ser uno de los valores del enumerado `TipoDeServicio`.

    Returns:
        El valor del enumerado `TipoDeServicio` como una cadena de texto.
    """
    return TipoDeServicio(tipo_de_servicio).value


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
    peso_de_mercancia: str,
    ciudad_origen: str,
    ciudad_destino: str,
    promedio_viajes_mensuales: int,
):
    """
    Se debe llamar a esta función cuando se haya recopilado la información
    requerida del cliente. Esta función guarda los detalles del cliente potencial.
    La información requerida es: nombre_legal, nombre_persona_contacto, correo, telefono,
    tipo_de_servicio, tipo_mercancia, detalles_mercancia, peso_de_mercancia, ciudad_origen, ciudad_destino,
    y promedio_viajes_mensuales. No esperes una confirmación del cliente para llamar esta
    función, con tener la información suficiente basta.
    """
    TipoDeServicio(tipo_de_servicio)
    return locals()


def is_valid_item(tipo_mercancia: str):
    """Válida si el tipo de mercancía es transportable. Por ahora, siempre retorna True."""
    return True


def is_valid_city(ciudad: str):
    """Válida si una ciudad es un origen/destino válido. Por ahora, siempre retorna True."""
    return True


def customer_requested_email():
    """
    Se debe llamar a esta función cuando el usuario indica que prefiere enviar la información por correo electrónico en lugar de proporcionarla en el chat.
    """
    return True


def save_customer_email(email: str):
    """
    Se debe llamar a esta función para guardar el correo electrónico del cliente cuando este lo proporciona después de haber solicitado enviarlo por correo.
    """
    return email
