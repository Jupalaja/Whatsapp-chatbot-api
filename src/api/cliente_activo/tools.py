from typing import Optional


def buscar_nit(nit: str):
    """Captura el NIT de la empresa proporcionado por el usuario."""
    return nit


def obtener_informacion_cliente_activo(nombre_empresa: Optional[str] = None):
    """
    Captura el Nombre de la empresa proporcionado por usuario, este valor es opcional.
    """
    return nombre_empresa


def es_consulta_trazabilidad(es_trazabilidad: bool) -> bool:
    """Retorna True si la consulta tiene que ver con trazabilidad (ubicar un vehículo)."""
    return es_trazabilidad


def es_consulta_bloqueos_cartera(es_bloqueos_cartera: bool) -> bool:
    """Retorna True si la consulta tiene que ver con bloqueos de cartera."""
    return es_bloqueos_cartera


def es_consulta_facturacion(es_facturacion: bool) -> bool:
    """Retorna True si la consulta tiene que ver con facturación."""
    return es_facturacion


def es_consulta_cotizacion(es_cotizacion: bool) -> bool:
    """Retorna True si la consulta es para realizar una cotización."""
    return es_cotizacion


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
