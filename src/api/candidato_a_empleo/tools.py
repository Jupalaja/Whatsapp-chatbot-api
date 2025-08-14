from typing import Optional


def obtener_informacion_candidato(
    nombre: Optional[str] = None, cedula: Optional[str] = None, vacante: Optional[str] = None
):
    """
    Se debe llamar a esta función para guardar el nombre, la cédula y la vacante a la que aplica el candidato.
    El modelo debe preguntar por esta información en el orden: nombre, cédula y vacante.
    """
    return {k: v for k, v in locals().items() if v is not None}
