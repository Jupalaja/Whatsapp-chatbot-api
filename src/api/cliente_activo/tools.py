from src.shared.enums import CategoriaClienteActivo


def obtener_nit(nit: str):
    """Captura el NIT de la empresa proporcionado por el usuario. Si el usuario no proporciona un NIT o especifica que no tiene uno, responde con un string vacío ''"""
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
