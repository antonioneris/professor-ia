from fastapi import APIRouter, Depends, HTTPException, Query, Security, Path
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database import get_db
from app.models.user import User
from app.models.conversation import Conversation, Message
from typing import List
from datetime import datetime
from pydantic import BaseModel, Field
import os

# Security configuration
API_KEY_NAME = "X-API-Key"
API_KEY = os.getenv("ADMIN_API_KEY", "professor_ai_webhook_verify_2024")  # Using the provided key
api_key_header = APIKeyHeader(name=API_KEY_NAME)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=401,
        detail="Invalid API Key",
        headers={"WWW-Authenticate": "ApiKey"},
    )

# Create router with explicit configuration
router = APIRouter(
    prefix="",  # Empty prefix since it's added in main.py
    tags=["admin"],
    dependencies=[Depends(get_api_key)],  # Apply authentication to all routes
    responses={401: {"description": "Invalid API Key"}},
)

# Test endpoint
@router.get("/test")
async def test_endpoint():
    return {"status": "ok", "message": "Admin router is working"}

class MessageResponse(BaseModel):
    """
    Represents a message in a conversation.
    """
    id: int = Field(..., description="Unique identifier for the message")
    message_type: str = Field(..., description="Type of message: 'incoming' (from user) or 'outgoing' (from system)")
    content: str = Field(..., description="Content of the message")
    timestamp: datetime = Field(..., description="When the message was sent/received")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "message_type": "incoming",
                "content": "Hello, I want to learn English",
                "timestamp": "2024-03-20T10:30:00Z"
            }
        }

class ConversationResponse(BaseModel):
    """
    Represents a conversation with a user.
    """
    id: int = Field(..., description="Unique identifier for the conversation")
    started_at: datetime = Field(..., description="When the conversation started")
    last_message_at: datetime | None = Field(None, description="When the last message was sent/received")
    status: str = Field(..., description="Status of the conversation: 'active', 'completed', or 'reset'")
    user_whatsapp_id: str = Field(..., description="WhatsApp ID of the user")
    user_name: str | None = Field(None, description="Name of the user if provided")
    user_english_level: str | None = Field(None, description="Current English level of the user")
    message_count: int = Field(..., description="Total number of messages in the conversation")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "started_at": "2024-03-20T10:00:00Z",
                "last_message_at": "2024-03-20T10:30:00Z",
                "status": "active",
                "user_whatsapp_id": "5517991234567",
                "user_name": "John Doe",
                "user_english_level": "intermediate",
                "message_count": 10
            }
        }

@router.get(
    "/conversations",
    response_model=List[ConversationResponse],
    summary="List All Conversations",
    description="""
    Retrieves a list of all conversations in the system.
    
    Each conversation includes:
    - Basic information about the conversation (ID, timestamps, status)
    - User information (WhatsApp ID, name, English level)
    - Message count
    
    The conversations can be filtered by status and sorted by date.
    
    Authentication required:
    - Include X-API-Key header with your API key
    """,
    responses={
        200: {
            "description": "List of conversations retrieved successfully",
            "content": {
                "application/json": {
                    "example": [{
                        "id": 1,
                        "started_at": "2024-03-20T10:00:00Z",
                        "last_message_at": "2024-03-20T10:30:00Z",
                        "status": "active",
                        "user_whatsapp_id": "5517991234567",
                        "user_name": "John Doe",
                        "user_english_level": "intermediate",
                        "message_count": 10
                    }]
                }
            }
        },
        401: {
            "description": "Invalid API Key"
        }
    }
)
async def list_conversations(
    status: str | None = Query(None, description="Filter conversations by status (active, completed, reset)"),
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(get_api_key)
):
    """List all conversations with basic information."""
    query = select(
        Conversation,
        User.whatsapp_id,
        User.name,
        User.english_level
    ).join(User)
    
    if status:
        query = query.where(Conversation.status == status)
    
    result = await db.execute(query)
    conversations = result.all()
    
    response = []
    for conv, whatsapp_id, name, level in conversations:
        # Count messages for this conversation
        msg_count = await db.execute(
            select(Message).where(Message.conversation_id == conv.id)
        )
        messages = msg_count.all()
        
        response.append(ConversationResponse(
            id=conv.id,
            started_at=conv.started_at,
            last_message_at=conv.last_message_at,
            status=conv.status,
            user_whatsapp_id=whatsapp_id,
            user_name=name,
            user_english_level=level.value if level else None,
            message_count=len(messages)
        ))
    
    return response

@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=List[MessageResponse],
    summary="Get Conversation Messages",
    description="""
    Retrieves all messages from a specific conversation.
    
    The messages are returned in chronological order and include:
    - Message ID
    - Type (incoming/outgoing)
    - Content
    - Timestamp
    
    Authentication required:
    - Include X-API-Key header with your API key
    """,
    responses={
        200: {
            "description": "Messages retrieved successfully",
            "content": {
                "application/json": {
                    "example": [{
                        "id": 1,
                        "message_type": "incoming",
                        "content": "Hello, I want to learn English",
                        "timestamp": "2024-03-20T10:30:00Z"
                    }]
                }
            }
        },
        401: {
            "description": "Invalid API Key"
        },
        404: {
            "description": "Conversation not found"
        }
    }
)
async def get_conversation_messages(
    conversation_id: int = Path(..., description="The ID of the conversation to retrieve messages from"),
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(get_api_key)
):
    """Get all messages from a specific conversation."""
    query = select(Message).where(
        Message.conversation_id == conversation_id
    ).order_by(Message.timestamp)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return messages

@router.post(
    "/conversations/{conversation_id}/reset",
    summary="Reset Conversation",
    description="""
    Resets a conversation and the user's assessment status.
    
    This will:
    1. Mark the current conversation as completed
    2. Clear the user's English level
    3. Reset the assessment progress
    4. Clear the study plan
    
    This allows the user to start fresh with a new assessment.
    
    Authentication required:
    - Include X-API-Key header with your API key
    """,
    responses={
        200: {
            "description": "Conversation reset successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "message": "Conversation reset successfully"
                    }
                }
            }
        },
        401: {
            "description": "Invalid API Key"
        },
        404: {
            "description": "Conversation not found"
        }
    }
)
async def reset_conversation(
    conversation_id: int = Path(..., description="The ID of the conversation to reset"),
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(get_api_key)
):
    """Reset a conversation, marking it as completed and clearing user's assessment."""
    async with db.begin():
        # Get conversation and user
        query = select(Conversation).where(Conversation.id == conversation_id)
        result = await db.execute(query)
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Update conversation status
        conversation.status = "completed"
        
        # Reset user's assessment
        user = await db.get(User, conversation.user_id)
        user.english_level = None
        user.assessment_completed = 0
        user.study_plan = None
        
        await db.commit()
    
    return {"status": "success", "message": "Conversation reset successfully"} 