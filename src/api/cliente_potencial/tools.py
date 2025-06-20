import unicodedata

from src.shared.enums import TipoDeServicio


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


def _normalize_city_name(name: str) -> str:
    """Normalizes a city name by removing accents, converting to lowercase, and stripping whitespace."""
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", name)
        if unicodedata.category(c) != "Mn"
    )
    return s.lower().strip()


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
    """
    Válida si una ciudad es un origen/destino válido. Si no es válido, retorna un mensaje para el usuario.
    """
    normalized_ciudad = _normalize_city_name(ciudad)
    if normalized_ciudad in BLACKLISTED_CITIES:
        return f"Lo sentimos, no prestamos servicio en {ciudad.title()}, ya que se encuentra en una zona donde actualmente no tenemos cobertura. Agradecemos tu interés en Botero Soto."
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
