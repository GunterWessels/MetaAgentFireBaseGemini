"""
Parse Goal Chain Module

This module provides a LangChain-based solution for parsing user goals into structured
intents and slots. It extracts meaningful information from natural language input
to help the Meta-Agent understand what the user wants to accomplish.
"""

import json
import re
from typing import Dict, List, Any, Optional, Union, Tuple, cast

from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import BaseOutputParser, OutputParserException
from langchain_core.pydantic_v1 import BaseModel, Field, validator
from langchain.output_parsers import PydanticOutputParser, OutputFixingParser

from app.utils.logger import setup_logger
from app.utils.config import Config

# Initialize logger
logger = setup_logger(__name__)

# Define the output schema for parsed goals
class Intent(BaseModel):
    """Schema for a parsed intent."""
    name: str = Field(..., description="The name of the identified intent")
    confidence: float = Field(..., description="Confidence score between 0 and 1")
    
    @validator("confidence")
    def validate_confidence(cls, v):
        """Ensure confidence is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        return v

class Slot(BaseModel):
    """Schema for a parsed slot (entity)."""
    name: str = Field(..., description="The name of the slot")
    value: str = Field(..., description="The extracted value")
    confidence: float = Field(..., description="Confidence score between 0 and 1")
    
    @validator("confidence")
    def validate_confidence(cls, v):
        """Ensure confidence is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        return v

class ParsedGoal(BaseModel):
    """Schema for a fully parsed goal."""
    raw_text: str = Field(..., description="The original text input")
    intents: List[Intent] = Field(..., description="List of identified intents")
    slots: List[Slot] = Field(..., description="List of extracted slots/entities")
    
    def get_primary_intent(self) -> Optional[Intent]:
        """Get the highest confidence intent."""
        if not self.intents:
            return None
        return max(self.intents, key=lambda x: x.confidence)
    
    def get_slot_value(self, slot_name: str) -> Optional[str]:
        """Get the value of a specific slot by name."""
        for slot in self.slots:
            if slot.name.lower() == slot_name.lower():
                return slot.value
        return None
    
    def has_required_slots(self, required_slots: List[str]) -> bool:
        """Check if all required slots are present."""
        extracted_slots = {slot.name.lower() for slot in self.slots}
        return all(slot.lower() in extracted_slots for slot in required_slots)
    
    def missing_slots(self, required_slots: List[str]) -> List[str]:
        """Get a list of missing required slots."""
        extracted_slots = {slot.name.lower() for slot in self.slots}
        return [slot for slot in required_slots if slot.lower() not in extracted_slots]


class GoalOutputParser(BaseOutputParser):
    """Custom output parser for goal parsing results."""
    
    def parse(self, text: str) -> ParsedGoal:
        """Parse the LLM output into a structured ParsedGoal object."""
        try:
            # Try to extract JSON from the text (handle cases where LLM adds explanations)
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
            return ParsedGoal(**parsed_data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse output: {e}")
            logger.error(f"Raw output: {text}")
            raise OutputParserException(f"Failed to parse output: {e}. Raw output: {text}")


class ParseGoalChain:
    """
    LangChain implementation for parsing user goals into structured intents and slots.
    
    This chain takes natural language input and extracts meaningful information to help
    the Meta-Agent understand what the user wants to accomplish.
    """
    
    def __init__(self, llm: BaseLLM, config: Config):
        """
        Initialize the ParseGoalChain.
        
        Args:
            llm: The language model to use for parsing
            config: Application configuration
        """
        self.llm = llm
        self.config = config
        
        # Initialize the output parser
        self.output_parser = GoalOutputParser()
        
        # Create a backup parser that can fix common errors
        pydantic_parser = PydanticOutputParser(pydantic_object=ParsedGoal)
        self.fixing_parser = OutputFixingParser.from_llm(
            parser=pydantic_parser,
            llm=llm
        )
        
        # Define the prompt template
        self.prompt_template = self._create_prompt_template()
        
        # Create the chain
        self.chain = LLMChain(
            llm=llm,
            prompt=self.prompt_template,
            verbose=config.debug_mode
        )
        
        logger.info("ParseGoalChain initialized")
    
    def _create_prompt_template(self) -> PromptTemplate:
        """Create the prompt template for goal parsing."""
        template = """
        You are an AI assistant that extracts structured information from user goals.
        
        Your task is to:
        1. Identify the user's intent(s) from their input
        2. Extract any relevant slots (entities) mentioned
        
        # Example intents:
        - create_task: User wants to create a new task or reminder
        - schedule_meeting: User wants to schedule a meeting
        - find_information: User wants to find or retrieve information
        - send_message: User wants to send a message to someone
        - update_status: User wants to update the status of something
        
        # Example slots:
        - person: Names of people mentioned
        - date: Any dates mentioned
        - time: Any times mentioned
        - duration: How long something should take
        - topic: The subject or topic of a meeting/task
        - priority: Priority level mentioned
        - platform: Specific platform or system mentioned
        
        # User input:
        {input}
        
        # Output format:
        Provide your response as a JSON object with the following structure:
        ```json
        {{
            "raw_text": "the original user input",
            "intents": [
                {{
                    "name": "intent_name",
                    "confidence": 0.95
                }}
            ],
            "slots": [
                {{
                    "name": "slot_name",
                    "value": "extracted value",
                    "confidence": 0.9
                }}
            ]
        }}
        ```
        
        Ensure you include all detected intents and slots. If multiple intents are possible, include them all with appropriate confidence scores.
        
        # Your structured JSON response:
        """
        
        return PromptTemplate(
            template=template,
            input_variables=["input"]
        )
    
    async def parse(self, text: str) -> ParsedGoal:
        """
        Parse a user goal into structured intents and slots.
        
        Args:
            text: The raw text input from the user
            
        Returns:
            ParsedGoal: Structured representation of the user's goal
        """
        try:
            # Run the chain
            result = await self.chain.arun(input=text)
            
            # Parse the output
            try:
                parsed_result = self.output_parser.parse(result)
            except OutputParserException:
                # If parsing fails, try the fixing parser
                logger.warning("Primary parsing failed, attempting to fix output")
                parsed_result = self.fixing_parser.parse(result)
            
            # Ensure raw_text is set correctly
            parsed_result.raw_text = text
            
            logger.info(f"Successfully parsed goal with {len(parsed_result.intents)} intents and {len(parsed_result.slots)} slots")
            return parsed_result
            
        except Exception as e:
            logger.error(f"Error parsing goal: {e}")
            # Return a minimal valid result on error
            return ParsedGoal(
                raw_text=text,
                intents=[Intent(name="unknown", confidence=0.0)],
                slots=[]
            )
    
    def get_required_slots_for_intent(self, intent_name: str) -> List[str]:
        """
        Get the list of required slots for a specific intent.
        
        Args:
            intent_name: The name of the intent
            
        Returns:
            List of required slot names
        """
        # This could be expanded with a more sophisticated mapping
        # or loaded from configuration
        intent_slot_mapping = {
            "create_task": ["topic", "date"],
            "schedule_meeting": ["topic", "date", "time", "person"],
            "find_information": ["topic"],
            "send_message": ["person", "content"],
            "update_status": ["topic", "status"]
        }
        
        return intent_slot_mapping.get(intent_name, [])
