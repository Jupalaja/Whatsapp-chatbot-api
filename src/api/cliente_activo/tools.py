from src.shared.enums import CategoriaClienteActivo


def clasificar_solicitud_cliente_activo(categoria: str) -> dict:
    """
    Clasifica la consulta de un cliente activo en una de las categorías predefinidas.
    El modelo debe analizar la consulta y llamar a esta función con el valor correspondiente del enumerado `CategoriaClienteActivo`.

    Args:
        categoria: La categoría de la consulta del cliente.
    """
    valid_categoria = CategoriaClienteActivo(categoria)
    return {"categoria": valid_categoria.value}
