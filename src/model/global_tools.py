from typing import List
from ..schemas import CategoriaPuntuacion


def get_human_help():
    """Use this function when the user explicitly asks for human help or to talk to a human."""
    return "A human will be with you shortly."


def clasificar_interaccion(
    puntuacionesPorCategoria: List[CategoriaPuntuacion],
    clasificacionPrimaria: str,
    clasificacionesAlternativas: List[str],
):
    """Clasifica la interacción del usuario en una de varias categorías predefinidas."""
    return locals()
