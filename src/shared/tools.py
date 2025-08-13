from src.shared.prompts import AYUDA_HUMANA_PROMPT


def obtener_ayuda_humana():
    """Utiliza esta función cuando el usuario solicite explícitamente ayuda humana o hablar con un humano."""
    return AYUDA_HUMANA_PROMPT


def nueva_interaccion_requerida():
    """Utiliza esta función cuando, después de haber resuelto una consulta previa, el usuario indica que tiene una nueva pregunta o necesidad diferente a la anterior."""
    return True
