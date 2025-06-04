"""
Follow Up Chain Module

This module provides a LangChain-based solution for generating follow-up questions
when required slots are missing from a parsed goal. It helps the Meta-Agent
gather additional information needed to fulfill the user's request.
"""

import json
from typing import Dict, List, Any, Optional, Union, Tuple

from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import BaseOutputParser, OutputParserException
from langchain_core.pydantic_v1 import BaseModel, Field, validator

from app.utils.logger import setup_logger
from app.utils.config import Config
from app.nlu.parse_goal_chain import ParsedGoal, Intent, Slot

# Initialize logger
logger = setup_logger(__name__)

# Define the output schema for follow-up questions
class FollowUpQuestion(BaseModel):
    """Schema for a follow-up question."""
    slot_name: str = Field(..., description="The name of the slot being asked about")
    question: str = Field(..., description="The follow-up question to ask the user")
    context: Optional[str] = Field(None, description="Additional context about why this information is needed")

class FollowUpResponse(BaseModel):
    """Schema for the response containing follow-up questions."""
    questions: List[FollowUpQuestion] = Field(..., description="List of follow-up questions")
    summary: str = Field(..., description="Summary of what information is still needed")


class FollowUpOutputParser(BaseOutputParser):
    """Custom output parser for follow-up question generation."""
    
    def parse(self, text: str) -> FollowUpResponse:
        """Parse the LLM output into a structured FollowUpResponse object."""
        try:
            # Try to extract JSON from the text
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON object without markdown formatting
                json_match = re.search(r'(\{.*\})', text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = text
            
            # Parse the JSON string
            parsed_data = json.loads(json_str)
            
            # Convert to Pydantic model
            return FollowUpResponse(**parsed_data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse output: {e}")
            logger.error(f"Raw output: {text}")
            raise OutputParserException(f"Failed to parse output: {e}. Raw output: {text}")


class FollowUpChain:
    """
    LangChain implementation for generating follow-up questions when required slots
    are missing from a parsed goal.
    
    This chain takes a parsed goal with missing slots and generates appropriate
    follow-up questions to gather the needed information.
    """
    
    def __init__(self, llm: BaseLLM, config: Config):
        """
        Initialize the FollowUpChain.
        
        Args:
            llm: The language model to use for generating questions
            config: Application configuration
        """
        self.llm = llm
        self.config = config
        
        # Initialize the output parser
        self.output_parser = FollowUpOutputParser()
        
        # Define the prompt template
        self.prompt_template = self._create_prompt_template()
        
        # Create the chain
        self.chain = LLMChain(
            llm=llm,
            prompt=self.prompt_template,
            verbose=config.debug_mode
        )
        
        # Define slot descriptions for better question generation
        self.slot_descriptions = {
            "person": "the person or people involved",
            "date": "the date when this should happen",
            "time": "the specific time",
            "duration": "how long this should take",
            "topic": "the subject or topic",
            "priority": "the priority level",
            "platform": "the specific platform or system",
            "content": "the content or message",
            "status": "the status or state",
            "location": "the location or place",
        }
        
        logger.info("FollowUpChain initialized")
    
    def _create_prompt_template(self) -> PromptTemplate:
        """Create the prompt template for follow-up question generation."""
        template = """
        You are an AI assistant that generates follow-up questions to gather missing information.
        
        The user has provided a goal, but some required information (slots) is missing.
        
        # User's original goal:
        {original_goal}
        
        # Detected intent:
        {intent}
        
        # Information we already have:
        {existing_slots}
        
        # Missing information (slots) we need:
        {missing_slots}
        
        Your task is to generate natural, conversational follow-up questions to gather the missing information.
        Create one question for each missing slot. Make the questions sound natural and contextual based on
        the user's original goal and the information we already have.
        
        # Output format:
        Provide your response as a JSON object with the following structure:
        ```json
        {{
            "questions": [
                {{
                    "slot_name": "missing_slot_name",
                    "question": "Your natural-sounding follow-up question?",
                    "context": "Brief explanation of why this information is needed"
                }}
            ],
            "summary": "A brief summary of what information is still needed"
        }}
        ```
        
        # Your follow-up questions:
        """
        
        return PromptTemplate(
            template=template,
            input_variables=["original_goal", "intent", "existing_slots", "missing_slots"]
        )
    
    async def generate_questions(self, parsed_goal: ParsedGoal, required_slots: List[str]) -> FollowUpResponse:
        """
        Generate follow-up questions for missing required slots.
        
        Args:
            parsed_goal: The parsed goal with potentially missing slots
            required_slots: List of slot names that are required for the intent
            
        Returns:
            FollowUpResponse: Structured response with follow-up questions
        """
        # Get the primary intent
        primary_intent = parsed_goal.get_primary_intent()
        intent_name = primary_intent.name if primary_intent else "unknown"
        
        # Determine which required slots are missing
        missing_slot_names = parsed_goal.missing_slots(required_slots)
        
        # If no slots are missing, return an empty response
        if not missing_slot_names:
            return FollowUpResponse(
                questions=[],
                summary="All required information is already provided."
            )
        
        # Format existing slots for the prompt
        existing_slots_text = "None" if not parsed_goal.slots else "\n".join([
            f"- {slot.name}: {slot.value}" for slot in parsed_goal.slots
        ])
        
        # Format missing slots for the prompt
        missing_slots_text = "\n".join([
            f"- {slot_name}: {self.slot_descriptions.get(slot_name.lower(), 'information')}" 
            for slot_name in missing_slot_names
        ])
        
        try:
            # Run the chain
            result = await self.chain.arun(
                original_goal=parsed_goal.raw_text,
                intent=intent_name,
                existing_slots=existing_slots_text,
                missing_slots=missing_slots_text
            )
            
            # Parse the output
            parsed_result = self.output_parser.parse(result)
            
            logger.info(f"Generated {len(parsed_result.questions)} follow-up questions")
            return parsed_result
            
        except Exception as e:
            logger.error(f"Error generating follow-up questions: {e}")
            # Return a default question on error
            default_questions = []
            for slot_name in missing_slot_names:
                description = self.slot_descriptions.get(slot_name.lower(), "this information")
                question = f"Could you please provide {description}?"
                default_questions.append(
                    FollowUpQuestion(
                        slot_name=slot_name,
                        question=question,
                        context=f"This information is required for your {intent_name} request."
                    )
                )
            
            return FollowUpResponse(
                questions=default_questions,
                summary=f"Please provide the following missing information: {', '.join(missing_slot_names)}."
            )
    
    def get_question_for_slot(self, slot_name: str, intent_name: str = None) -> str:
        """
        Get a default question for a specific slot.
        
        Args:
            slot_name: The name of the slot to ask about
            intent_name: Optional intent name for context
            
        Returns:
            A default question string
        """
        description = self.slot_descriptions.get(slot_name.lower(), f"the {slot_name}")
        
        # Map of slot names to default questions
        default_questions = {
            "person": "Who should be involved in this?",
            "date": "When should this happen?",
            "time": "At what time should this occur?",
            "duration": "How long should this take?",
            "topic": "What is the topic or subject for this?",
            "priority": "What priority level would you assign to this?",
            "platform": "Which platform or system should this use?",
            "content": "What content or message would you like to include?",
            "status": "What status would you like to set?",
            "location": "Where should this take place?"
        }
        
        # Get the default question or create a generic one
        question = default_questions.get(
            slot_name.lower(), 
            f"Could you please provide {description}?"
        )
        
        # Add intent context if provided
        if intent_name:
            intent_display = intent_name.replace("_", " ")
            question += f" This will help me {intent_display} correctly."
        
        return question
