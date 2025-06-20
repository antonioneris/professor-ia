from sqlalchemy import Column, Integer, String, Enum, DateTime, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class EnglishLevel(enum.Enum):
    BEGINNER = "beginner"
    ELEMENTARY = "elementary"
    INTERMEDIATE = "intermediate"
    UPPER_INTERMEDIATE = "upper_intermediate"
    ADVANCED = "advanced"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, unique=True, index=True)
    name = Column(String)
    english_level = Column(Enum(EnglishLevel), nullable=True)
    study_plan = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_interaction = Column(DateTime(timezone=True), onupdate=func.now())
    assessment_completed = Column(Integer, default=0)  # 0: Not started, 1: In progress, 2: Completed
    
    # Relationships
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan") 