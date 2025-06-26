from src.shared.enums import CategoriaUsuarioAdministrativo


def obtener_tipo_de_necesidad(categoria: str) -> dict:
    """
    Clasifica la consulta de un usuario administrativo en una de las categorías predefinidas.
    El modelo debe analizar la consulta y llamar a esta función con el valor correspondiente del enumerado `CategoriaUsuarioAdministrativo`.

    Args:
        categoria: La categoría de la consulta del usuario.
    """
    valid_categoria = CategoriaUsuarioAdministrativo(categoria)
    return {"categoria": valid_categoria.value}
