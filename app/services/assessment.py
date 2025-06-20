from typing import Dict, List, Optional, Tuple
from app.models.user import EnglishLevel
import json
import os
import aiohttp
from app.services.whatsapp import WhatsAppService

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

            Provide the level only as a single word response.
            """

            async with session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}]
                }
            ) as response:
                result = await response.json()
                level_str = result["choices"][0]["message"]["content"].strip().upper()
                return EnglishLevel[level_str]

    async def process_assessment_response(self, user: 'User', message_text: str) -> Tuple[str, bool]:
        """
        Process a user's response during the assessment phase.
        Returns a tuple of (next_message, is_assessment_complete)
        """
        questions_answered = user.assessment_completed or 0
        
        # Analyze response if we have enough data
        if questions_answered >= self.min_questions_for_assessment:
            level = await self.analyze_response(message_text, questions_answered)
            
            if level:
                user.english_level = level
                study_plan = await self.generate_study_plan(level)
                user.study_plan = study_plan
                user.assessment_completed = questions_answered + 1
                
                response = (
                    f"Based on your responses, your English level is: {level.value.upper()}\n\n"
                    "I've created a personalized study plan for you. "
                    "We'll have daily conversations to improve your English skills.\n\n"
                    "Let's start with our first lesson tomorrow! 🚀"
                )
                return response, True
        
        # Get next question if assessment not complete
        next_question = self.get_next_assessment_question(
            EnglishLevel.BEGINNER if questions_answered < 2 else EnglishLevel.INTERMEDIATE,
            questions_answered
        )
        
        if next_question:
            user.assessment_completed = questions_answered + 1
            return next_question, False
        
        # Fallback response if something goes wrong
        return "I'm analyzing your responses to determine your English level...", False

    async def generate_study_plan(self, user_level: EnglishLevel) -> str:
        """Generate a personalized study plan based on the user's English level."""
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
                    "messages": [{"role": "user", "content": prompt}]
                }
            ) as response:
                result = await response.json()
                return result["choices"][0]["message"]["content"] 