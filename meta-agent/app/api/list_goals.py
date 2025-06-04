"""
List Goals API Module

This module provides the API endpoint for listing existing goals. It supports
filtering by user ID and status, as well as pagination through limit and offset
parameters.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.utils.logger import setup_logger
from app.utils.config import Config, load_config
from app.memory.memory_store import MemoryStore

# Initialize logger
logger = setup_logger(__name__)

# Create router
router = APIRouter(tags=["goals"])

# Models
class GoalListItem(BaseModel):
    """Response model for a goal in the list."""
    id: str
    title: str
    description: Optional[str] = None
    status: str
    user_id: Optional[str] = None
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class GoalListResponse(BaseModel):
    """Response model for the list goals endpoint."""
    goals: List[GoalListItem]
    total: int
    limit: int
    offset: int
    has_more: bool

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

@router.get("/goals", response_model=GoalListResponse)
async def list_goals(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    memory_store: MemoryStore = Depends(get_memory_store),
    config: Config = Depends(get_config)
) -> GoalListResponse:
    """
    List existing goals with optional filtering and pagination.
    
    Args:
        user_id: Optional user ID to filter goals by
        status: Optional status to filter goals by (active, completed, failed, etc.)
        limit: Maximum number of goals to return (default: 10, max: 100)
        offset: Number of goals to skip (for pagination)
        memory_store: The memory store
        config: Application configuration
        
    Returns:
        GoalListResponse: List of goals matching the criteria
    """
    try:
        # Retrieve goals from memory store
        goals = await memory_store.list_goals(
            user_id=user_id,
            status=status,
            limit=limit + 1,  # Request one more to check if there are more
            offset=offset
        )
        
        # Check if there are more results
        has_more = len(goals) > limit
        if has_more:
            goals = goals[:limit]  # Remove the extra item
        
        # Get total count (in a real implementation, this would be a separate query)
        # For now, we'll just use a placeholder
        total = offset + len(goals) + (1 if has_more else 0)
        
        # Convert to response model
        response_goals = [
            GoalListItem(
                id=goal["id"],
                title=goal["title"],
                description=goal["description"],
                status=goal["status"],
                user_id=goal["user_id"],
                created_at=goal["created_at"],
                updated_at=goal["updated_at"],
                completed_at=goal["completed_at"],
                metadata=goal["metadata"]
            )
            for goal in goals
        ]
        
        logger.info(f"Listed {len(response_goals)} goals (offset={offset}, limit={limit}, user_id={user_id}, status={status})")
        
        return GoalListResponse(
            goals=response_goals,
            total=total,
            limit=limit,
            offset=offset,
            has_more=has_more
        )
        
    except Exception as e:
        logger.error(f"Error listing goals: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list goals: {str(e)}")
