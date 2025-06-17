import enum


class ClientePotencialState(str, enum.Enum):
    """
    Defines the possible states in the potential client qualification conversation flow.
    Each state represents a different stage in the interaction with the user.
    """

    # Initial state, waiting for the user to provide a NIT (Tax ID).
    AWAITING_NIT = "AWAITING_NIT"
    # State after user indicates they are a natural person, waiting for more info.
    AWAITING_REMAINING_INFORMATION = "AWAITING_REMAINING_INFORMATION"
    # State when a NIT has been provided and validated.
    NIT_PROVIDED = "NIT_PROVIDED"
    # Terminal state when the user is not a potential client for the primary services.
    CUSTOMER_DISCARDED = "CUSTOMER_DISCARDED"
    # Terminal state when the conversation requires human intervention.
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
