import unicodedata

from src.shared.enums import TipoDeServicio


FORBIDDEN_GOODS_KEYWORDS = {
    # This content is now in shared/utils/validations.py
}


def _normalize_text(name: str) -> str:
    """Normalizes a string by removing accents, converting to lowercase, and stripping whitespace."""
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", name)
        if unicodedata.category(c) != "Mn"
    )
    return s.lower().strip()


def es_solicitud_de_mudanza(es_mudanza: bool) -> bool:
    """
    Determina si la solicitud del cliente es para una mudanza.
    El modelo debe analizar el tipo de mercancía y la descripción del usuario y llamar a esta función con `es_mudanza=True` si corresponde a un servicio de mudanza o trasteo.
    """
    return es_mudanza


def es_solicitud_de_paqueteo(es_paqueteo: bool) -> bool:
    """
    Determina si la solicitud del cliente es para paquetes pequeños.
    El modelo debe analizar el tipo de mercancía y la descripción del usuario y llamar a esta función con `es_paqueteo=True` si corresponde a un servicio de 'paqueteo' qu consiste en transporte de mercancía de bajo peso y poco tamaño.
    """
    return es_paqueteo


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


def buscar_nit(nit: str):
    """Captura el NIT de la empresa proporcionado por el usuario."""
    return nit


def es_persona_natural():
    """Se debe llamar cuando el usuario indica que no es una empresa, por ejemplo si dice 'soy persona natural' o 'no tengo NIT'."""
    return True


def necesita_agente_de_carga():
    """Se debe llamar si la persona natural indica que SÍ está interesada en agenciamiento de carga. Usar solo cuando la persona confirma que necesita un 'agente de carga' o que necesita 'agenciamiento de carga' o un 'freight forwarder'."""
    return True


def obtener_informacion_cliente_potencial(
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


def cliente_solicito_correo():
    """Se debe llamar a esta función cuando el usuario indica que prefiere enviar la información por correo electrónico en lugar de proporcionarla en el chat."""
    return True


def guardar_correo_cliente(email: str):
    """Se debe llamar a esta función para guardar el correo electrónico del cliente cuando este lo proporciona después de haber solicitado enviarlo por correo."""
    return email


def formatear_nombre_responsable(nombre_completo: str) -> str:
    """
    Formatea un nombre completo que está en formato 'APELLIDOS NOMBRES' a 'Nombres Apellidos' con capitalización de tipo título.
    El modelo debe analizar el nombre del responsable comercial y utilizar esta función para formatearlo correctamente.
    Por ejemplo, si el nombre es 'VELEZ IVONNE', se convierte en 'Ivonne Velez'.
    Otro ejemplo: 'Zapata Castrillon Luis Fernando' se convierte en 'Luis Fernando Zapata Castrillon'.

    Heurística de formato:
    - 2 palabras: Apellido Nombre -> Nombre Apellido
    - 3 palabras: Apellido1 Apellido2 Nombre -> Nombre Apellido1 Apellido2
    - 4 palabras: Apellido1 Apellido2 Nombre1 Nombre2 -> Nombre1 Nombre2 Apellido1 Apellido2
    - Para otros casos, se dividirá por la mitad.
    """
    parts = nombre_completo.strip().split()
    num_parts = len(parts)

    if num_parts <= 1:
        return nombre_completo.title()

    if num_parts == 2:  # Asume APELLIDO NOMBRE
        nombres = parts[1:]
        apellidos = parts[:1]
    elif num_parts == 3:  # Heurística: Asume APELLIDO1 APELLIDO2 NOMBRE
        nombres = parts[2:]
        apellidos = parts[:2]
    else:  # 4 o más palabras
        # Asume que los apellidos son la primera mitad y los nombres la segunda
        split_point = num_parts // 2
        apellidos = parts[:split_point]
        nombres = parts[split_point:]

    nombre_formateado = " ".join(nombres) + " " + " ".join(apellidos)
    return nombre_formateado.title()
