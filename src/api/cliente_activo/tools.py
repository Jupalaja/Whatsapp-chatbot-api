from typing import Optional
from src.shared.enums import CategoriaClienteActivo


def buscar_nit(nit: str):
    """Captura el NIT de la empresa proporcionado por el usuario."""
    return nit


def clasificar_solicitud_cliente_activo(categoria: str) -> dict:
    """
    Clasifica la consulta de un cliente activo en una de las categorías predefinidas.
    El modelo debe analizar la consulta y llamar a esta función con el valor correspondiente del enumerado `CategoriaClienteActivo`.

    Args:
        categoria: La categoría de la consulta del cliente.
    """
    valid_categoria = CategoriaClienteActivo(categoria)
    return {"categoria": valid_categoria.value}


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
