import logging
import os


from langchain_core.chat_models import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain.schema import SystemMessage, HumanMessage
from main.models import ChatHistory

logger = logging.getLogger(__name__)


class MathProblemInput(BaseModel):
    question: str = Field(description="The math problem to solve")
    approach: Optional[str] = Field(default="auto", description="The approach to use for solving")

class MathAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            temperature=0.2,
            model="gpt-4o",
            max_tokens=1000,
            api_key=os.getenv('OPENAI_API_KEY'),
            top_p=0.9,
            
        )
        self.chat_history = []
        self.max_history = 100
        self.tools = self._create_tools()
        self.interaction_prompts = {
            'explain': "Explain the concept in detail with examples.",
            'solve': "Solve this problem step by step.",
            'general': "Respond naturally to the query.",
        }

    def _create_tools(self) -> Dict[str, str]:
        return {
            "step_by_step": """Break down the problem into clear steps:
                1. Identify key components
                2. Apply relevant formulas
                3. Show calculations
                4. Explain each step""",
                
            "basics": """Explain fundamental concepts:
                1. Core mathematical principles
                2. Required formulas
                3. Key definitions
                4. Prerequisites""",
                
            "examples": """Provide similar problems:
                1. Solved example
                2. Step-by-step solution
                3. Variations of the problem
                4. Practice problems""",
                
            "mistakes": """Analyze common errors:
                1. Typical mistakes
                2. Why they occur
                3. How to avoid them
                4. Verification steps"""
        }

    def _detect_approach(self, question: str) -> str:
        """Automatically detect the best approach based on question content"""
        question_lower = question.lower()
        
        # Enhanced keywords for better detection
        keywords = {
            "step_by_step": [
                "solve", "calculate", "find", "evaluate", "determine",
                "compute", "derive", "what is the value", "find the value"
            ],
            "basics": [
                "explain", "what is", "define", "concept", "understand",
                "describe", "elaborate", "clarify", "how does", "why is"
            ],
            "examples": [
                "example", "similar", "practice", "show me", "demonstrate",
                "illustrate", "give an instance", "sample", "like"
            ],
            "mistakes": [
                "mistake", "error", "wrong", "incorrect", "avoid",
                "common problem", "pitfall", "caution", "warning", "be careful"
            ]
        }
        
        # Count keyword matches for each approach
        matches = {
            approach: sum(1 for word in words if word in question_lower)
            for approach, words in keywords.items()
        }
        
        # Return the approach with most matches, default to step_by_step
        best_approach = max(matches.items(), key=lambda x: x[1])[0]
        return best_approach if matches[best_approach] > 0 else "step_by_step"

    def _validate_response(self, response: str) -> bool:
        """Validate the quality and format of the response"""
        required_sections = [
            "**Concept Understanding**",
            "**Step-by-Step Solution**",
            "**Key Points to Remember**",
            "**Similar Problem Types**"
        ]
        
        # Check sections with exact formatting
        if not all(section in response for section in required_sections):
            return False
            
        # Check formatting
        if not ("•" in response and "**" in response):
            return False
            
        # Check length
        if not (200 <= len(response) <= 2500):
            return False
            
        return True

    def _format_history(self) -> str:
        """Format chat history for prompt context"""
        if not self.chat_history:
            return "No previous context."
            
        formatted = []
        for msg in self.chat_history[-100:]:  # Last 100 exchanges
            role = "Student" if isinstance(msg, HumanMessage) else "Tutor"
            content = msg.content[:300]  # Limit content length
            formatted.append(f"{role}: {content}")
        
        return "\n".join(formatted)

    def _is_general_query(self, question: str) -> bool:
        """Check if the question is a general query or greeting"""
        general_patterns = [
            'hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening',
            'how are you', 'what can you do', 'help', 'who are you'
        ]
        return any(pattern in question.lower() for pattern in general_patterns)

    def _get_general_response(self, question: str) -> Dict[str, Any]:
        """Generate a friendly response for general queries"""
        greetings = {
            'hi': "Hi! 👋 I'm your JEE study assistant. I can help you with Physics, Chemistry, and Mathematics problems. Would you like to:\n\n• Solve a specific JEE problem?\n• Understand a concept?\n• Practice with example questions?\n\nJust ask me anything related to JEE preparation!",
            'hello': "Hello! 👋 I'm here to help with your JEE preparation. What subject would you like to focus on - Physics, Chemistry, or Mathematics?",
            'help': "I'm your JEE study assistant! I can help you:\n\n• Solve JEE problems step by step\n• Explain complex concepts\n• Provide practice questions\n• Share exam tips and strategies\n\nWhat would you like help with?",
            'default': "Hello! 👋 I'm your JEE study assistant. I specialize in Physics, Chemistry, and Mathematics. How can I help you with your JEE preparation today?"
        }

        # Get appropriate greeting or default response
        for key in greetings:
            if key in question.lower():
                response = greetings[key]
                break
        else:
            response = greetings['default']

        return {
            "solution": response,
            "context": [
                HumanMessage(content=question),
                AIMessage(content=response[:500])
            ],
            "approach_used": "greeting"
        }

    async def solve(self, question: str, context: Dict[Any, Any]) -> dict:
        try:
            # Get user and session info
            user_id = context.get('user_id')
            session_id = context.get('session_id')
            history_limit = context.get('history_limit', 100)
            subject = context.get('subject', '').lower()
            topic = context.get('topic', '')

            # Format chat history for context
            formatted_history = []
            if context.get('chat_history'):
                for chat in context['chat_history']:
                    formatted_history.append({
                        'question': chat['question'],
                        'response': chat['response'],
                        'timestamp': chat['timestamp'],
                        'subject': chat['context'].get('subject', ''),
                        'topic': chat['context'].get('topic', '')
                    })

            # Create history context string
            if formatted_history:
                history_context = "\n\n".join([
                    f"Previous Question ({h['timestamp']}):\n"
                    f"Subject: {h['subject']}\n"
                    f"Topic: {h['topic']}\n"
                    f"Q: {h['question']}\n"
                    f"A: {h['response']}"
                    for h in formatted_history
                ])
            else:
                history_context = "No previous conversation context."

            # Process image if present
            image_context = ""
            if context.get('image'):
                image_context = "[Image provided for reference]"

            # Create system message with subject-specific instructions
            subject_prompts = {
                'physics': "As a Physics expert, focus on physical concepts, laws, and their applications.",
                'chemistry': "As a Chemistry expert, focus on chemical principles, reactions, and molecular understanding.",
                'mathematics': "As a Mathematics expert, focus on mathematical concepts, proofs, and problem-solving strategies."
            }

            subject_instruction = subject_prompts.get(subject, "As a JEE expert, provide comprehensive guidance across Physics, Chemistry, and Mathematics.")

            messages = [
                SystemMessage(content=fr"""You are an expert friendly JEE tutor specialized in Physics, Chemistry, and Mathematics.
                {subject_instruction}
                
                Previous conversation context:
                {history_context}

                Additional context:
                Subject: {subject}
                Topic: {topic}
                {context.get('pinnedText', '')}
                {image_context}

                Format your response following these rules:
                1. Use plain text without LaTeX markers or special characters
                2. For mathematical expressions:
                    - Use simple text: x^2 for powers
                    - Use / for fractions: a/b
                    - Use * for multiplication
                    - Write units in parentheses: (m/s), (kg), etc.
                
                3. Structure your response with:
                    - Clear numbered sections
                    - Bullet points using simple dashes (-)
                    - Line breaks between sections
                    - Simple indentation for sub-points
                
                4. For equations:
                    - Write them on separate lines
                    - Use = sign with spaces around it
                    - Example: F = m * a
                    - For complex equations, break into multiple lines
                
                5. For explanations:
                    - Use step-by-step numbering
                    - Include clear examples
                    - Explain concepts without technical markup
                
                If the user asks about previous conversations or history, summarize the above context using this same formatting.
                
                Remember to keep all mathematical and scientific content accurate while using this simplified format.
                Include specific details from previous questions and their solutions.
                """),
                HumanMessage(content=question)
            ]

            # Call the LLM
            response = await self.llm.agenerate([messages])
            
            # Extract the response
            llm_response = response.generations[0][0].text
            
            return {
                'solution': llm_response,
                'context': {
                    'history': formatted_history,
                    'current_question': question,
                    'response': llm_response,
                    'user_id': user_id,
                    'session_id': session_id,
                    'subject': subject,
                    'topic': topic
                }
            }

        except Exception as e:
            logger.error(f"Error in MathAgent solve method: {str(e)}", exc_info=True)
            raise Exception(f"Failed to process question: {str(e)}")

