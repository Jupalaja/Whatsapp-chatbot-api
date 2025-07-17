from typing import Optional
from src.shared.enums import TipoDeServicio


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
    tipo_de_servicio: Optional[str] = None,
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


def cliente_solicito_correo():
    """Se debe llamar a esta función cuando el usuario indica que prefiere enviar la información por correo electrónico en lugar de proporcionarla en el chat."""
    return True


def guardar_correo_cliente(email: str):
    """Se debe llamar a esta función para guardar el correo electrónico del cliente cuando este lo proporciona después de haber solicitado enviarlo por correo."""
    return email


def limpiar_datos_agente_comercial(
    responsable_comercial: str,
    email: str,
    telefono: str
) -> dict:
    """
    Limpia y valida los datos del agente comercial obtenidos de Google Sheets.
    
    El modelo debe analizar los datos y determinar:
    1. Si representan un agente comercial válido
    2. Si el nombre necesita ser formateado correctamente
    3. Si los datos de contacto son válidos
    
    Args:
        responsable_comercial: Nombre del responsable comercial desde Google Sheets
        email: Email del responsable comercial
        telefono: Teléfono del responsable comercial
        
    Returns:
        dict con las siguientes claves:
        - "agente_valido": bool - True si hay un agente válido, False si no
        - "nombre_formateado": str - Nombre formateado correctamente (solo si agente_valido=True)
        - "email_valido": str - Email válido o cadena vacía
        - "telefono_valido": str - Teléfono válido o cadena vacía
        - "razon": str - Explicación de por qué no es válido (solo si agente_valido=False)
    """
    # Análisis de datos - indicadores de agente no válido:
    # - Nombres como "SIN RESPONSABLE", "N/A", "NO ASIGNADO", etc.
    # - Emails como "N.A", "N/A", "NO DISPONIBLE", etc.
    # - Teléfonos como "N.A", "N/A", "NO DISPONIBLE", etc.
    
    # Indicadores de datos válidos:
    # - Nombre con formato de persona real (puede estar en formato "APELLIDOS NOMBRES")
    # - Email con formato válido
    # - Teléfono con formato válido
    
    return {
        "agente_valido": False,
        "nombre_formateado": "",
        "email_valido": "",
        "telefono_valido": "",
        "razon": "Datos insuficientes para determinar validez"
    }
