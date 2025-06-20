from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.assessment import AssessmentService
from app.models.user import User
from sqlalchemy import select
from typing import Dict
from pydantic import BaseModel
import json

router = APIRouter()
assessment_service = AssessmentService()

class UserLevelResponse(BaseModel):
    """Response model for user level information."""
    whatsapp_id: str
    english_level: str | None
    assessment_completed: int

    class Config:
        schema_extra = {
            "example": {
                "whatsapp_id": "1234567890",
                "english_level": "intermediate",
                "assessment_completed": 2
            }
        }

class StudyPlanResponse(BaseModel):
    """Response model for study plan information."""
    whatsapp_id: str
    english_level: str | None
    study_plan: dict

    class Config:
        schema_extra = {
            "example": {
                "whatsapp_id": "1234567890",
                "english_level": "intermediate",
                "study_plan": {
                    "weekly_plans": [
                        {
                            "week": 1,
                            "focus_points": ["Present Perfect", "Business Vocabulary"],
                            "daily_topics": [
                                "Introduction to Business English",
                                "Email Writing",
                                "Phone Conversations",
                                "Meeting Vocabulary",
                                "Presentation Skills"
                            ],
                            "grammar": "Present Perfect in Business Context",
                            "vocabulary": "Office and Business Terms",
                            "activities": [
                                "Role-play business meetings",
                                "Write professional emails"
                            ]
                        }
                    ]
                }
            }
        }

@router.get(
    "/user/{whatsapp_id}/level",
    response_model=UserLevelResponse,
    summary="Get User's English Level"
)
async def get_user_level(whatsapp_id: str, db: AsyncSession = Depends(get_db)) -> Dict:
    """
    Retrieve the current English level of a user.
    
    This endpoint returns detailed information about a user's English proficiency level
    and assessment status.
    
    Parameters:
    - **whatsapp_id**: The WhatsApp ID of the user
    
    Returns:
    - User level information including:
        - WhatsApp ID
        - Current English level (if assessed)
        - Assessment completion status
    
    Raises:
    - 404: If user is not found
    """
    async with db.begin():
        result = await db.execute(
            select(User).where(User.whatsapp_id == whatsapp_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail={"error": "User not found", "whatsapp_id": whatsapp_id}
            )
        
        return {
            "whatsapp_id": user.whatsapp_id,
            "english_level": user.english_level.value if user.english_level else None,
            "assessment_completed": user.assessment_completed
        }

@router.get(
    "/user/{whatsapp_id}/study-plan",
    response_model=StudyPlanResponse,
    summary="Get User's Study Plan"
)
async def get_study_plan(whatsapp_id: str, db: AsyncSession = Depends(get_db)) -> Dict:
    """
    Retrieve the personalized study plan for a user.
    
    This endpoint returns the detailed study plan generated for the user based on their
    assessed English level. The study plan includes weekly objectives, daily topics,
    and suggested activities.
    
    Parameters:
    - **whatsapp_id**: The WhatsApp ID of the user
    
    Returns:
    - Complete study plan including:
        - WhatsApp ID
        - Current English level
        - Detailed weekly plans with:
            - Focus points
            - Daily topics
            - Grammar focus
            - Vocabulary themes
            - Suggested activities
    
    Raises:
    - 404: If user is not found or study plan hasn't been generated yet
    """
    async with db.begin():
        result = await db.execute(
            select(User).where(User.whatsapp_id == whatsapp_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail={"error": "User not found", "whatsapp_id": whatsapp_id}
            )
        
        if not user.study_plan:
            raise HTTPException(
                status_code=404,
                detail={"error": "Study plan not found", "whatsapp_id": whatsapp_id}
            )
        
        return {
            "whatsapp_id": user.whatsapp_id,
            "english_level": user.english_level.value if user.english_level else None,
            "study_plan": json.loads(user.study_plan)
        } 