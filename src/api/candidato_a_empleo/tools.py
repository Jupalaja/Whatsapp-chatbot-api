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


def obtener_informacion_candidato(
    nombre: Optional[str] = None, cedula: Optional[str] = None
):
    """
    Se debe llamar a esta función para guardar el nombre y la cédula del candidato.
    El modelo debe preguntar por esta información después de haber obtenido la vacante a la que aplica el candidato.
    """
    return {k: v for k, v in locals().items() if v is not None}
