from src.shared.enums import CategoriaTransportista


def obtener_tipo_de_solicitud(categoria: str) -> dict:
    """
    Clasifica la consulta de un transportista en una de las categorías predefinidas.
    El modelo debe analizar la consulta y llamar a esta función con el valor correspondiente del enumerado `CategoriaTransportista`.

    Args:
        categoria: La categoría de la consulta del transportista.
    """
    valid_categoria = CategoriaTransportista(categoria)
    return {"categoria": valid_categoria.value}
