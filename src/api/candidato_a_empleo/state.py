import enum


class CandidatoAEmpleoState(str, enum.Enum):
    """
    Defines the possible states in the job candidate conversation flow.
    """

    AWAITING_VACANCY = "AWAITING_VACANCY"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
