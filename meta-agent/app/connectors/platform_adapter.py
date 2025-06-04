"""
Platform Adapter Module

This module defines the common interface for platform connectors in the Meta-Agent.
It provides abstract base classes and utility functions that standardize how
the Meta-Agent interacts with external platforms like Slack, JIRA, etc.

The platform adapter is responsible for abstracting away platform-specific details
and providing a uniform interface for performing actions across different platforms.
"""

import abc
import enum
import json
import time
from typing import Dict, List, Any, Optional, Union, Tuple, TypeVar, Generic, Callable
from datetime import datetime

from pydantic import BaseModel, Field, validator

from app.utils.logger import setup_logger

# Initialize logger
logger = setup_logger(__name__)

class ActionStatus(str, enum.Enum):
    """Status of an action performed on a platform."""
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN = "unknown"

class ActionContext(BaseModel):
    """Context for an action, including metadata and tracking information."""
    action_id: str = Field(..., description="Unique identifier for the action")
    goal_id: Optional[str] = Field(None, description="ID of the goal this action is part of")
    step_id: Optional[str] = Field(None, description="ID of the execution plan step")
    timestamp: float = Field(default_factory=time.time, description="When the action was initiated")
    user_id: Optional[str] = Field(None, description="User who initiated the action")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "action_id": self.action_id,
            "goal_id": self.goal_id,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "metadata": self.metadata
        }

class ActionResult(BaseModel):
    """Result of an action performed on a platform."""
    status: ActionStatus = Field(..., description="Status of the action")
    data: Optional[Any] = Field(None, description="Data returned by the action")
    error_message: Optional[str] = Field(None, description="Error message if action failed")
    platform: str = Field(..., description="Platform the action was performed on")
    action_type: str = Field(..., description="Type of action performed")
    context: ActionContext = Field(..., description="Context of the action")
    timestamp: float = Field(default_factory=time.time, description="When the result was generated")
    
    def is_success(self) -> bool:
        """Check if the action was successful."""
        return self.status == ActionStatus.SUCCESS
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status,
            "data": self.data,
            "error_message": self.error_message,
            "platform": self.platform,
            "action_type": self.action_type,
            "context": self.context.to_dict(),
            "timestamp": self.timestamp
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)

class PlatformAdapter(abc.ABC):
    """
    Abstract base class for platform connectors.
    
    This defines the interface that all platform connectors must implement.
    Each connector is responsible for translating between the Meta-Agent's
    abstract actions and the platform-specific API calls.
    """
    
    @property
    @abc.abstractmethod
    def platform_name(self) -> str:
        """Get the name of the platform."""
        pass
    
    @abc.abstractmethod
    async def initialize(self) -> bool:
        """
        Initialize the connector.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        pass
    
    @abc.abstractmethod
    async def close(self) -> None:
        """Close the connector and clean up resources."""
        pass
    
    @abc.abstractmethod
    async def is_connected(self) -> bool:
        """
        Check if the connector is connected to the platform.
        
        Returns:
            bool: True if connected, False otherwise
        """
        pass
    
    @abc.abstractmethod
    async def perform_action(
        self, action_type: str, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Perform an action on the platform.
        
        Args:
            action_type: Type of action to perform
            parameters: Parameters for the action
            context: Context for the action
            
        Returns:
            ActionResult: Result of the action
        """
        pass
    
    @abc.abstractmethod
    async def validate_parameters(
        self, action_type: str, parameters: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate parameters for an action.
        
        Args:
            action_type: Type of action to perform
            parameters: Parameters to validate
            
        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        pass
    
    @abc.abstractmethod
    def get_supported_actions(self) -> List[str]:
        """
        Get a list of actions supported by this connector.
        
        Returns:
            List[str]: List of supported action types
        """
        pass
    
    @abc.abstractmethod
    def get_required_parameters(self, action_type: str) -> List[str]:
        """
        Get a list of required parameters for an action.
        
        Args:
            action_type: Type of action
            
        Returns:
            List[str]: List of required parameter names
        """
        pass
    
    @abc.abstractmethod
    def get_optional_parameters(self, action_type: str) -> List[str]:
        """
        Get a list of optional parameters for an action.
        
        Args:
            action_type: Type of action
            
        Returns:
            List[str]: List of optional parameter names
        """
        pass


# Registry of platform adapters
_platform_adapters: Dict[str, PlatformAdapter] = {}

def register_adapter(adapter: PlatformAdapter) -> None:
    """
    Register a platform adapter.
    
    Args:
        adapter: The adapter to register
    """
    _platform_adapters[adapter.platform_name] = adapter
    logger.info(f"Registered platform adapter for {adapter.platform_name}")

def get_adapter(platform: str) -> Optional[PlatformAdapter]:
    """
    Get a platform adapter by name.
    
    Args:
        platform: Name of the platform
        
    Returns:
        Optional[PlatformAdapter]: The adapter, or None if not found
    """
    return _platform_adapters.get(platform.lower())

async def perform_action(
    platform: str, action_type: str, parameters: Dict[str, Any], context: Optional[ActionContext] = None
) -> ActionResult:
    """
    Perform an action on a platform.
    
    This is a convenience function that looks up the appropriate adapter
    and delegates to its perform_action method.
    
    Args:
        platform: Name of the platform
        action_type: Type of action to perform
        parameters: Parameters for the action
        context: Optional context for the action
        
    Returns:
        ActionResult: Result of the action
    """
    # Generate a context if none is provided
    if context is None:
        import uuid
        context = ActionContext(
            action_id=str(uuid.uuid4()),
            timestamp=time.time()
        )
    
    # Get the adapter
    adapter = get_adapter(platform)
    if not adapter:
        logger.error(f"No adapter found for platform {platform}")
        return ActionResult(
            status=ActionStatus.NOT_FOUND,
            error_message=f"No adapter found for platform {platform}",
            platform=platform,
            action_type=action_type,
            context=context
        )
    
    # Check if the adapter is connected
    if not await adapter.is_connected():
        logger.error(f"Adapter for platform {platform} is not connected")
        return ActionResult(
            status=ActionStatus.UNAUTHORIZED,
            error_message=f"Adapter for platform {platform} is not connected",
            platform=platform,
            action_type=action_type,
            context=context
        )
    
    # Validate parameters
    is_valid, error_message = await adapter.validate_parameters(action_type, parameters)
    if not is_valid:
        logger.error(f"Invalid parameters for {action_type} on {platform}: {error_message}")
        return ActionResult(
            status=ActionStatus.INVALID_REQUEST,
            error_message=error_message,
            platform=platform,
            action_type=action_type,
            context=context
        )
    
    # Perform the action
    try:
        result = await adapter.perform_action(action_type, parameters, context)
        return result
    except Exception as e:
        logger.exception(f"Error performing {action_type} on {platform}: {e}")
        return ActionResult(
            status=ActionStatus.FAILURE,
            error_message=str(e),
            platform=platform,
            action_type=action_type,
            context=context
        )
