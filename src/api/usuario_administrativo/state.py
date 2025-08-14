import enum


class UsuarioAdministrativoState(str, enum.Enum):
    """
    Defines the possible states in the administrative user conversation flow.
    """

    AWAITING_NECESITY_TYPE = "AWAITING_NECESITY_TYPE"
    AWAITING_ADMIN_INFO = "AWAITING_ADMIN_INFO"
    CONVERSATION_FINISHED = "CONVERSATION_FINISHED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
