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

FORBIDDEN_GOODS_KEYWORDS = {
    _normalize_text(keyword)
    for keyword in [
        # From docstring
        "ultima milla",
        "desechos peligrosos",
        "residuos industriales",
        "sustancias toxicas",
        "sustancias infecciosas",
        "radiactivas",
        "explosivos",
        "polvora",
        "material pirotecnico",
        "fosforos",
        "liquidos inflamables",
        "combustibles",
        "gasolina",
        "etanol",
        "semovientes",
        "animales vivos",
        "animales muertos",
        "animal",
        "cerdos",
        "ganado",
        "reses",
        "aves",
        "carnes",
        "despojos comestibles",
        "productos de origen animal",
        "objetos de arte",
        "colecciones",
        "antiguedades",
        "perlas",
        "piedras preciosas",
        "metales preciosos",
        "oro",
        "plata",
        "diamantes",
        "legumbres",
        "hortalizas",
        "plantas",
        "raices",
        "tuberculos alimenticios",
        "pescados",
        "crustaceos",
        "moluscos",
        "invertebrados acuaticos",
        "armas",
        "municiones",
        "aceites crudos de petroleo",
        "minerales bituminosos",
        "alquitranes",
        "betunes",
        "asfaltos",
        "rocas asfalticas",
        "vaselina",
        "parafina",
        "ceras minerales",
        "navegacion aerea",
        "navegacion espacial",
        "navegacion maritima",
        "navegacion fluvial",
        "energia electrica",
        "gas de hulla",
    ]
}


def es_mercancia_valida(tipo_mercancia: str) -> bool | str:
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

    for keyword in FORBIDDEN_GOODS_KEYWORDS:
        if keyword in normalized_mercancia:
            return PROMPT_MERCANCIA_NO_TRANSPORTADA.format(
                tipo_mercancia=tipo_mercancia
            )

    return True


def es_ciudad_valida(ciudad: str):
    """
    Valida si una ciudad de origen o destino es válida según el área de cobertura de Botero Soto.
    Si el modelo detecta que el usuario menciona una ciudad, debe llamar a esta función para validarla.
    Si la ciudad es inválida, esta función generará el mensaje de rechazo apropiado. Para envíos internacionales fuera de la cobertura terrestre (Venezuela, Ecuador, Perú), se debe usar `es_envio_internacional`.

    **Instrucciones para el Modelo:**
    1.  Analiza la ciudad mencionada por el usuario (ej: "Leticia", "Bogotá").
    2.  Llama a esta herramienta con el `ciudad` exacto que mencionó el usuario para que sea validada.
    3.  Si la ciudad es válida, la herramienta devolverá `True` y podrás continuar la conversación.
    4.  Si la ciudad es inválida (sin cobertura en Colombia), la herramienta devolverá un mensaje de texto. **Debes usar este mensaje como tu respuesta final al usuario y terminar la conversación sobre esa solicitud.**

    **Área de Cobertura de Botero Soto:**
    - **Principal:** Colombia.
    - **Internacional Terrestre:** Venezuela, Ecuador y Perú.
    - **Exclusiones Importantes:**
        - No se ofrece transporte aéreo ni marítimo.
        - No hay servicio a ninguna ciudad fuera de los países mencionados.
        - **Ejemplos de destinos NO válidos:** Estados Unidos (Miami, Nueva York), Europa (Madrid, París), Asia (Tokio), Chile, Argentina, Brasil, México, etc.

    **Ciudades Colombianas Sin Cobertura:**
    Existe una lista interna de ciudades y municipios en Colombia a los que no se presta servicio. Esta herramienta también valida contra esa lista. No necesitas conocerla, solo llama a la herramienta.
    """
    normalized_ciudad = _normalize_text(ciudad)
    if normalized_ciudad in BLACKLISTED_CITIES:
        return PROMPT_CIUDAD_NO_VALIDA.format(ciudad=ciudad.title())
    return True


def es_envio_internacional(es_internacional: bool) -> bool:
    """
    Determina si una solicitud de envío es para un destino internacional y si está dentro de la cobertura de Botero Soto.
    La cobertura terrestre incluye: Colombia, Venezuela, Ecuador y Perú.

    **Instrucciones para el Modelo:**
    1.  Analiza la ubicación de origen o destino mencionada.
    2.  Si el destino está en **Venezuela, Ecuador o Perú**, llama a esta herramienta con `es_internacional=False` para indicar que es un destino internacional válido.
    3.  Si el destino está **fuera de Colombia, Venezuela, Ecuador y Perú** (ej: "China", "Miami", "Madrid"), llama a esta herramienta con `es_internacional=True` para indicar que es un destino no válido.
    4.  Si el envío es dentro de Colombia, usa la herramienta `es_ciudad_valida` en su lugar y no llames a esta.
    """
    return es_internacional


def es_solicitud_de_mudanza(es_mudanza: bool) -> bool:
    """
    Determina si la solicitud del cliente es para una mudanza.
    El modelo debe analizar la descripción del usuario y llamar a esta función con `es_mudanza=True` si la solicitud se refiere a un servicio de mudanza, trasteo o el transporte de enseres domésticos como muebles, electrodomésticos, colchones, etc.

    **Instrucciones para el Modelo:**
    1.  Analiza el mensaje en busca de palabras clave como "mudanza", "trasteo", "muebles", "enseres", "electrodomésticos", "nevera", "cama", "sofá", etc.
    2.  Si la solicitud se ajusta a la descripción de una mudanza, llama a esta herramienta con `es_mudanza=True`.
    3.  Si no estás seguro, es mejor no llamar a la herramienta y continuar la conversación para aclarar.
    """
    return es_mudanza


def es_solicitud_de_paqueteo(es_paqueteo: bool) -> bool:
    """
    Determina si la solicitud del cliente es para paquetes pequeños ("paqueteo").
    El modelo debe analizar la descripción del usuario y llamar a esta función con `es_paqueteo=True` si la solicitud es para "paqueteo".
    Se considera "paqueteo" el transporte de mercancía de bajo peso y volumen. Esto incluye cualquier solicitud con un peso explícitamente mencionado que sea inferior a 1000 kilogramos (1 tonelada).

    **Instrucciones para el Modelo:**
    1.  Analiza la descripción del usuario en busca de menciones de peso (ej: "30 kilos", "500 kg", "media tonelada"). Si el peso mencionado es **menor a 1000 kg**, DEBES llamar a esta herramienta con `es_paqueteo=True`.
    2.  Utiliza esta herramienta si el usuario usa términos que **inequívocamente** se refieren a envíos pequeños, como "un sobre", "un paquete pequeño", o "una cajita".
    3.  Si el usuario menciona "cajas" sin especificar el peso total o las dimensiones (ej: "3 cajas de zapatos"), **NO** asumas que es paqueteo y **NO llames a esta herramienta**. En su lugar, continúa la conversación para obtener el peso de la mercancía.
    4.  Si el peso es de 1000 kg o más, o si no se menciona un peso y la descripción no sugiere paqueteo (y no cumple con el punto 2), **NO** llames a esta herramienta.
    """
    return es_paqueteo
