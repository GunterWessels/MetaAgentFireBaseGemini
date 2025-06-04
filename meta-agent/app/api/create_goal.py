"""
Create Goal API Module

This module provides the API endpoint for creating new goals. It processes
natural language input through the NLU pipeline to extract intents and slots,
generates follow-up questions if needed, and stores the goal in the memory store.
"""

import uuid
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.utils.logger import setup_logger
from app.utils.config import Config, load_config
from app.memory.memory_store import MemoryStore
from app.nlu.parse_goal_chain import ParseGoalChain, ParsedGoal
from app.nlu.follow_up_chain import FollowUpChain, FollowUpQuestion
from app.planner.plan_generator import PlanGenerator

# Initialize logger
logger = setup_logger(__name__)

# Create router
router = APIRouter(tags=["goals"])

# Models
class GoalRequest(BaseModel):
    """Request model for creating a goal."""
    text: str = Field(..., description="Natural language description of the goal")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class SlotResponse(BaseModel):
    """Response model for a parsed slot."""
    name: str
    value: str
    confidence: float

class IntentResponse(BaseModel):
    """Response model for a parsed intent."""
    name: str
    confidence: float

class FollowUpQuestionResponse(BaseModel):
    """Response model for a follow-up question."""
    slot_name: str
    question: str
    context: Optional[str] = None

class GoalResponse(BaseModel):
    """Response model for a created goal."""
    goal_id: str
    text: str
    intents: List[IntentResponse]
    slots: List[SlotResponse]
    primary_intent: Optional[str] = None
    follow_up_questions: List[FollowUpQuestionResponse] = []
    requires_follow_up: bool = False
    created_at: str

# Dependencies
def get_config() -> Config:
    """Dependency to get configuration."""
    return load_config()

async def get_memory_store(config: Config = Depends(get_config)) -> MemoryStore:
    """Dependency to get memory store."""
    memory_store = MemoryStore(config)
    await memory_store.initialize()
    try:
        yield memory_store
    finally:
        await memory_store.close()

async def get_nlu_components(config: Config = Depends(get_config)):
    """Dependency to get NLU components."""
    from app.main import get_llm_instance
    
    llm = get_llm_instance(config)
    parse_chain = ParseGoalChain(llm, config)
    follow_up_chain = FollowUpChain(llm, config)
    plan_generator = PlanGenerator(config)
    
    return parse_chain, follow_up_chain, plan_generator

@router.post("/goals", response_model=GoalResponse)
async def create_goal(
    request: GoalRequest,
    background_tasks: BackgroundTasks,
    memory_store: MemoryStore = Depends(get_memory_store),
    nlu_components: tuple = Depends(get_nlu_components),
    config: Config = Depends(get_config)
) -> GoalResponse:
    """
    Create a new goal from natural language input.
    
    This endpoint processes the input through the NLU pipeline to extract
    intents and slots, generates follow-up questions if needed, and stores
    the goal in the memory store.
    
    Args:
        request: The goal creation request
        background_tasks: FastAPI background tasks
        memory_store: The memory store
        nlu_components: NLU components (parse_chain, follow_up_chain, plan_generator)
        config: Application configuration
        
    Returns:
        GoalResponse: The created goal with parsed information
    """
    parse_chain, follow_up_chain, plan_generator = nlu_components
    
    try:
        # Parse the goal text
        parsed_goal = await parse_chain.parse(request.text)
        
        # Get the primary intent
        primary_intent = parsed_goal.get_primary_intent()
        intent_name = primary_intent.name if primary_intent else "unknown"
        
        # Get required slots for the intent
        required_slots = []
        if primary_intent:
            required_slots = plan_generator.get_required_slots_for_intent(intent_name)
        
        # Check if follow-up questions are needed
        follow_up_response = None
        requires_follow_up = False
        
        if required_slots and not parsed_goal.has_required_slots(required_slots):
            # Generate follow-up questions for missing slots
            follow_up_response = await follow_up_chain.generate_questions(parsed_goal, required_slots)
            requires_follow_up = len(follow_up_response.questions) > 0
        
        # Create a goal in the memory store
        metadata = request.metadata or {}
        metadata.update({
            "intents": [{"name": intent.name, "confidence": intent.confidence} for intent in parsed_goal.intents],
            "slots": [{"name": slot.name, "value": slot.value, "confidence": slot.confidence} for slot in parsed_goal.slots],
            "primary_intent": intent_name if primary_intent else None,
            "requires_follow_up": requires_follow_up
        })
        
        goal_id = await memory_store.create_goal(
            title=request.text[:100],  # Use first 100 chars as title
            description=request.text,
            user_id=request.user_id,
            metadata=metadata
        )
        
        # If we have a complete goal (no follow-up needed), generate a plan in the background
        if not requires_follow_up and primary_intent:
            background_tasks.add_task(
                _generate_plan_background,
                goal_id=goal_id,
                parsed_goal=parsed_goal,
                plan_generator=plan_generator
            )
        
        # Prepare the response
        response = GoalResponse(
            goal_id=goal_id,
            text=request.text,
            intents=[
                IntentResponse(name=intent.name, confidence=intent.confidence)
                for intent in parsed_goal.intents
            ],
            slots=[
                SlotResponse(name=slot.name, value=slot.value, confidence=slot.confidence)
                for slot in parsed_goal.slots
            ],
            primary_intent=intent_name if primary_intent else None,
            requires_follow_up=requires_follow_up,
            created_at=datetime.utcnow().isoformat()
        )
        
        # Add follow-up questions if any
        if follow_up_response and follow_up_response.questions:
            response.follow_up_questions = [
                FollowUpQuestionResponse(
                    slot_name=q.slot_name,
                    question=q.question,
                    context=q.context
                )
                for q in follow_up_response.questions
            ]
        
        logger.info(f"Created goal {goal_id} with intent {intent_name}")
        return response
        
    except Exception as e:
        logger.error(f"Error creating goal: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create goal: {str(e)}")

async def _generate_plan_background(goal_id: str, parsed_goal: ParsedGoal, plan_generator: PlanGenerator):
    """
    Background task to generate an execution plan for a goal.
    
    Args:
        goal_id: The goal ID
        parsed_goal: The parsed goal
        plan_generator: The plan generator
    """
    try:
        # Generate a plan
        plan = await plan_generator.generate_plan(parsed_goal, goal_id)
        
        # Generate code for the plan
        generated_code = await plan_generator.generate_code(plan)
        
        # In a real implementation, we would store the plan and generated code
        # and potentially execute the plan automatically
        
        logger.info(f"Generated plan for goal {goal_id} with {len(plan.steps)} steps")
    except Exception as e:
        logger.error(f"Error generating plan for goal {goal_id}: {e}")
