import unicodedata

from src.shared.enums import TipoDeServicio
from .prompts import (
    PROMPT_CIUDAD_NO_VALIDA,
    PROMPT_MERCANCIA_NO_TRANSPORTADA,
    PROMPT_SERVICIO_NO_PRESTADO_ULTIMA_MILLA,
)


BLACKLISTED_CITIES = {
    # Amazonas
    "leticia", "el encanto", "la chorrera", "la pedrera", "la victoria", "miriti-parana", "puerto alegria", "puerto arica", "puerto narino", "puerto santander", "tarapaca",
    # Arauca
    "arauca", "arauquita", "cravo norte", "fortul", "puerto rondon", "saravena", "tame",
    # Archipiélago de San Andrés, Providencia y Santa Catalina
    "san andres", "providencia", "santa catalina",
    # Bolívar
    "altos del rosario", "barranco de loba", "el penon", "regidor", "rio viejo", "san martin de loba", "arenal", "cantagallo", "morales", "san pablo", "santa rosa del sur", "simiti", "montecristo", "pinillos", "san jacinto del cauca", "tiquisio",
    # Caquetá
    "albania", "belen de los andaquies", "cartagena del chaira", "curillo", "el doncello", "el paujil", "la montanita", "milan", "morelia", "puerto rico", "san jose del fragua", "san vicente del caguan", "solano", "solita", "valparaiso",
    # Cauca
    "cajibio", "el tambo", "la sierra", "morales", "sotara", "buenos aires", "suarez", "guapi", "lopez", "timbiqui", "inza", "jambalo", "paez", "purace", "silvia", "toribio", "totoro", "almaguer", "argelia", "balboa", "bolivar", "florencia", "la vega", "piamonte", "san sebastian", "santa rosa", "sucre",
    # Chocó
    "atrato", "darien", "pacifico norte", "pacifico sur", "san juan", "bagado", "bahia solano", "nuqui", "alto baudo", "condoto",
    # Guainía
    "barranco mina", "cacahual", "inirida", "la guadalupe", "mapiripan", "morichal", "pana pana", "puerto colombia", "san felipe",
    # Guaviare
    "calamar", "el retorno", "miraflores", "san jose del guaviare",
    # Huila
    "algeciras", "santa maria",
    # Norte de Santander
    "el tarra", "tibu", "cachira", "convencion", "el carmen", "hacari", "la playa", "san calixto", "teorama", "herran", "ragonvalia",
    # Putumayo
    "colon", "puerto asis", "puerto caicedo", "puerto guzman", "puerto leguizamo", "san francisco", "san miguel", "santiago", "sibundoy", "valle del guamuez", "villa garzon",
    # Vaupés
    "caruru", "mitu", "pacoa", "papunahua", "taraira", "yavarate",
    # Vichada
    "cumaribo", "la primavera", "puerto carreno", "santa rosalia",
}


def _normalize_text(name: str) -> str:
    """Normalizes a string by removing accents, converting to lowercase, and stripping whitespace."""
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", name)
        if unicodedata.category(c) != "Mn"
    )
    return s.lower().strip()


FORBIDDEN_GOODS_KEYWORDS = {
    _normalize_text(keyword) for keyword in [
        # Mercancías que no moviliza Botero Soto
        "desechos peligrosos", "semovientes", "animales vivos", "animal", "armas", "municiones",
        "carnes", "despojos comestibles", "explosivos", "legumbres", "hortalizas", "plantas",
        "raices", "tuberculos alimenticios", "liquidos inflamables", "productos de origen animal",
        "material radiactivo", "navegacion aerea", "navegacion espacial", "navegacion maritima",
        "navegacion fluvial", "objetos de arte", "coleccion", "antigüedad", "perlas",
        "piedras preciosas", "pescados", "crustaceos", "moluscos", "invertebrados acuaticos",
        "polvora", "pirotecnia", "fosforos", "cerillas", "residuos", "desperdicios",
        "alimentos", "sustancias toxicas", "sustancias infecciosas",
        # Productos no transportados por Botero Soto
        "aceites crudos", "aceites de petroleo", "minerales bituminosos",
        "alquitranes de hulla", "alquitranes de lignito", "alquitranes de turba",
        "alquitranes minerales", "betunes", "asfaltos naturales", "pizarras bituminosas",
        "arenas bituminosas", "asfaltitas", "rocas asfalticas", "brea", "coque de brea",
        "coque de petroleo", "betun de petroleo", "energia electrica", "gas de hulla",
        "gas de agua", "gas pobre", "lignitos", "azabache", "mezclas bituminosas",
        "turba", "vaselina", "parafina", "cera de petroleo", "ozoquerita",
        "cera de lignito", "cera de turba", "ceras minerales", "combustible para motores",
        "gasolina", "etanol",
    ]
}


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


def es_mercancia_valida(tipo_mercancia: str):
    """
    Válida si el tipo de mercancía y servicio asociado son transportables por Botero Soto.
    Devuelve True si es válido, o un mensaje de error si no lo es.
    """
    normalized_mercancia = _normalize_text(tipo_mercancia)

    if "ultima milla" in normalized_mercancia:
        return PROMPT_SERVICIO_NO_PRESTADO_ULTIMA_MILLA

    for keyword in FORBIDDEN_GOODS_KEYWORDS:
        if keyword in normalized_mercancia:
            return PROMPT_MERCANCIA_NO_TRANSPORTADA.format(tipo_mercancia=tipo_mercancia)

    return True


def es_ciudad_valida(ciudad: str):
    """
    Válida si una ciudad es un origen/destino válido. Si no es válido, retorna un mensaje para el usuario.
    """
    normalized_ciudad = _normalize_text(ciudad)
    if normalized_ciudad in BLACKLISTED_CITIES:
        return PROMPT_CIUDAD_NO_VALIDA.format(ciudad=ciudad.title())
    return True


def cliente_solicito_correo():
    """Se debe llamar a esta función cuando el usuario indica que prefiere enviar la información por correo electrónico en lugar de proporcionarla en el chat."""
    return True


def guardar_correo_cliente(email: str):
    """Se debe llamar a esta función para guardar el correo electrónico del cliente cuando este lo proporciona después de haber solicitado enviarlo por correo."""
    return email
