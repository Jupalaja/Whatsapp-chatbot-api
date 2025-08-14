import enum


class CandidatoAEmpleoState(str, enum.Enum):
    """
    Defines the possible states in the job candidate conversation flow.
    """

    AWAITING_CANDIDATE_INFO = "AWAITING_CANDIDATE_INFO"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
