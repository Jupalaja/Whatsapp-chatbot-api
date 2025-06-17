import enum


class ClientePotencialState(str, enum.Enum):
    """
    Defines the possible states in the potential client qualification conversation flow.
    Each state represents a different stage in the interaction with the user.
    """
    AWAITING_NIT = "AWAITING_NIT"
    AWAITING_REMAINING_INFORMATION = "AWAITING_REMAINING_INFORMATION"
    NIT_PROVIDED = "NIT_PROVIDED"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
