import enum


class ClientePotencialState(str, enum.Enum):
    """
    Defines the possible states in the potential client qualification conversation flow.
    Each state represents a different stage in the interaction with the user.
    """

    AWAITING_NIT = "AWAITING_NIT"
    AWAITING_PERSONA_NATURAL_FREIGHT_INFO = "AWAITING_PERSONA_NATURAL_FREIGHT_INFO"
    AWAITING_REMAINING_INFORMATION = "AWAITING_REMAINING_INFORMATION"
    CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT = "CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
