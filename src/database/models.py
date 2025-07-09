from sqlalchemy import Column, String, JSON, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base


class Interaction(Base):
    """
    Represents a conversation session stored in the database.
    """

    __tablename__ = "interactions"

    session_id = Column(String, primary_key=True, index=True)
    messages = Column(JSONB, nullable=False)
    state = Column(String, nullable=True)
    interaction_data = Column(JSON, nullable=True)
    user_data = Column(JSON, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
