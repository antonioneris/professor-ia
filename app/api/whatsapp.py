from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.whatsapp import WhatsAppService, WhatsAppPermissionError
from app.services.assessment import AssessmentService
from app.models.user import User, EnglishLevel
from app.models.conversation import Conversation, Message, MessageType
from sqlalchemy import select, func
from typing import Dict, Tuple, List
import json
import logging
from datetime import datetime
import aiohttp
import os
import base64
import uuid
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["WhatsApp Integration"],
    responses={404: {"description": "Not found"}},
)
whatsapp_service = WhatsAppService()
assessment_service = AssessmentService()

async def get_or_create_conversation(db: AsyncSession, user: User) -> Tuple[Conversation, bool]:
    """Get active conversation or create new one."""
    query = select(Conversation).where(
        Conversation.user_id == user.id,
        Conversation.status == "active"
    ).order_by(Conversation.started_at.desc())
    
    result = await db.execute(query)
    conversations = result.scalars().all()
    
    if not conversations:
        # No active conversations, create a new one
        conversation = Conversation(user_id=user.id)
        db.add(conversation)
        await db.flush()
        return conversation, True
    
    # If there are multiple active conversations, mark all but the most recent as completed
    if len(conversations) > 1:
        most_recent = conversations[0]
        for conv in conversations[1:]:
            conv.status = "completed"
        await db.flush()
        return most_recent, False
    
    # Return the single active conversation
    return conversations[0], False

async def store_message(db: AsyncSession, conversation: Conversation, content: str, message_type: MessageType):
    """Store a message in the database."""
    message = Message(
        conversation_id=conversation.id,
        content=content,
        message_type=message_type
    )
    db.add(message)
    await db.flush()
    return message

async def process_audio_message(audio_data: dict, user: User) -> str:
    """Process audio message and return transcription using OpenAI's Whisper API."""
    try:
        # Log the attempt to process audio
        logger.info(f"Starting audio processing with data: {json.dumps(audio_data, indent=2)}")
        
        # Get media ID from audio data
        media_id = audio_data.get("id")
        if not media_id:
            logger.error("No media ID in audio data")
            return "Error: No media ID found in audio message"
        
        # Create necessary directories
        debug_dir = "/tmp/audio_messages"
        os.makedirs(debug_dir, exist_ok=True)
        
        # Download the audio file using our endpoint
        try:
            # Get the host from environment or use default
            host = os.getenv('APP_HOST', 'localhost')
            port = os.getenv('APP_PORT', '8000')
            url = f"http://{host}:{port}/api/whatsapp/download-media/{media_id}"
            
            logger.info(f"Attempting to download audio from: {url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to download audio. Status: {response.status}, Response: {error_text}")
                        return f"Error: Failed to download audio - {error_text}"
                    
                    audio_content = await response.read()
                    content_type = response.headers.get("Content-Type", "application/octet-stream")
                    content_length = len(audio_content)
                    
                    logger.info(f"Successfully downloaded audio. Size: {content_length} bytes, Type: {content_type}")
                    
                    # Save audio content for debugging with proper extension
                    extension = "ogg" if "ogg" in content_type else "mp3" if "mp3" in content_type else "bin"
                    debug_path = f"{debug_dir}/message_{media_id}.{extension}"
                    
                    try:
                        with open(debug_path, "wb") as f:
                            f.write(audio_content)
                        
                        # Verify the file was saved
                        if os.path.exists(debug_path):
                            file_size = os.path.getsize(debug_path)
                            logger.info(f"Successfully saved audio to {debug_path} (size: {file_size} bytes)")
                        else:
                            logger.error(f"File not found after saving: {debug_path}")
                    except Exception as save_error:
                        logger.error(f"Error saving audio file: {str(save_error)}", exc_info=True)
                        # Continue with transcription even if save fails
                    
                    # Get OpenAI API key
                    openai_key = os.getenv('OPENAI_API_KEY')
                    if not openai_key:
                        logger.error("OpenAI API key not found in environment")
                        return "Error: OpenAI API key not configured"
                    
                    # Prepare the request to OpenAI's Whisper API
                    headers = {
                        "Authorization": f"Bearer {openai_key}",
                    }
                    
                    # Create form data with the audio file
                    form_data = aiohttp.FormData()
                    form_data.add_field(
                        'file',
                        audio_content,
                        filename=f'audio_{media_id}.{extension}',
                        content_type=content_type
                    )
                    form_data.add_field('model', 'whisper-1')
                    form_data.add_field('language', 'en' if user.english_level else 'pt')
                    form_data.add_field('response_format', 'json')
                    
                    logger.info("Sending transcription request to OpenAI Whisper API")
                    
                    async with session.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers=headers,
                        data=form_data,
                        timeout=30
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"API Response Status: {response.status}")
                        logger.info(f"API Response Headers: {dict(response.headers)}")
                        logger.info(f"API Response Body: {response_text}")
                        
                        if response.status != 200:
                            error_msg = f"Transcription failed - API returned status {response.status}"
                            if response_text:
                                try:
                                    error_data = json.loads(response_text)
                                    if "error" in error_data:
                                        error_msg += f": {error_data['error']['message']}"
                                except:
                                    error_msg += f" - Raw response: {response_text}"
                            logger.error(error_msg)
                            return f"Error: {error_msg}"
                        
                        try:
                            result = json.loads(response_text)
                        except json.JSONDecodeError as json_error:
                            logger.error(f"Failed to parse API response: {str(json_error)}")
                            return "Error: Invalid response from transcription API"
                        
                        logger.info(f"Transcription result: {json.dumps(result, indent=2)}")
                        
                        # Extract transcription
                        transcription = result.get("text", "").strip()
                        
                        if not transcription:
                            return "Error: No transcription received from the API"
                        
                        logger.info(f"Final transcription: {transcription}")
                        return transcription
                        
        except Exception as e:
            logger.error(f"Error processing audio: {str(e)}", exc_info=True)
            return f"Error: {str(e)}"
            
    except Exception as e:
        error_msg = f"Error processing audio: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return f"Error: {error_msg}"

