import enum


class TransportistaState(str, enum.Enum):
    """
    Defines the possible states in the carrier conversation flow.
    """

    AWAITING_REQUEST_TYPE = "AWAITING_REQUEST_TYPE"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
