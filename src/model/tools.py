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
    # This is a dummy function for schema generation for the model.
    # The model will generate the arguments for this function.
    return locals()


def search_nit(nit: str):
    """Busca información de una empresa por su NIT."""
    # This is a dummy function for schema generation for the model.
    # In a real scenario, this would look up the NIT in a database.
    if nit == "901535329":
        return {
            "cliente": "Elevva Colombia S.A.S.",
            "estado": "PERDIDO_2_ANOS",
            "responsable_comercial": "TEGUA SIERRA DEISSY ROCIO",
        }
    elif nit == "901534449":
        return {
            "cliente": "Insumos & Ingeniería S.A.S",
            "estado": "NUEVO",
            "responsable_comercial": "CORTES LEON KEVIN DAVID",
        }
    else:
        return {
            "cliente": "No encontrado",
            "estado": "No encontrado",
            "responsable_comercial": "No encontrado",
        }

def is_persona_natural():
    """Se debe llamar cuando el usuario indica que no es una empresa."""
    # This is a dummy function for schema generation for the model.
    return True


def needs_freight_forwarder():
    """Se debe llamar si la persona natural está interesada en agenciamiento de carga."""
    # This is a dummy function for schema generation for the model.
    return True