async def generate_audio_response(text: str, user: User) -> str:
    """Generate audio response using OpenAI's Text-to-Speech API."""
    try:
        # Get OpenAI API key
        openai_key = os.getenv('OPENAI_API_KEY')
        if not openai_key:
            logger.error("OpenAI API key not found in environment")
            raise Exception("OpenAI API key not configured")
        
        # Get current working directory
        cwd = os.getcwd()
        logger.info(f"Current working directory: {cwd}")
        
        # Try multiple possible paths for audio directory
        possible_dirs = [
            os.path.join(cwd, "temp_audio"),  # Relative to CWD
            "/opt/traefik/professor-ia/temp_audio",  # Absolute path
            "/app/temp_audio",  # Docker container path
            "./temp_audio"  # Relative to script
        ]
        
        # Try to find or create a writable directory
        audio_dir = None
        for dir_path in possible_dirs:
            logger.info(f"Trying directory: {dir_path}")
            try:
                os.makedirs(dir_path, mode=0o777, exist_ok=True)
                # Test if we can write to this directory
                test_file = os.path.join(dir_path, "test.txt")
                try:
                    with open(test_file, 'w') as f:
                        f.write("test")
                    os.remove(test_file)
                    audio_dir = dir_path
                    logger.info(f"Found writable directory at: {dir_path}")
                    break
                except Exception as e:
                    logger.error(f"Directory not writable: {dir_path} - {str(e)}")
            except Exception as e:
                logger.error(f"Cannot create/access directory: {dir_path} - {str(e)}")
        
        if not audio_dir:
            logger.error("No writable directory found in any of the possible locations")
            raise Exception("Cannot find writable directory for audio files")
        
        # Generate a unique filename
        filename = f"response_{uuid.uuid4()}.mp3"
        filepath = os.path.join(audio_dir, filename)
        
        logger.info(f"Will save audio to: {filepath}")
        logger.info(f"Generating audio response for text: {text[:100]}...")
        
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            }
            
            # Prepare the request payload
            payload = {
                "model": "tts-1",
                "input": text,
                "voice": "alloy",
                "response_format": "mp3"
            }
            
            logger.info("Sending TTS request to OpenAI API")
            
            async with session.post(
                "https://api.openai.com/v1/audio/speech",
                headers=headers,
                json=payload,
                timeout=30
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to generate audio. Status: {response.status}, Response: {error_text}")
                    raise Exception(f"Failed to generate audio: {error_text}")
                
                # Get the audio content
                audio_content = await response.read()
                
                # Save the audio file with proper permissions
                try:
                    with open(filepath, "wb") as f:
                        f.write(audio_content)
                    # Set file permissions to be readable by all
                    os.chmod(filepath, 0o666)
                    logger.info(f"Successfully saved audio to {filepath} with permissions 666")
                    
                    # Verify the file was saved
                    if os.path.exists(filepath):
                        file_size = os.path.getsize(filepath)
                        stats = os.stat(filepath)
                        logger.info(f"Verified file saved: {filepath}")
                        logger.info(f"File size: {file_size} bytes")
                        logger.info(f"File permissions: {oct(stats.st_mode)}")
                        logger.info(f"File owner: {stats.st_uid}:{stats.st_gid}")
                    else:
                        logger.error(f"File not found after saving: {filepath}")
                        raise Exception("Failed to save audio file")
                except Exception as save_error:
                    logger.error(f"Error saving audio file: {str(save_error)}", exc_info=True)
                    raise Exception(f"Failed to save audio file: {str(save_error)}")
                
                # Get base URL from environment or use default
                base_url = os.getenv('APP_BASE_URL', 'https://professor.3ndigital.com.br/api/whatsapp')
                
                # Construct the audio URL using the correct path
                audio_url = f"{base_url}/audio/{filename}"
                logger.info(f"Audio URL generated: {audio_url}")
                
                return audio_url
                
    except Exception as e:
        logger.error(f"Error generating audio response: {str(e)}", exc_info=True)
        raise Exception(f"Failed to generate audio response: {str(e)}")

async def should_respond_with_audio(user: User, message_type: str, recent_messages: List[Message]) -> bool:
    """Determine if we should respond with audio."""
    # Respond with audio if:
    # 1. User sent an audio message
    # 2. User is practicing pronunciation
    # 3. Last few messages included audio
    if message_type == "audio":
        return True
        
    audio_count = sum(1 for msg in recent_messages[-3:] if "audio" in msg.content.lower())
    if audio_count >= 2:
        return True
        
    pronunciation_keywords = ["pronounce", "pronunciation", "speak", "say", "sound"]
    if any(keyword in recent_messages[-1].content.lower() for keyword in pronunciation_keywords):
        return True
        
    return False

@router.get(
    "/webhook",
    summary="Verify WhatsApp Webhook",
    description="""
    Verify webhook endpoint for WhatsApp API setup.
    
    This endpoint is used by WhatsApp to verify the webhook URL during setup.
    It implements the challenge-response verification protocol required by WhatsApp.
    
    The endpoint will:
    1. Verify the mode is 'subscribe'
    2. Validate the verification token
    3. Return the challenge string if verification is successful
    """,
    responses={
        200: {
            "description": "Webhook verified successfully",
            "content": {
                "application/json": {
                    "example": "1234567890"
                }
            }
        },
        403: {
            "description": "Invalid verification token"
        }
    }
)
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    logger.info(f"Webhook verification request - Mode: {mode}, Token: {token}, Challenge: {challenge}")
    
    if challenge := whatsapp_service.verify_webhook(mode, token, challenge):
        logger.info("Webhook verification successful")
        return int(challenge)
    
    logger.error("Webhook verification failed - Invalid token")
    raise HTTPException(status_code=403, detail="Invalid verification token")

@router.post(
    "/webhook",
    summary="Handle WhatsApp Messages",
    description="""
    Handle incoming WhatsApp messages and user interactions.
    
    This endpoint receives messages from WhatsApp and processes them based on the user's state:
    - For new users: Starts the assessment process
    - For users in assessment: Analyzes responses and determines English level
    - For existing users: Handles daily conversations and exercises
    
    The endpoint supports multiple message formats:
    1. Standard WhatsApp webhook format
    2. WhatsApp Business Account format
    3. Direct API message format
    
    Features:
    - User creation and management
    - English level assessment
    - Study plan generation
    - Interactive conversations
    """,
    responses={
        200: {
            "description": "Message processed successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "new_user": {
                            "summary": "New user response",
                            "value": {"status": "success", "action": "new_user_welcome"}
                        },
                        "assessment": {
                            "summary": "Assessment response",
                            "value": {"status": "success", "action": "assessment_in_progress"}
                        },
                        "completed": {
                            "summary": "Assessment completed",
                            "value": {"status": "success", "action": "assessment_completed"}
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid message format or processing error",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Invalid message format",
                        "message": "Message format not recognized"
                    }
                }
            }
        }
    }
)
async def webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Dict:
    try:
        # Log raw request details with better formatting
        headers = dict(request.headers)
        logger.info("==================== WEBHOOK REQUEST START ====================")
        logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        
        body = await request.json()
        logger.info(f"Raw payload: {json.dumps(body, indent=2)}")
        
        # Extract message data based on different possible formats
        message_data = None
        whatsapp_id = None
        message_text = None
        message_type = "text"
        audio_url = None
        conversation = None
        
        # Extract message data from webhook payload
        if "entry" in body and len(body["entry"]) > 0:
            entry = body["entry"][0]
            logger.info(f"Entry structure: {json.dumps(entry, indent=2)}")
            
            if "changes" in entry and len(entry["changes"]) > 0:
                changes = entry["changes"][0]
                logger.info(f"Changes structure: {json.dumps(changes, indent=2)}")
                
                if "value" in changes:
                    value = changes["value"]
                    logger.info(f"Value structure: {json.dumps(value, indent=2)}")
                    
                    if "messages" in value and len(value["messages"]) > 0:
                        message = value["messages"][0]
                        whatsapp_id = message.get("from")
                        message_data = message

        # Skip processing if no WhatsApp ID
        if not whatsapp_id:
            logger.info("Skipping processing - No WhatsApp ID")
            return {"status": "success", "action": "no_content"}

        # Get or create user
        async with db.begin():
            result = await db.execute(
                select(User).where(User.whatsapp_id == whatsapp_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                logger.info(f"New user detected: {whatsapp_id}")
                user = User(whatsapp_id=whatsapp_id)
                db.add(user)
                await db.flush()

            # Create or get conversation immediately
            conversation, is_new = await get_or_create_conversation(db, user)
            
            # Log message structure
            logger.info(f"Message structure: {json.dumps(message_data, indent=2)}")
            
            # Get message type and handle audio
            message_type = message_data.get("type", "text")
            logger.info(f"Message type from payload: {message_type}")
            
            if message_type == "text" and "text" in message_data:
                message_text = message_data["text"].get("body", "")
                logger.info("Detected text message")
            elif message_type == "audio" and "audio" in message_data:
                # Updated audio handling based on WhatsApp API documentation
                audio_data = message_data["audio"]
                audio_id = audio_data.get("id")
                mime_type = audio_data.get("mime_type")
                logger.info(f"Detected audio message. ID: {audio_id}, MIME Type: {mime_type}")
                logger.info(f"Full audio data: {json.dumps(audio_data, indent=2)}")
                
                # Process audio message
                try:
                    message_text = await process_audio_message(audio_data, user)
                    logger.info(f"Audio processing result: {message_text}")
                    
                    if message_text.startswith("Error:"):
                        error_msg = "Sorry, I couldn't process your audio message. Could you try again or type your message?"
                        await store_message(db, conversation, error_msg, MessageType.OUTGOING)
                        try:
                            whatsapp_service.send_message(whatsapp_id, error_msg)
                        except WhatsAppPermissionError as e:
                            logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
                        return JSONResponse(
                            status_code=200,
                            content={"status": "error", "action": "audio_processing_failed"}
                        )
                        
                    # For pronunciation practice, add specific feedback
                    if conversation.status == "active":
                        # Get recent messages to check context
                        context_query = select(Message).where(
                            Message.conversation_id == conversation.id
                        ).order_by(Message.timestamp.desc()).limit(3)
                        
                        context_result = await db.execute(context_query)
                        recent_messages = context_result.scalars().all()
                        
                        # Check if we're in pronunciation practice
                        is_pronunciation_practice = any(
                            "pronunciation" in msg.content.lower() or
                            "think vs sink" in msg.content.lower() or
                            "three vs tree" in msg.content.lower() or
                            "ship vs sheep" in msg.content.lower()
                            for msg in recent_messages
                        )
                        
                        if is_pronunciation_practice:
                            # Analyze pronunciation and provide feedback
                            feedback = (
                                "Thanks for practicing! 🎯\n\n"
                                f"I heard: '{message_text}'\n\n"
                                "Here's my feedback:\n"
                                "✓ Good attempt at the sounds!\n\n"
                                "Tips for improvement:\n"
                                "- Try placing your tongue between your teeth for 'th' sounds\n"
                                "- Make 'ee' longer in 'sheep' compared to 'ship'\n"
                                "- For 'three', make sure the 'th' and 'r' are distinct\n\n"
                                "Would you like to:\n"
                                "1. Try these words again\n"
                                "2. Practice different words\n"
                                "3. Move to sentence pronunciation\n"
                                "Just type the number of your choice!"
                            )
                            
                            await store_message(db, conversation, feedback, MessageType.OUTGOING)
                            try:
                                whatsapp_service.send_message(whatsapp_id, feedback)
                            except WhatsAppPermissionError as e:
                                logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
                            
                            await db.commit()
                            return JSONResponse(
                                status_code=200,
                                content={"status": "success", "action": "pronunciation_feedback_sent"}
                            )
                            
                except Exception as e:
                    logger.error(f"Error processing audio: {str(e)}", exc_info=True)
                    error_msg = "Sorry, I couldn't process your audio message. Could you try again or type your message?"
                    await store_message(db, conversation, error_msg, MessageType.OUTGOING)
                    try:
                        whatsapp_service.send_message(whatsapp_id, error_msg)
                    except WhatsAppPermissionError as e:
                        logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
                    return JSONResponse(
                        status_code=200,
                        content={"status": "error", "action": "audio_processing_failed"}
                    )
            else:
                logger.info(f"Unknown message type: {message_type}, Keys present: {list(message_data.keys())}")
                return JSONResponse(
                    status_code=200,
                    content={"status": "error", "action": "unknown_message_type"}
                )

            # Skip processing if no message content
            if not message_text:
                logger.info("Skipping processing - No message content")
                return {"status": "success", "action": "no_content"}

            # Create new conversation for new users
            if not user.english_level:
                # Check if this is the first interaction (no messages in conversation)
                message_count_query = select(func.count(Message.id)).where(
                    Message.conversation_id == conversation.id
                )
                result = await db.execute(message_count_query)
                message_count = result.scalar()
                
                if message_count == 0:
                    # This is a new user's first interaction
                    welcome_msg = (
                        "👋 Welcome to Professor AI - Your Personal English Teacher! 🌟\n\n"
                        "I'm here to help you improve your English skills through personalized lessons and conversations. "
                        "Before we start our journey together, I need to assess your current English level.\n\n"
                        "The assessment will consist of a few questions. Please answer them naturally in English - "
                        "you can use text or voice messages!\n\n"
                        "First, could you tell me your name?"
                    )
                    
                    await store_message(db, conversation, welcome_msg, MessageType.OUTGOING)
                    
                    try:
                        whatsapp_service.send_message(whatsapp_id, welcome_msg)
                    except WhatsAppPermissionError as e:
                        logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
                    except Exception as e:
                        logger.error(f"Error sending welcome message: {str(e)}")
                    
                    await db.commit()
                    return JSONResponse(
                        status_code=200,
                        content={"status": "success", "action": "new_user_welcome"}
                    )
                
                # Store incoming message first
                await store_message(db, conversation, message_text, MessageType.INCOMING)
                
                # Process the assessment response
                next_message, is_complete = await assessment_service.process_assessment_response(user, message_text)
                logger.info(f"Assessment response processed - Complete: {is_complete}, Next message: {next_message}")
                
                if is_complete:
                    # Mark all active conversations as completed
                    query = select(Conversation).where(
                        Conversation.user_id == user.id,
                        Conversation.status == "active"
                    )
                    result = await db.execute(query)
                    active_conversations = result.scalars().all()
                    for conv in active_conversations:
                        conv.status = "completed"
                    await db.flush()
                    
                    # Create a new conversation for regular lessons
                    new_conversation = Conversation(user_id=user.id)
                    db.add(new_conversation)
                    await db.flush()
                    
                    # Send completion message only once
                    completion_msg = (
                        f"🎉 Assessment completed! Your English level is: {user.english_level.value}\n\n"
                        "I've created a personalized study plan for you. Here's what you can expect:\n"
                        "- Daily conversations to practice English\n"
                        "- Grammar and vocabulary exercises\n"
                        "- Progress tracking and feedback\n"
                        "- Regular level assessments\n\n"
                        "Let's start our first lesson! Choose a topic:\n\n"
                        "1. Daily conversations (greetings, shopping, travel)\n"
                        "2. Grammar exercises\n"
                        "3. Vocabulary building\n"
                        "4. Pronunciation help\n"
                        "5. Writing practice\n\n"
                        "Just type the number or name of what you'd like to practice!"
                    )
                    
                    await store_message(db, new_conversation, completion_msg, MessageType.OUTGOING)
                    
                    try:
                        whatsapp_service.send_message(whatsapp_id, completion_msg)
                    except WhatsAppPermissionError as e:
                        logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
                    except Exception as e:
                        logger.error(f"Error sending completion message: {str(e)}")
                    
                    await db.commit()
                    return JSONResponse(
                        status_code=200,
                        content={"status": "success", "action": "assessment_completed"}
                    )
                else:
                    # Store and send the next assessment question
                    await store_message(db, conversation, next_message, MessageType.OUTGOING)
                    
                    try:
                        whatsapp_service.send_message(whatsapp_id, next_message)
                    except WhatsAppPermissionError as e:
                        logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
                    except Exception as e:
                        logger.error(f"Error sending next question: {str(e)}")
                    
                    await db.commit()
                    return JSONResponse(
                        status_code=200,
                        content={"status": "success", "action": "assessment_in_progress"}
                    )

            # Handle regular conversation mode
            logger.info(f"Processing message for existing user - Level: {user.english_level}")
            
            # Store incoming message
            await store_message(db, conversation, message_text, MessageType.INCOMING)
            
            # Check if this is a topic selection only for recent assessment completions
            is_topic_selection = False
            
            # Get the last few messages to check if we just completed assessment
            recent_messages_query = select(Message).where(
                Message.conversation_id == conversation.id
            ).order_by(Message.timestamp.desc()).limit(3)
            
            recent_result = await db.execute(recent_messages_query)
            recent_messages = recent_result.scalars().all()
            
            # Check if the last outgoing message was the assessment completion message
            if recent_messages:
                last_outgoing = None
                for msg in recent_messages:
                    if msg.message_type == MessageType.OUTGOING:
                        last_outgoing = msg
                        break
                
                if last_outgoing and "Assessment completed" in last_outgoing.content:
                    # This might be a topic selection
                    topic_selection = message_text.strip().lower()
                    
                    # Map both numbers and text to topics
                    topic_map = {
                        "1": "daily_conversations",
                        "2": "grammar",
                        "3": "vocabulary",
                        "4": "pronunciation",
                        "5": "writing",
                        "daily": "daily_conversations",
                        "conversations": "daily_conversations",
                        "grammar": "grammar",
                        "vocabulary": "vocabulary",
                        "pronunciation": "pronunciation",
                        "writing": "writing"
                    }
                    
                    selected_topic = None
                    for key, value in topic_map.items():
                        if key in topic_selection:
                            selected_topic = value
                            is_topic_selection = True
                            break
                    
                    if selected_topic:
                        # Handle pronunciation practice
                        if selected_topic == "pronunciation":
                            response = (
                                "Great choice! Let's work on your pronunciation. 🗣️\n\n"
                                "I'll help you improve your pronunciation through:\n"
                                "1. Word-by-word practice\n"
                                "2. Sentence rhythm and intonation\n"
                                "3. Common sound pairs\n\n"
                                "Let's start with some common words that English learners often find challenging.\n\n"
                                "Please say these words (you can send an audio message):\n"
                                "- 'Think' vs 'Sink'\n"
                                "- 'Three' vs 'Tree'\n"
                                "- 'Ship' vs 'Sheep'\n\n"
                                "I'll listen and give you feedback on your pronunciation!"
                            )
                        elif selected_topic == "daily_conversations":
                            response = (
                                "Let's practice daily conversations! 💬\n\n"
                                "We'll focus on common situations like:\n"
                                "- Ordering food\n"
                                "- Shopping\n"
                                "- Asking for directions\n\n"
                                "Let's start with introductions. How would you introduce yourself to someone you just met?"
                            )
                        elif selected_topic == "grammar":
                            response = (
                                "Time to improve your grammar! 📚\n\n"
                                "We'll work on:\n"
                                "- Present tense\n"
                                "- Past tense\n"
                                "- Question formation\n\n"
                                "Let's start with a simple exercise. Complete this sentence:\n"
                                "Yesterday, I _____ (go) to the store."
                            )
                        elif selected_topic == "vocabulary":
                            response = (
                                "Let's expand your vocabulary! 📖\n\n"
                                "We'll learn new words through:\n"
                                "- Themes and categories\n"
                                "- Context and usage\n"
                                "- Word families\n\n"
                                "Today's theme is 'Food and Cooking'\n"
                                "What are some foods you like to cook?"
                            )
                        elif selected_topic == "writing":
                            response = (
                                "Let's improve your writing skills! ✍️\n\n"
                                "We'll practice:\n"
                                "- Sentence structure\n"
                                "- Paragraph organization\n"
                                "- Email writing\n\n"
                                "Let's start with a simple task:\n"
                                "Write 3-4 sentences about your favorite hobby."
                            )
                        
                        await store_message(db, conversation, response, MessageType.OUTGOING)
                        
                        try:
                            whatsapp_service.send_message(whatsapp_id, response)
                        except WhatsAppPermissionError as e:
                            logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
                        except Exception as e:
                            logger.error(f"Error sending topic response: {str(e)}")
                        
                        await db.commit()
                        return JSONResponse(
                            status_code=200,
                            content={"status": "success", "action": "topic_selected"}
                        )
            
            # If no topic was selected or this is regular conversation, generate AI response
            logger.info(f"Generating AI response for message: {message_text}")
            response_text = await generate_ai_response(user, message_text, conversation, db)
            logger.info(f"Generated AI response: {response_text[:100]}...")
            
            await store_message(db, conversation, response_text, MessageType.OUTGOING)
            
            # Check if we should respond with audio
            recent_messages_query = select(Message).where(
                Message.conversation_id == conversation.id
            ).order_by(Message.timestamp.desc()).limit(5)
            
            recent_result = await db.execute(recent_messages_query)
            recent_messages = recent_result.scalars().all()
            
            should_audio = await should_respond_with_audio(user, message_type, recent_messages)
            logger.info(f"Should respond with audio: {should_audio}")
            
            try:
                if should_audio:
                    # Generate and send audio response
                    logger.info("Generating audio response...")
                    audio_url = await generate_audio_response(response_text, user)
                    whatsapp_service.send_audio(whatsapp_id, audio_url)
                    logger.info(f"Sent audio response: {audio_url}")
                else:
                    # Send text response
                    logger.info("Sending text response...")
                    whatsapp_service.send_message(whatsapp_id, response_text)
                    logger.info(f"Sent text response: {response_text[:50]}...")
                    
            except WhatsAppPermissionError as e:
                logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
            except Exception as e:
                logger.error(f"Error sending response: {str(e)}")
            
            await db.commit()
            return JSONResponse(
                status_code=200,
                content={"status": "success", "action": "conversation_processed"}
            )

    except WhatsAppPermissionError as e:
        # This is expected during development
        logger.warning(f"WhatsApp permission error (expected during development): {str(e)}")
        return JSONResponse(
            status_code=200,  # Return 200 to acknowledge receipt
            content={"status": "success", "action": "message_stored_only"}
        )
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "message": "Failed to process WhatsApp message"}
        )

