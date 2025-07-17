import enum


class ClienteActivoState(str, enum.Enum):
    """
    Defines the possible states in the active client conversation flow.
    """

    AWAITING_NIT = "AWAITING_NIT"
    AWAITING_RESOLUTION = "AWAITING_RESOLUTION"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
