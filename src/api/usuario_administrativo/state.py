import enum


class UsuarioAdministrativoState(str, enum.Enum):
    """
    Defines the possible states in the administrative user conversation flow.
    """

    AWAITING_NECESITY_TYPE = "AWAITING_NECESITY_TYPE"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
