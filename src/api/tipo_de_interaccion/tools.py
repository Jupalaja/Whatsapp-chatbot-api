from typing import List
from src.shared.schemas import (
    CategoriaClasificacionLiteral,
    CategoriaPuntuacion,
)


def clasificar_interaccion(
    puntuacionesPorCategoria: List[CategoriaPuntuacion],
    clasificacionPrimaria: CategoriaClasificacionLiteral,
    clasificacionesAlternativas: List[CategoriaClasificacionLiteral],
):
    """Clasifica la interacción del usuario en una de varias categorías predefinidas."""
    return locals()
