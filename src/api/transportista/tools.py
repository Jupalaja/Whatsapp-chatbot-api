from typing import Optional


def es_consulta_manifiestos(es_manifiestos: bool) -> bool:
    """Llama a esta función con `es_manifiestos=True` si la consulta del transportista es sobre manifiestos o su pago."""
    return es_manifiestos


def es_consulta_enturnamientos(es_enturnamientos: bool) -> bool:
    """Llama a esta función con `es_enturnamientos=True` si la consulta del transportista es sobre enturnamientos, reporte de eventos, registro de nuevos usuarios o actualización de datos (que no sean sobre la app)."""
    return es_enturnamientos


def es_consulta_app(es_app: bool) -> bool:
    """Llama a esta función con `es_app=True` si la consulta del transportista es sobre cualquier duda o problema con la aplicación de conductores."""
    return es_app


def obtener_informacion_transportista(
    placa_vehiculo: Optional[str] = None, nombre: Optional[str] = None
):
    """
    Se debe llamar a esta función para guardar la placa del vehículo y el nombre del transportista.
    El modelo debe preguntar por esta información después de haber obtenido el tipo de necesidad.
    """
    return {k: v for k, v in locals().items() if v is not None}


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
