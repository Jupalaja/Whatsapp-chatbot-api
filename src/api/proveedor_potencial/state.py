import enum


class ProveedorPotencialState(str, enum.Enum):
    """
    Defines the possible states in the potential provider conversation flow.
    """

    AWAITING_SERVICE_TYPE = "AWAITING_SERVICE_TYPE"
    AWAITING_COMPANY_INFO = "AWAITING_COMPANY_INFO"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
