import enum


class GlobalState(str, enum.Enum):
    """
    Defines the possible states shared by ALL the conversation flows.
    """
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
