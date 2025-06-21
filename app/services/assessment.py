from typing import Dict, List, Optional, Tuple
from app.models.user import EnglishLevel
import json
import os
import aiohttp
import logging
from app.services.whatsapp import WhatsAppService

logger = logging.getLogger(__name__)

class AssessmentService:
    def __init__(self):
        self.whatsapp = WhatsAppService()
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.assessment_questions = self._load_assessment_questions()
        self.min_questions_for_assessment = 3  # Minimum questions needed for level assessment

    def _load_assessment_questions(self) -> Dict:
        """Load assessment questions from predefined structure."""
        return {
            EnglishLevel.BEGINNER: [
                "What's your name?",
                "How are you today?",
                "Where are you from?",
                "What do you do for work or study?",
                "Do you like learning English? Why?"
            ],
            EnglishLevel.ELEMENTARY: [
                "What do you like to do in your free time?",
                "Can you describe your daily routine?",
                "What kind of movies do you enjoy watching?",
                "Tell me about your family.",
                "What are your hobbies?"
            ],
            EnglishLevel.INTERMEDIATE: [
                "What are your thoughts on climate change?",
                "How would you describe your ideal job?",
                "What changes would you like to see in your city?",
                "What's the most interesting place you've visited?",
                "What are your goals for learning English?"
            ],
            EnglishLevel.ADVANCED: [
                "Could you elaborate on the implications of artificial intelligence in modern society?",
                "What are the most pressing challenges facing global education today?",
                "How do you think technology will shape the future of work?",
                "Discuss the role of social media in modern society.",
                "What measures could be taken to address environmental issues?"
            ]
        }

    def get_next_assessment_question(self, current_level: EnglishLevel, questions_answered: int = 0) -> str:
        """Get the next assessment question based on the current level and progress."""
        questions = self.assessment_questions[current_level]
        if questions_answered >= len(questions):
            return None
        
        next_question = questions[questions_answered]
        remaining = len(questions) - questions_answered
        
        if remaining > 1:
            return f"{next_question}\n\n(Question {questions_answered + 1} of {len(questions)})"
        else:
            return f"{next_question}\n\n(Final question! After this, I'll assess your English level.)"

    async def analyze_response(self, user_response: str, questions_answered: int) -> Optional[EnglishLevel]:
        """Analyze user response and determine if enough data for final assessment."""
        if questions_answered < self.min_questions_for_assessment:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.deepseek_api_key}",
                    "Content-Type": "application/json"
                }
                
                prompt = f"""
                Analyze the following English response and determine the user's English level 
                (BEGINNER, ELEMENTARY, INTERMEDIATE, UPPER_INTERMEDIATE, or ADVANCED) 
                based on grammar, vocabulary, and complexity:

                User response: {user_response}

                Consider:
                - Grammar accuracy and complexity
                - Vocabulary range and appropriateness
                - Sentence structure
                - Overall fluency

                Respond with only one of these exact words: BEGINNER, ELEMENTARY, INTERMEDIATE, UPPER_INTERMEDIATE, ADVANCED
                """

                async with session.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 50,
                        "temperature": 0.3
                    },
                    timeout=30
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        level_str = result["choices"][0]["message"]["content"].strip().upper()
                        
                        # Map the response to valid enum values
                        level_mapping = {
                            "BEGINNER": EnglishLevel.BEGINNER,
                            "ELEMENTARY": EnglishLevel.ELEMENTARY,
                            "INTERMEDIATE": EnglishLevel.INTERMEDIATE,
                            "UPPER_INTERMEDIATE": EnglishLevel.UPPER_INTERMEDIATE,
                            "ADVANCED": EnglishLevel.ADVANCED
                        }
                        
                        return level_mapping.get(level_str, EnglishLevel.INTERMEDIATE)
                    else:
                        # Fallback: basic level assessment based on response length and complexity
                        return self._fallback_level_assessment(user_response)
                        
        except Exception as e:
            # Fallback assessment if API fails
            return self._fallback_level_assessment(user_response)
    
    def _fallback_level_assessment(self, response: str) -> EnglishLevel:
        """Simple fallback assessment based on response characteristics."""
        words = response.split()
        word_count = len(words)
        
        # Simple heuristics
        if word_count < 5:
            return EnglishLevel.BEGINNER
        elif word_count < 15:
            return EnglishLevel.ELEMENTARY
        elif word_count < 30:
            return EnglishLevel.INTERMEDIATE
        else:
            return EnglishLevel.UPPER_INTERMEDIATE

    async def process_assessment_response(self, user: 'User', message_text: str) -> Tuple[str, bool]:
        """
        Process a user's response during the assessment phase.
        Returns a tuple of (next_message, is_assessment_complete)
        """
        questions_answered = user.assessment_completed or 0
        
        # Increment questions answered
        user.assessment_completed = questions_answered + 1
        
        # Check if we have enough responses for assessment
        if user.assessment_completed >= self.min_questions_for_assessment:
            try:
                level = await self.analyze_response(message_text, user.assessment_completed)
                
                if level:
                    user.english_level = level
                    study_plan = await self.generate_study_plan(level)
                    user.study_plan = study_plan
                    
                    response = (
                        f"🎉 Assessment completed! Your English level is: {level.value.upper()}\n\n"
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
                    return response, True
            except Exception as e:
                # Continue with one more question if analysis fails
                pass
        
        # Get next question if assessment not complete
        # Use progressive difficulty
        if user.assessment_completed <= 2:
            current_level = EnglishLevel.BEGINNER
        elif user.assessment_completed <= 4:
            current_level = EnglishLevel.ELEMENTARY
        else:
            current_level = EnglishLevel.INTERMEDIATE
            
        next_question = self.get_next_assessment_question(current_level, user.assessment_completed - 1)
        
        if next_question:
            return next_question, False
        
        # If we run out of questions, complete assessment with fallback
        level = self._fallback_level_assessment(message_text)
        user.english_level = level
        study_plan = await self.generate_study_plan(level)
        user.study_plan = study_plan
        
        response = (
            f"🎉 Assessment completed! Your English level is: {level.value.upper()}\n\n"
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
        return response, True

    async def generate_study_plan(self, user_level: EnglishLevel) -> str:
        """Generate a personalized study plan based on the user's English level."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.deepseek_api_key}",
                    "Content-Type": "application/json"
                }
                
                prompt = f"""
                Create a personalized 30-day English study plan for a {user_level.value} level student.
                Include:
                - Daily conversation topics
                - Grammar focus points
                - Vocabulary themes
                - Suggested activities
                - Weekly goals

                Format the response as a JSON string with the following structure:
                {{
                    "weekly_plans": [
                        {{
                            "week": 1,
                            "focus_points": ["point1", "point2"],
                            "daily_topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
                            "grammar": "focus area",
                            "vocabulary": "theme",
                            "activities": ["activity1", "activity2"]
                        }}
                    ]
                }}
                """

                async with session.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1000,
                        "temperature": 0.7
                    },
                    timeout=30
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result["choices"][0]["message"]["content"]
                    else:
                        return self._get_default_study_plan(user_level)
                        
        except Exception as e:
            return self._get_default_study_plan(user_level)
    
    def _get_default_study_plan(self, user_level: EnglishLevel) -> str:
        """Get a default study plan if API fails."""
        plans = {
            EnglishLevel.BEGINNER: {
                "focus": "Basic vocabulary and simple sentences",
                "activities": ["Daily greetings", "Numbers and colors", "Family members", "Basic verbs"]
            },
            EnglishLevel.ELEMENTARY: {
                "focus": "Present tense and everyday conversations",
                "activities": ["Shopping dialogues", "Describing daily routine", "Asking questions", "Time expressions"]
            },
            EnglishLevel.INTERMEDIATE: {
                "focus": "Past and future tenses, complex sentences",
                "activities": ["Storytelling", "Expressing opinions", "Travel conversations", "Work discussions"]
            },
            EnglishLevel.UPPER_INTERMEDIATE: {
                "focus": "Advanced grammar and fluent conversation",
                "activities": ["Debates", "News discussions", "Academic writing", "Professional communication"]
            },
            EnglishLevel.ADVANCED: {
                "focus": "Refining skills and cultural nuances",
                "activities": ["Literary discussions", "Complex presentations", "Idioms and slang", "Advanced writing"]
            }
        }
        
        plan = plans.get(user_level, plans[EnglishLevel.BEGINNER])
        return json.dumps({
            "level": user_level.value,
            "focus": plan["focus"],
            "activities": plan["activities"],
            "generated": "default"
        }) 