@router.get("/download-media/{media_id}")
async def download_media(media_id: str):
    """Download media from WhatsApp."""
    try:
        # WhatsApp Media API endpoint
        api_version = os.getenv('WHATSAPP_API_VERSION', 'v17.0')
        media_endpoint = f"https://graph.facebook.com/{api_version}/{media_id}"
        
        # Get WhatsApp token from environment
        whatsapp_token = os.getenv('WHATSAPP_TOKEN')
        if not whatsapp_token:
            logger.error("WhatsApp token not found in environment")
            raise HTTPException(status_code=500, detail="WhatsApp token not configured")
        
        headers = {
            "Authorization": f"Bearer {whatsapp_token}"
        }
        
        logger.info(f"Starting media download process for ID: {media_id}")
        logger.info(f"Using WhatsApp API version: {api_version}")
        logger.info(f"Using endpoint: {media_endpoint}")
        
        async with aiohttp.ClientSession() as session:
            # First get the media URL
            logger.info("Step 1: Getting media URL from WhatsApp API")
            async with session.get(media_endpoint, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to get media URL. Status: {response.status}, Response: {error_text}")
                    raise HTTPException(status_code=400, detail=f"Failed to get media URL: {error_text}")
                
                media_info = await response.json()
                logger.info(f"Media info received: {json.dumps(media_info, indent=2)}")
                
                if "url" not in media_info:
                    logger.error(f"No URL in media info: {json.dumps(media_info, indent=2)}")
                    raise HTTPException(status_code=400, detail="No media URL found in response")
                
                media_url = media_info["url"]
                logger.info(f"Media URL obtained: {media_url}")
                
                # Now download the actual media with the same token
                logger.info("Step 2: Downloading media content")
                async with session.get(media_url, headers=headers) as media_response:
                    if media_response.status != 200:
                        error_text = await media_response.text()
                        logger.error(f"Failed to download media. Status: {media_response.status}, Response: {error_text}")
                        raise HTTPException(status_code=400, detail=f"Failed to download media: {error_text}")
                    
                    content = await media_response.read()
                    content_length = len(content)
                    content_type = media_response.headers.get("Content-Type", "application/octet-stream")
                    
                    logger.info(f"Successfully downloaded media content. Size: {content_length} bytes, Type: {content_type}")
                    
                    # Save the media file for debugging
                    debug_dir = "/tmp/whatsapp_media"
                    os.makedirs(debug_dir, exist_ok=True)
                    debug_path = f"{debug_dir}/{media_id}"
                    
                    try:
                        with open(debug_path, "wb") as f:
                            f.write(content)
                        logger.info(f"Successfully saved media to {debug_path}")
                        
                        # Verify the file was saved
                        if os.path.exists(debug_path):
                            file_size = os.path.getsize(debug_path)
                            logger.info(f"Verified file saved: {debug_path} (size: {file_size} bytes)")
                        else:
                            logger.error(f"File not found after saving: {debug_path}")
                    except Exception as save_error:
                        logger.error(f"Error saving media file: {str(save_error)}", exc_info=True)
                        # Continue even if save fails - we still want to return the content
                    
                    # Return the content with proper content type
                    return Response(
                        content=content,
                        media_type=content_type,
                        headers={
                            "Content-Length": str(content_length),
                            "Content-Disposition": f'attachment; filename="whatsapp_media_{media_id}"'
                        }
                    )

    except Exception as e:
        logger.error(f"Error in download_media: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/audio/{filename}")
async def get_audio(filename: str):
    """Serve audio files."""
    try:
        # Sanitize filename to prevent directory traversal
        if ".." in filename or "/" in filename:
            logger.error(f"Invalid filename attempted: {filename}")
            raise HTTPException(status_code=400, detail="Invalid filename")
            
        # Get current working directory
        cwd = os.getcwd()
        logger.info(f"Current working directory: {cwd}")
        
        # Try multiple possible paths
        possible_paths = [
            os.path.join(cwd, "temp_audio", filename),  # Relative to CWD
            os.path.join("/opt/traefik/professor-ia/temp_audio", filename),  # Absolute path
            os.path.join("/app/temp_audio", filename),  # Docker container path
            "./temp_audio/" + filename  # Relative to script
        ]
        
        filepath = None
        for path in possible_paths:
            logger.info(f"Trying path: {path}")
            if os.path.exists(path):
                filepath = path
                logger.info(f"Found file at: {path}")
                break
        
        if not filepath:
            logger.error("File not found in any of the possible locations:")
            for path in possible_paths:
                logger.error(f"  - {path}")
            raise HTTPException(status_code=404, detail="Audio file not found")
        
        # Get file stats
        try:
            stats = os.stat(filepath)
            logger.info(f"File stats:")
            logger.info(f"  Size: {stats.st_size} bytes")
            logger.info(f"  Permissions: {oct(stats.st_mode)}")
            logger.info(f"  Owner: {stats.st_uid}:{stats.st_gid}")
            logger.info(f"  Created: {datetime.fromtimestamp(stats.st_ctime)}")
            logger.info(f"  Modified: {datetime.fromtimestamp(stats.st_mtime)}")
        except Exception as e:
            logger.error(f"Error getting file stats: {str(e)}")
        
        # Try to open and read the file
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
                logger.info(f"Successfully read file content, size: {len(content)} bytes")
                
                return Response(
                    content=content,
                    media_type="audio/mpeg",
                    headers={
                        "Content-Length": str(len(content)),
                        "Content-Disposition": f'attachment; filename="{filename}"',
                        "Cache-Control": "public, max-age=3600"
                    }
                )
        except Exception as e:
            logger.error(f"Error reading file: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error reading audio file: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error serving audio file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def get_user_preferences(db: AsyncSession, user: User) -> dict:
    """Get user's learning preferences from conversation history."""
    try:
        # Get recent messages to analyze preferences
        query = select(Message).join(Conversation).where(
            Conversation.user_id == user.id
        ).order_by(Message.timestamp.desc()).limit(50)
        
        result = await db.execute(query)
        messages = result.scalars().all()
        
        preferences = {
            'interests': set(),
            'learning_style': 'visual',  # default
            'favorite_topics': set(),
            'challenging_areas': set()
        }
        
        # Analyze messages for preferences
        for msg in messages:
            content = msg.content.lower()
            
            # Check for interests in media
            if any(word in content for word in ['movie', 'film', 'series', 'show']):
                preferences['interests'].add('movies')
            if any(word in content for word in ['music', 'song', 'sing']):
                preferences['interests'].add('music')
                
            # Detect learning style
            if any(word in content for word in ['see', 'watch', 'look']):
                preferences['learning_style'] = 'visual'
            elif any(word in content for word in ['hear', 'listen', 'sound']):
                preferences['learning_style'] = 'auditory'
            
            # Identify challenging areas
            if 'difficult' in content or 'hard' in content:
                for area in ['grammar', 'vocabulary', 'pronunciation', 'listening']:
                    if area in content:
                        preferences['challenging_areas'].add(area)
        
        return preferences
    except Exception as e:
        logger.error(f"Error getting user preferences: {str(e)}")
        return {'interests': set(), 'learning_style': 'visual', 'favorite_topics': set(), 'challenging_areas': set()}

async def generate_ai_response(user: User, user_message: str, conversation: Conversation, db: AsyncSession) -> str:
    """Generate AI response using DeepSeek or OpenAI based on user context."""
    try:
        # Get conversation history for context
        history_query = select(Message).where(
            Message.conversation_id == conversation.id
        ).order_by(Message.timestamp.desc()).limit(10)
        
        history_result = await db.execute(history_query)
        history_messages = list(reversed(history_result.scalars().all()))
        
        # Build conversation context
        context = f"User English Level: {user.english_level.value if user.english_level else 'Unknown'}\n\n"
        context += "Conversation History:\n"
        
        for msg in history_messages[-5:]:  # Last 5 messages for context
            role = "User" if msg.message_type == MessageType.INCOMING else "AI"
            context += f"{role}: {msg.content}\n"
        
        # Create prompt for AI
        system_prompt = f"""You are Professor AI, a friendly and professional English teacher. 
        
        Student Profile:
        - English Level: {user.english_level.value if user.english_level else 'Beginner'}
        - Learning Goals: Improve English through conversation practice
        
        Guidelines:
        1. Always respond in English
        2. Adjust your language complexity to match the student's level
        3. Provide corrections and explanations when needed
        4. Be encouraging and supportive
        5. Ask follow-up questions to maintain engagement
        6. Include practical examples and exercises when appropriate
        7. For pronunciation topics, provide specific phonetic guidance
        8. Keep responses concise but helpful (max 200 words)
        
        Current conversation context:
        {context}
        
        Student's latest message: {user_message}
        
        Respond as Professor AI, helping the student improve their English:"""
        
        # Try DeepSeek first, then OpenAI as fallback
        deepseek_key = os.getenv('DEEPSEEK_API_KEY')
        openai_key = os.getenv('OPENAI_API_KEY')
        
        if deepseek_key:
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {
                        "Authorization": f"Bearer {deepseek_key}",
                        "Content-Type": "application/json"
                    }
                    
                    payload = {
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        "max_tokens": 300,
                        "temperature": 0.7
                    }
                    
                    async with session.post(
                        "https://api.deepseek.com/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=30
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            ai_response = result["choices"][0]["message"]["content"].strip()
                            logger.info(f"Generated DeepSeek response: {ai_response[:100]}...")
                            return ai_response
                        else:
                            error_text = await response.text()
                            logger.error(f"DeepSeek API error: {response.status} - {error_text}")
                            
            except Exception as e:
                logger.error(f"Error with DeepSeek API: {str(e)}")
        
        # Fallback to OpenAI
        if openai_key:
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json"
                    }
                    
                    payload = {
                        "model": "gpt-3.5-turbo",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        "max_tokens": 300,
                        "temperature": 0.7
                    }
                    
                    async with session.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=30
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            ai_response = result["choices"][0]["message"]["content"].strip()
                            logger.info(f"Generated OpenAI response: {ai_response[:100]}...")
                            return ai_response
                        else:
                            error_text = await response.text()
                            logger.error(f"OpenAI API error: {response.status} - {error_text}")
                            
            except Exception as e:
                logger.error(f"Error with OpenAI API: {str(e)}")
        
        # Fallback response if both APIs fail
        level_responses = {
            EnglishLevel.BEGINNER: "Thank you for your message! I'm here to help you learn English. Can you tell me more about what you want to practice today?",
            EnglishLevel.ELEMENTARY: "That's interesting! I'd like to help you improve your English. What specific areas would you like to work on?",
            EnglishLevel.INTERMEDIATE: "Great! I appreciate you sharing that with me. How can I help you practice English today? Would you like to focus on conversation, grammar, or vocabulary?",
            EnglishLevel.ADVANCED: "Excellent! I can see you have good English skills. Let's continue our conversation and work on refining your language abilities. What topics interest you most?"
        }
        
        fallback_response = level_responses.get(user.english_level, level_responses[EnglishLevel.BEGINNER])
        logger.info(f"Using fallback response: {fallback_response}")
        return fallback_response
        
    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}", exc_info=True)
        return "I'm sorry, I'm having trouble processing your message right now. Could you please try again?"