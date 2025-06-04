"""
Plan Generator Module

This module is responsible for mapping parsed intents and slots to sub-agent
specifications. It generates execution plans based on the user's goals and
available connectors.

The plan generator determines which actions to take and which sub-agents to deploy
to fulfill the user's request.
"""

import json
import os
from typing import Dict, List, Any, Optional, Union, Tuple
from enum import Enum
from pathlib import Path
import importlib

import jinja2
from pydantic import BaseModel, Field, validator

from app.utils.logger import setup_logger
from app.utils.config import Config
from app.nlu.parse_goal_chain import ParsedGoal, Intent, Slot

# Initialize logger
logger = setup_logger(__name__)

class ActionType(str, Enum):
    """Types of actions that can be performed by sub-agents."""
    QUERY = "query"              # Retrieve information
    CREATE = "create"            # Create a new resource
    UPDATE = "update"            # Update an existing resource
    DELETE = "delete"            # Delete a resource
    NOTIFY = "notify"            # Send a notification
    SCHEDULE = "schedule"        # Schedule a task or event
    MONITOR = "monitor"          # Monitor for changes or events
    ANALYZE = "analyze"          # Analyze data or information
    TRANSFORM = "transform"      # Transform data from one format to another
    CUSTOM = "custom"            # Custom action defined by a template

class PlatformType(str, Enum):
    """Supported platform types."""
    SLACK = "slack"
    JIRA = "jira"
    EMAIL = "email"
    CALENDAR = "calendar"
    GENERIC = "generic"
    CUSTOM = "custom"

class ExecutionMode(str, Enum):
    """Execution modes for plans."""
    SYNCHRONOUS = "synchronous"   # Execute steps in sequence
    ASYNCHRONOUS = "asynchronous" # Execute steps in parallel
    CONDITIONAL = "conditional"   # Execute steps based on conditions
    PERIODIC = "periodic"         # Execute steps on a schedule

class ActionParameter(BaseModel):
    """Parameter for an action."""
    name: str = Field(..., description="Name of the parameter")
    value: Any = Field(..., description="Value of the parameter")
    source: str = Field("slot", description="Source of the parameter (slot, config, default)")
    required: bool = Field(True, description="Whether the parameter is required")

class ActionStep(BaseModel):
    """Step in an execution plan."""
    id: str = Field(..., description="Unique identifier for the step")
    name: str = Field(..., description="Name of the step")
    description: str = Field(..., description="Description of what the step does")
    action_type: ActionType = Field(..., description="Type of action to perform")
    platform: PlatformType = Field(..., description="Platform to execute the action on")
    parameters: List[ActionParameter] = Field(default_factory=list, description="Parameters for the action")
    template: Optional[str] = Field(None, description="Template to use for code generation")
    depends_on: List[str] = Field(default_factory=list, description="IDs of steps this step depends on")
    condition: Optional[str] = Field(None, description="Condition for executing this step")
    retry_policy: Optional[Dict[str, Any]] = Field(None, description="Retry policy for the step")
    timeout: Optional[int] = Field(None, description="Timeout in seconds")

class ExecutionPlan(BaseModel):
    """Complete execution plan for a goal."""
    id: str = Field(..., description="Unique identifier for the plan")
    goal_id: str = Field(..., description="ID of the goal this plan is for")
    intent: str = Field(..., description="Primary intent of the goal")
    steps: List[ActionStep] = Field(..., description="Steps to execute")
    execution_mode: ExecutionMode = Field(ExecutionMode.SYNCHRONOUS, description="How to execute the steps")
    created_at: str = Field(..., description="When the plan was created")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

