def search_nit(nit: str):
    """Busca información de una empresa por su NIT."""
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
    """Se debe llamar cuando el usuario indica que no es una empresa, por ejemplo si dice 'soy persona natural' o 'no tengo NIT'."""
    return True


def needs_freight_forwarder():
    """Se debe llamar si la persona natural indica que SÍ está interesada en agenciamiento de carga. Usar solo cuando la persona confirma que necesita un 'agente de carga' o que necesita 'agenciamiento de carga' o un 'freight forwarder'."""
    return True
