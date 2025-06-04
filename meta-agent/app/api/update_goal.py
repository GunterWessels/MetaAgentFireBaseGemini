"""
Update Goal API Module

This module provides the API endpoint for updating existing goals. It allows
changing the status, title, description, and metadata of a goal, as well as
handling follow-up responses to complete goals that required additional information.
"""

from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.utils.logger import setup_logger
from app.utils.config import Config, load_config
from app.memory.memory_store import MemoryStore
from app.nlu.parse_goal_chain import ParseGoalChain
from app.planner.plan_generator import PlanGenerator

# Initialize logger
logger = setup_logger(__name__)

# Create router
router = APIRouter(tags=["goals"])

# Models
class GoalUpdateRequest(BaseModel):
    """Request model for updating a goal."""
    status: Optional[str] = Field(None, description="New status (active, completed, failed, etc.)")
    title: Optional[str] = Field(None, description="New title for the goal")
    description: Optional[str] = Field(None, description="New description for the goal")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata to merge")
    follow_up_responses: Optional[Dict[str, str]] = Field(None, description="Responses to follow-up questions by slot name")

class SlotResponse(BaseModel):
    """Response model for a parsed slot."""
    name: str
    value: str
    confidence: float

class IntentResponse(BaseModel):
    """Response model for a parsed intent."""
    name: str
    confidence: float

class GoalUpdateResponse(BaseModel):
    """Response model for an updated goal."""
    goal_id: str
    title: str
    description: Optional[str] = None
    status: str
    user_id: Optional[str] = None
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    intents: List[IntentResponse] = []
    slots: List[SlotResponse] = []
    primary_intent: Optional[str] = None
    requires_follow_up: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

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
    plan_generator = PlanGenerator(config)
    
    return parse_chain, plan_generator

@router.put("/goals/{goal_id}", response_model=GoalUpdateResponse)
async def update_goal(
    goal_id: str = Path(..., description="The ID of the goal to update"),
    request: GoalUpdateRequest = None,
    background_tasks: BackgroundTasks = None,
    memory_store: MemoryStore = Depends(get_memory_store),
    nlu_components: tuple = Depends(get_nlu_components),
    config: Config = Depends(get_config)
) -> GoalUpdateResponse:
    """
    Update an existing goal.
    
    This endpoint allows updating the status, title, description, and metadata
    of a goal. It also handles follow-up responses to complete goals that
    required additional information.
    
    Args:
        goal_id: The ID of the goal to update
        request: The goal update request
        background_tasks: FastAPI background tasks
        memory_store: The memory store
        nlu_components: NLU components (parse_chain, plan_generator)
        config: Application configuration
        
    Returns:
        GoalUpdateResponse: The updated goal
    """
    parse_chain, plan_generator = nlu_components
    
    try:
        # Get the existing goal
        goal = await memory_store.get_goal(goal_id)
        if not goal:
            raise HTTPException(status_code=404, detail=f"Goal with ID {goal_id} not found")
        
        # If no request body is provided, just return the current state
        if not request:
            return _convert_to_response(goal)
        
        # Process follow-up responses if provided
        updated_metadata = dict(goal.get("metadata", {}))
        if request.follow_up_responses:
            # Get existing slots
            existing_slots = updated_metadata.get("slots", [])
            existing_slot_names = {slot["name"].lower() for slot in existing_slots}
            
            # Add new slots from follow-up responses
            for slot_name, value in request.follow_up_responses.items():
                if slot_name.lower() not in existing_slot_names:
                    existing_slots.append({
                        "name": slot_name,
                        "value": value,
                        "confidence": 1.0  # Direct user input has high confidence
                    })
                else:
                    # Update existing slot
                    for slot in existing_slots:
                        if slot["name"].lower() == slot_name.lower():
                            slot["value"] = value
                            slot["confidence"] = 1.0
            
            # Update metadata
            updated_metadata["slots"] = existing_slots
            
            # Check if we have all required slots now
            primary_intent = updated_metadata.get("primary_intent")
            if primary_intent:
                required_slots = plan_generator.get_required_slots_for_intent(primary_intent)
                all_slot_names = {slot["name"].lower() for slot in existing_slots}
                requires_follow_up = not all(slot.lower() in all_slot_names for slot in required_slots)
                updated_metadata["requires_follow_up"] = requires_follow_up
                
                # If we have all required slots now, generate a plan in the background
                if not requires_follow_up:
                    # Create a parsed goal object for the plan generator
                    from app.nlu.parse_goal_chain import ParsedGoal, Intent, Slot
                    
                    parsed_goal = ParsedGoal(
                        raw_text=goal.get("description", ""),
                        intents=[
                            Intent(name=intent["name"], confidence=intent["confidence"])
                            for intent in updated_metadata.get("intents", [])
                        ],
                        slots=[
                            Slot(name=slot["name"], value=slot["value"], confidence=slot["confidence"])
                            for slot in updated_metadata.get("slots", [])
                        ]
                    )
                    
                    # Schedule plan generation
                    background_tasks.add_task(
                        _generate_plan_background,
                        goal_id=goal_id,
                        parsed_goal=parsed_goal,
                        plan_generator=plan_generator
                    )
        
        # Update the goal with provided values
        update_data = {}
        if request.status:
            update_data["status"] = request.status
        if request.title:
            update_data["title"] = request.title
        if request.description:
            update_data["description"] = request.description
        
        # Merge metadata
        if request.metadata:
            updated_metadata.update(request.metadata)
        
        # Update the goal in the memory store
        success = await memory_store.update_goal(
            goal_id=goal_id,
            status=request.status,
            title=request.title,
            description=request.description,
            metadata=updated_metadata
        )
        
        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to update goal {goal_id}")
        
        # Get the updated goal
        updated_goal = await memory_store.get_goal(goal_id)
        if not updated_goal:
            raise HTTPException(status_code=404, detail=f"Goal with ID {goal_id} not found after update")
        
        logger.info(f"Updated goal {goal_id}")
        return _convert_to_response(updated_goal)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating goal {goal_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update goal: {str(e)}")

def _convert_to_response(goal: Dict[str, Any]) -> GoalUpdateResponse:
    """
    Convert a goal dictionary from the memory store to a response model.
    
    Args:
        goal: The goal dictionary from the memory store
        
    Returns:
        GoalUpdateResponse: The formatted response
    """
    metadata = goal.get("metadata", {})
    
    # Extract intents and slots from metadata
    intents = []
    for intent_data in metadata.get("intents", []):
        intents.append(IntentResponse(
            name=intent_data.get("name", "unknown"),
            confidence=intent_data.get("confidence", 0.0)
        ))
    
    slots = []
    for slot_data in metadata.get("slots", []):
        slots.append(SlotResponse(
            name=slot_data.get("name", "unknown"),
            value=slot_data.get("value", ""),
            confidence=slot_data.get("confidence", 0.0)
        ))
    
    return GoalUpdateResponse(
        goal_id=goal["id"],
        title=goal["title"],
        description=goal["description"],
        status=goal["status"],
        user_id=goal["user_id"],
        created_at=goal["created_at"],
        updated_at=goal["updated_at"],
        completed_at=goal["completed_at"],
        intents=intents,
        slots=slots,
        primary_intent=metadata.get("primary_intent"),
        requires_follow_up=metadata.get("requires_follow_up", False),
        metadata=metadata
    )

async def _generate_plan_background(goal_id: str, parsed_goal, plan_generator):
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
