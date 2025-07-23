from typing import Optional


def obtener_ayuda_humana(reason: Optional[str] = None):
    """Utiliza esta función cuando el usuario solicite explícitamente ayuda humana o hablar con un humano."""
    if reason:
        return f"HUMANO INTERVIENE AQUÍ\n Error:[{reason}]"
    return "HUMANO INTERVIENE AQUÍ"


def nueva_interaccion_requerida():
    """Utiliza esta función cuando, después de haber resuelto una consulta previa, el usuario indica que tiene una nueva pregunta o necesidad diferente a la anterior."""
    return True
