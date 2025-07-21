from typing import Optional


def buscar_nit(nit: str):
    """Captura el NIT de la empresa proporcionado por el usuario."""
    return nit


def es_persona_natural():
    """Se debe llamar cuando el usuario indica que no es una empresa, por ejemplo si dice 'soy persona natural' o 'no tengo NIT'."""
    return True


def necesita_agente_de_carga():
    """Se debe llamar si la persona natural indica que SÍ está interesada en agenciamiento de carga. Usar solo cuando la persona confirme que necesita un 'agente de carga' o que necesita 'agenciamiento de carga' o un 'freight forwarder'."""
    return True


def obtener_informacion_esencial_cliente_potencial(
    nombre_persona_contacto: Optional[str] = None,
    telefono: Optional[str] = None,
    tipo_mercancia: Optional[str] = None,
    ciudad_origen: Optional[str] = None,
    ciudad_destino: Optional[str] = None,
):
    """
    Se debe llamar a esta función para guardar cualquier pieza de información esencial del cliente que se haya recopilado.
    El modelo debe seguir pidiendo la información faltante hasta que tenga todos los datos esenciales: nombre_persona_contacto, telefono, tipo_mercancia, ciudad_origen, y ciudad_destino.
    """
    return {k: v for k, v in locals().items() if v is not None}


def informacion_esencial_obtenida(obtenida: bool):
    """
    Llama a esta función con `obtenida=True` una vez que se haya recopilado TODA la información esencial del cliente potencial (nombre de contacto, teléfono, tipo de mercancía, ciudad de origen y ciudad de destino).
    Esto indica que se puede proceder al siguiente paso.
    """
    return obtenida


def obtener_informacion_adicional_cliente_potencial(
    nombre_legal: Optional[str] = None,
    correo: Optional[str] = None,
    detalles_mercancia: Optional[str] = None,
    peso_de_mercancia: Optional[str] = None,
    promedio_viajes_mensuales: Optional[int] = None,
):
    """
    Se debe llamar a esta función para guardar cualquier información adicional del cliente que se haya recopilado.
    Esta función guarda detalles opcionales del cliente potencial.
    No se debe insistir al usuario para obtener esta información si decide no proporcionarla.
    """
    # Return only provided values
    return {k: v for k, v in locals().items() if v is not None}


def obtener_tipo_de_servicio(tipo_de_servicio: str):
    """
    Infiere y guarda el tipo de servicio que el cliente potencial necesita.
    El modelo debe analizar el historial de la conversación y determinar el servicio más probable.

    Posibles valores para `tipo_de_servicio`:
    - TRANSPORTE_NACIONAL
    - EXPORTACION
    - IMPORTACION
    - DISTRIBUCION
    - ALMACENAMIENTO
    - ITR (Recibo de Traslado de Intercambio)
    - TRANSPORTE_ANDINO
    """
    return tipo_de_servicio


def cliente_solicito_correo():
    """Se debe llamar a esta función cuando el usuario indica que prefiere enviar la información por correo electrónico en lugar de proporcionarla en el chat."""
    return True


def guardar_correo_cliente(email: str):
    """Se debe llamar a esta función para guardar el correo electrónico del cliente cuando este lo proporciona después de haber solicitado enviarlo por correo."""
    return email


def limpiar_datos_agente_comercial(
    agente_valido: bool,
    nombre_formateado: Optional[str] = None,
    email_valido: Optional[str] = None,
    telefono_valido: Optional[str] = None,
    razon: Optional[str] = None,
) -> dict:
    """
    Limpia y valida los datos del agente comercial obtenidos de Google Sheets.

    El modelo debe analizar los datos de entrada y llamar a esta función con los resultados.

    Análisis de datos:
    - Indicadores de agente no válido: Nombres como "SIN RESPONSABLE", "N/A", "NO ASIGNADO". Emails o teléfonos como "N.A", "N/A", "NO DISPONIBLE".
    - Formato de nombre: Si el nombre está en formato "APELLIDOS NOMBRES", formatearlo a "Nombres Apellidos" (capitalización de título).
    - Validación de contacto: Verificar que el email y teléfono sean válidos. Si no, devolver un string vacío.

    Args:
        agente_valido: True si los datos representan un agente válido, False si no.
        nombre_formateado: Nombre del agente con formato de título (e.g., "Paola Andrea Guerra Cardona"). Solo si es válido.
        email_valido: Email válido del agente. Solo si es válido.
        telefono_valido: Teléfono válido del agente. Solo si es válido.
        razon: Explicación de por qué no es válido. Solo si `agente_valido` es False.
    """
    return {
        "agente_valido": agente_valido,
        "nombre_formateado": nombre_formateado,
        "email_valido": email_valido,
        "telefono_valido": telefono_valido,
        "razon": razon,
    }
