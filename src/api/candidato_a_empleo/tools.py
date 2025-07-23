from typing import Optional


def obtener_vacante(vacante: Optional[str] = None) -> Optional[str]:
    """
    Se debe llamar a esta función cuando se haya recopilado la información sobre la vacante a la que aplica el candidato.
    Si el candidato no sabe o no especifica la vacante, llama a la función sin el argumento 'vacante'.
    Esta función guarda la vacante.

    Args:
        vacante: La vacante a la que aplica el candidato. Este campo es opcional.
    """
    return vacante
