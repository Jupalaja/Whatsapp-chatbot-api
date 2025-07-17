from typing import Optional


def obtener_ayuda_humana(reason: Optional[str] = None):
    """Utiliza esta función cuando el usuario solicite explícitamente ayuda humana o hablar con un humano."""
    if reason:
        return f"HUMANO INTERVIENE AQUÍ\n Error:[{reason}]"
    return "HUMANO INTERVIENE AQUÍ"
