import unicodedata

from src.shared.prompts import (
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


def es_mercancia_valida(tipo_mercancia: str) -> str:
    """
    Valida si un tipo de mercancía o servicio es transportable por Botero Soto.
    El modelo debe analizar la mercancía y determinar si pertenece a una de las categorías prohibidas.
    Si la mercancía o servicio es prohibido, esta función DEBE ser llamada para generar el mensaje de rechazo.

    **Instrucciones para el Modelo:**
    1.  Analiza la mercancía mencionada por el usuario (ej: "oro", "muebles", "servicio de última milla").
    2.  Compara la mercancía con las categorías prohibidas a continuación.
    3.  Si la mercancía coincide con alguna categoría (ej: "oro" es un "metal precioso", o el servicio es "última milla"), **NO respondas directamente al usuario**. En su lugar, llama a esta herramienta con el `tipo_mercancia` exacto que mencionó el usuario.
    4.  Si la mercancía **NO** está en la lista (ej: "ropa", "electrodomésticos", "repuestos"), considera que es válida y continúa la conversación normal. **NO llames a esta herramienta si la mercancía es válida.**

    **Categorías de Mercancías y Servicios Prohibidos:**
    - **Servicios Excluidos:**
      - **Última milla:** No se ofrece distribución de última milla.
    - **Materiales Peligrosos:**
      - Desechos peligrosos, residuos industriales, sustancias tóxicas, infecciosas o radiactivas.
      - Explosivos, pólvora, material pirotécnico, fósforos.
      - Líquidos inflamables, combustibles (gasolina, etanol).
    - **Seres Vivos y Productos Animales:**
      - Semovientes, animales vivos o muertos.
      - Carnes y despojos comestibles sin procesar.
      - Otros productos de origen animal no procesados.
    - **Objetos de Valor Excepcional:**
      - Objetos de arte, colecciones, antigüedades.
      - Perlas, piedras preciosas, metales preciosos (oro, plata, diamantes).
    - **Productos Perecederos:**
      - Legumbres, hortalizas, plantas, raíces y tubérculos alimenticios que requieran refrigeración especial.
      - Pescados, crustáceos, moluscos y otros invertebrados acuáticos frescos.
    - **Armamento:**
      - Armas y municiones.
    - **Hidrocarburos y Derivados:**
      - Aceites crudos de petróleo, minerales bituminosos.
      - Alquitranes, betunes, asfaltos y rocas asfálticas.
      - Vaselina, parafina y ceras minerales.
    - **Otros:**
      - Navegación aérea, espacial, marítima o fluvial.
      - Energía eléctrica, gas de hulla.
    """
    normalized_mercancia = _normalize_text(tipo_mercancia)

    if "ultima milla" in normalized_mercancia:
        return PROMPT_SERVICIO_NO_PRESTADO_ULTIMA_MILLA

    return PROMPT_MERCANCIA_NO_TRANSPORTADA.format(tipo_mercancia=tipo_mercancia)


def es_ciudad_valida(ciudad: str):
    """
    Válida si una ciudad es un origen/destino válido. Si no es válido, retorna un mensaje para el usuario.
    """
    normalized_ciudad = _normalize_text(ciudad)
    if normalized_ciudad in BLACKLISTED_CITIES:
        return PROMPT_CIUDAD_NO_VALIDA.format(ciudad=ciudad.title())
    return True


def es_solicitud_de_mudanza(es_mudanza: bool) -> bool:
    """
    Determina si la solicitud del cliente es para una mudanza.
    El modelo debe analizar el tipo de mercancía y la descripción del usuario y llamar a esta función con `es_mudanza=True` si corresponde a un servicio de mudanza o trasteo.
    """
    return es_mudanza


def es_solicitud_de_paqueteo(es_paqueteo: bool) -> bool:
    """
    Determina si la solicitud del cliente es para paquetes pequeños ("paqueteo").
    El modelo debe analizar la descripción del usuario y llamar a esta función con `es_paqueteo=True` si la solicitud es para "paqueteo".
    Se considera "paqueteo" el transporte de mercancía de bajo peso y volumen. Esto incluye solicitudes con peso inferior a una tonelada (ej. "300 kilos", "media tonelada") o que usen términos como "paquete pequeño".
    """
    return es_paqueteo
