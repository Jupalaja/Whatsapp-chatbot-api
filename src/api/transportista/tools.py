from src.shared.enums import CategoriaTransportista


def obtener_tipo_de_solicitud(categoria: str) -> dict:
    """
    Clasifica la consulta de un transportista en una de las categorías predefinidas.
    El modelo debe analizar la consulta y llamar a esta función con el valor correspondiente del enumerado `CategoriaTransportista`.

    Args:
        categoria: La categoría de la consulta del transportista.
    """
    valid_categoria = CategoriaTransportista(categoria)
    return {"categoria": valid_categoria.value}


def enviar_video_registro_app():
    """Llama a esta función si el usuario pregunta '¿Cómo me registro en la App?'."""
    return {
        "video_file": "registro-usuario-nuevo.mp4",
        "caption": "Este es un video explicativo con instrucciones sobre cómo registrarte en la App.",
    }


def enviar_video_actualizacion_datos_app():
    """Llama a esta función si el usuario pregunta '¿Cómo actualizo mis datos en la App?'."""
    return {
        "video_file": "actualizacion-de-datos.mp4",
        "caption": "Este es un video explicativo con instrucciones sobre cómo actualizar tus datos en la App.",
    }


def enviar_video_enturno_app():
    """Llama a esta función si el usuario pregunta '¿Cómo me enturno en la App?'."""
    return {
        "video_file": "crear-turno.mp4",
        "caption": "Este es un video explicativo con instrucciones sobre cómo enturnarte en la App.",
    }


def enviar_video_reporte_eventos_app():
    """Llama a esta función si el usuario pregunta '¿Cómo reporto mis eventos en la App?'."""
    return {
        "video_file": "reporte-de-eventos.mp4",
        "caption": "Este es un video explicativo con instrucciones sobre cómo reportar tus eventos en la App.",
    }