class PlanGenerator:
    """
    Plan Generator for mapping intents to execution plans.
    
    This class is responsible for generating execution plans based on parsed goals.
    It maps intents to specific actions and generates sub-agent specifications.
    """
    
    def __init__(self, config: Config):
        """
        Initialize the Plan Generator.
        
        Args:
            config: Application configuration
        """
        self.config = config
        
        # Set up template environment
        templates_dir = Path(config.templates_dir)
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(templates_dir),
            autoescape=jinja2.select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Load intent-to-action mappings
        self.intent_mappings = self._load_intent_mappings()
        
        logger.info("PlanGenerator initialized")
    
    def _load_intent_mappings(self) -> Dict[str, Dict[str, Any]]:
        """
        Load mappings from intents to action templates.
        
        Returns:
            Dictionary mapping intent names to action templates
        """
        # This could be loaded from a configuration file or database
        # For now, we'll define it directly
        
        mappings = {
            "create_task": {
                "description": "Create a new task or reminder",
                "platforms": {
                    "slack": {
                        "action_type": ActionType.CREATE,
                        "template": "slack_create_task.j2",
                        "required_slots": ["topic", "date"],
                        "optional_slots": ["priority", "person", "description"]
                    },
                    "jira": {
                        "action_type": ActionType.CREATE,
                        "template": "jira_create_issue.j2",
                        "required_slots": ["topic", "priority"],
                        "optional_slots": ["description", "assignee", "due_date"]
                    },
                    "generic": {
                        "action_type": ActionType.CREATE,
                        "template": "generic_task.j2",
                        "required_slots": ["topic"],
                        "optional_slots": ["date", "priority", "person", "description"]
                    }
                }
            },
            "schedule_meeting": {
                "description": "Schedule a meeting or appointment",
                "platforms": {
                    "slack": {
                        "action_type": ActionType.SCHEDULE,
                        "template": "slack_schedule_meeting.j2",
                        "required_slots": ["topic", "date", "time"],
                        "optional_slots": ["duration", "person", "description", "location"]
                    },
                    "calendar": {
                        "action_type": ActionType.CREATE,
                        "template": "calendar_create_event.j2",
                        "required_slots": ["topic", "date", "time"],
                        "optional_slots": ["duration", "attendees", "description", "location"]
                    },
                    "generic": {
                        "action_type": ActionType.SCHEDULE,
                        "template": "generic_meeting.j2",
                        "required_slots": ["topic", "date"],
                        "optional_slots": ["time", "duration", "person", "description", "location"]
                    }
                }
            },
            "find_information": {
                "description": "Find or retrieve information",
                "platforms": {
                    "slack": {
                        "action_type": ActionType.QUERY,
                        "template": "slack_search.j2",
                        "required_slots": ["topic"],
                        "optional_slots": ["channel", "time_range", "from_person"]
                    },
                    "jira": {
                        "action_type": ActionType.QUERY,
                        "template": "jira_search.j2",
                        "required_slots": ["topic"],
                        "optional_slots": ["project", "status", "assignee"]
                    },
                    "generic": {
                        "action_type": ActionType.QUERY,
                        "template": "generic_search.j2",
                        "required_slots": ["topic"],
                        "optional_slots": ["source", "time_range", "filter"]
                    }
                }
            },
            "send_message": {
                "description": "Send a message to someone",
                "platforms": {
                    "slack": {
                        "action_type": ActionType.NOTIFY,
                        "template": "slack_send_message.j2",
                        "required_slots": ["person", "content"],
                        "optional_slots": ["channel", "scheduled_time"]
                    },
                    "email": {
                        "action_type": ActionType.NOTIFY,
                        "template": "email_send.j2",
                        "required_slots": ["person", "content", "subject"],
                        "optional_slots": ["cc", "bcc", "scheduled_time", "attachments"]
                    },
                    "generic": {
                        "action_type": ActionType.NOTIFY,
                        "template": "generic_message.j2",
                        "required_slots": ["person", "content"],
                        "optional_slots": ["subject", "scheduled_time"]
                    }
                }
            },
            "update_status": {
                "description": "Update the status of something",
                "platforms": {
                    "slack": {
                        "action_type": ActionType.UPDATE,
                        "template": "slack_update_status.j2",
                        "required_slots": ["topic", "status"],
                        "optional_slots": ["channel", "notify_person"]
                    },
                    "jira": {
                        "action_type": ActionType.UPDATE,
                        "template": "jira_update_status.j2",
                        "required_slots": ["topic", "status"],
                        "optional_slots": ["comment", "assignee"]
                    },
                    "generic": {
                        "action_type": ActionType.UPDATE,
                        "template": "generic_status_update.j2",
                        "required_slots": ["topic", "status"],
                        "optional_slots": ["comment", "notify"]
                    }
                }
            }
        }
        
        return mappings
    
    def _select_platform(self, intent: str, slots: List[Slot]) -> PlatformType:
        """
        Select the most appropriate platform for an intent based on available slots.
        
        Args:
            intent: The intent name
            slots: List of available slots
            
        Returns:
            Selected platform type
        """
        # Extract platform from slots if specified
        platform_slot = next((slot for slot in slots if slot.name.lower() == "platform"), None)
        if platform_slot:
            platform_name = platform_slot.value.lower()
            try:
                return PlatformType(platform_name)
            except ValueError:
                logger.warning(f"Unknown platform '{platform_name}', falling back to default")
        
        # Check if we have platform-specific slots
        slot_names = {slot.name.lower() for slot in slots}
        
        # Platform-specific indicators
        platform_indicators = {
            "slack": {"channel", "slack", "workspace"},
            "jira": {"project", "issue", "ticket", "jira"},
            "email": {"email", "subject", "cc", "bcc"},
            "calendar": {"calendar", "attendees", "meeting_link"}
        }
        
        # Check for platform-specific indicators in slots
        for platform, indicators in platform_indicators.items():
            if any(indicator in slot_names for indicator in indicators):
                try:
                    return PlatformType(platform)
                except ValueError:
                    continue
        
        # Check if the intent mapping has a preferred platform
        intent_config = self.intent_mappings.get(intent, {})
        platforms = intent_config.get("platforms", {})
        
        # Prioritize platforms based on configuration and available slots
        for platform in ["slack", "jira", "email", "calendar"]:
            if platform in platforms:
                platform_config = platforms[platform]
                required_slots = set(platform_config.get("required_slots", []))
                if required_slots and required_slots.issubset(slot_names):
                    return PlatformType(platform)
        
        # Default to generic if no specific platform is determined
        return PlatformType.GENERIC
    
    def _create_action_parameters(
        self, slots: List[Slot], required_slots: List[str], optional_slots: List[str]
    ) -> List[ActionParameter]:
        """
        Create action parameters from slots.
        
        Args:
            slots: List of available slots
            required_slots: List of required slot names
            optional_slots: List of optional slot names
            
        Returns:
            List of action parameters
        """
        parameters = []
        
        # Create a dictionary of slots by name for easy lookup
        slot_dict = {slot.name.lower(): slot for slot in slots}
        
        # Add required parameters
        for slot_name in required_slots:
            slot = slot_dict.get(slot_name.lower())
            if slot:
                parameters.append(
                    ActionParameter(
                        name=slot_name,
                        value=slot.value,
                        source="slot",
                        required=True
                    )
                )
            else:
                # Add placeholder for missing required parameter
                parameters.append(
                    ActionParameter(
                        name=slot_name,
                        value=None,
                        source="default",
                        required=True
                    )
                )
        
        # Add optional parameters if available
        for slot_name in optional_slots:
            slot = slot_dict.get(slot_name.lower())
            if slot:
                parameters.append(
                    ActionParameter(
                        name=slot_name,
                        value=slot.value,
                        source="slot",
                        required=False
                    )
                )
        
        return parameters
    
    async def generate_plan(self, parsed_goal: ParsedGoal, goal_id: str) -> ExecutionPlan:
        """
        Generate an execution plan based on a parsed goal.
        
        Args:
            parsed_goal: The parsed goal with intents and slots
            goal_id: ID of the goal this plan is for
            
        Returns:
            ExecutionPlan: The generated execution plan
        """
        # Get the primary intent
        primary_intent = parsed_goal.get_primary_intent()
        if not primary_intent:
            raise ValueError("No intent could be determined from the parsed goal")
        
        intent_name = primary_intent.name
        
        # Check if we have a mapping for this intent
        if intent_name not in self.intent_mappings:
            logger.warning(f"No mapping found for intent '{intent_name}', using generic approach")
            return self._generate_generic_plan(parsed_goal, goal_id)
        
        # Select the appropriate platform
        platform = self._select_platform(intent_name, parsed_goal.slots)
        
        # Get the intent configuration
        intent_config = self.intent_mappings[intent_name]
        platform_config = intent_config.get("platforms", {}).get(
            platform.value, 
            intent_config.get("platforms", {}).get("generic", {})
        )
        
        if not platform_config:
            logger.warning(f"No platform configuration found for {platform.value}, using generic approach")
            return self._generate_generic_plan(parsed_goal, goal_id)
        
        # Get required and optional slots
        required_slots = platform_config.get("required_slots", [])
        optional_slots = platform_config.get("optional_slots", [])
        
        # Create action parameters
        parameters = self._create_action_parameters(
            parsed_goal.slots, required_slots, optional_slots
        )
        
        # Create a unique ID for the plan
        import uuid
        from datetime import datetime
        
        plan_id = str(uuid.uuid4())
        step_id = str(uuid.uuid4())
        
        # Create the action step
        step = ActionStep(
            id=step_id,
            name=f"{intent_name}_{platform.value}",
            description=intent_config.get("description", f"Execute {intent_name} on {platform.value}"),
            action_type=platform_config.get("action_type", ActionType.CUSTOM),
            platform=platform,
            parameters=parameters,
            template=platform_config.get("template")
        )
        
        # Create the execution plan
        plan = ExecutionPlan(
            id=plan_id,
            goal_id=goal_id,
            intent=intent_name,
            steps=[step],
            execution_mode=ExecutionMode.SYNCHRONOUS,
            created_at=datetime.utcnow().isoformat(),
            metadata={
                "original_text": parsed_goal.raw_text,
                "confidence": primary_intent.confidence
            }
        )
        
        logger.info(f"Generated execution plan {plan_id} for intent {intent_name} on {platform.value}")
        return plan
    
    def _generate_generic_plan(self, parsed_goal: ParsedGoal, goal_id: str) -> ExecutionPlan:
        """
        Generate a generic execution plan when no specific mapping is available.
        
        Args:
            parsed_goal: The parsed goal with intents and slots
            goal_id: ID of the goal this plan is for
            
        Returns:
            ExecutionPlan: A generic execution plan
        """
        # Get the primary intent or use "custom" if none
        primary_intent = parsed_goal.get_primary_intent()
        intent_name = primary_intent.name if primary_intent else "custom"
        
        # Create unique IDs
        import uuid
        from datetime import datetime
        
        plan_id = str(uuid.uuid4())
        step_id = str(uuid.uuid4())
        
        # Create parameters from all available slots
        parameters = [
            ActionParameter(
                name=slot.name,
                value=slot.value,
                source="slot",
                required=True
            )
            for slot in parsed_goal.slots
        ]
        
        # Create a generic action step
        step = ActionStep(
            id=step_id,
            name=f"generic_{intent_name}",
            description=f"Execute {intent_name} using available information",
            action_type=ActionType.CUSTOM,
            platform=PlatformType.GENERIC,
            parameters=parameters,
            template="generic_lambda.j2"
        )
        
        # Create the execution plan
        plan = ExecutionPlan(
            id=plan_id,
            goal_id=goal_id,
            intent=intent_name,
            steps=[step],
            execution_mode=ExecutionMode.SYNCHRONOUS,
            created_at=datetime.utcnow().isoformat(),
            metadata={
                "original_text": parsed_goal.raw_text,
                "is_generic": True,
                "confidence": primary_intent.confidence if primary_intent else 0.0
            }
        )
        
        logger.info(f"Generated generic execution plan {plan_id} for intent {intent_name}")
        return plan
    
    async def generate_code(self, plan: ExecutionPlan) -> Dict[str, str]:
        """
        Generate code for sub-agents based on the execution plan.
        
        Args:
            plan: The execution plan
            
        Returns:
            Dictionary mapping file names to generated code
        """
        generated_code = {}
        
        for step in plan.steps:
            if not step.template:
                continue
            
            try:
                # Load the template
                template = self.template_env.get_template(step.template)
                
                # Prepare template variables
                template_vars = {
                    "step": step,
                    "plan": plan,
                    "parameters": {param.name: param.value for param in step.parameters},
                    "config": self.config
                }
                
                # Render the template
                code = template.render(**template_vars)
                
                # Generate a file name
                file_name = f"{step.name}_{step.id[:8]}.py"
                
                # Add to generated code dictionary
                generated_code[file_name] = code
                
                logger.info(f"Generated code for step {step.id} using template {step.template}")
                
            except Exception as e:
                logger.error(f"Error generating code for step {step.id}: {e}")
                # Add error information to the output
                file_name = f"error_{step.id[:8]}.txt"
                generated_code[file_name] = f"Error generating code: {str(e)}"
        
        return generated_code
    
    def get_required_slots_for_intent(self, intent_name: str, platform: Optional[str] = None) -> List[str]:
        """
        Get the list of required slots for a specific intent and platform.
        
        Args:
            intent_name: The name of the intent
            platform: Optional platform name
            
        Returns:
            List of required slot names
        """
        # Check if we have a mapping for this intent
        if intent_name not in self.intent_mappings:
            return []
        
        # Get the intent configuration
        intent_config = self.intent_mappings[intent_name]
        
        # If platform is specified, get that platform's required slots
        if platform and platform in intent_config.get("platforms", {}):
            return intent_config["platforms"][platform].get("required_slots", [])
        
        # Otherwise, get all unique required slots across platforms
        required_slots = set()
        for platform_config in intent_config.get("platforms", {}).values():
            required_slots.update(platform_config.get("required_slots", []))
        
        return list(required_slots)
