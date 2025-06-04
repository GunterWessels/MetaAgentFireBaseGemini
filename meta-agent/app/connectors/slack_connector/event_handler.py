"""
Slack Event Handler Module

This module provides FastAPI routes for handling Slack events and interactions.
It includes verification of Slack requests, processing of incoming events, and
forwarding them to appropriate handlers.
"""

import hmac
import hashlib
import time
import json
from typing import Dict, Any, Optional, List, Callable, Awaitable
from functools import wraps

from fastapi import APIRouter, Request, Response, Depends, HTTPException, Header, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.utils.logger import setup_logger
from app.utils.config import Config, load_config
from app.connectors.slack_connector.slack_client import SlackConnector
from app.connectors.platform_adapter import ActionContext

# Initialize logger
logger = setup_logger(__name__)

# Create router
router = APIRouter(tags=["slack"])

# Models
class SlackVerificationRequest(BaseModel):
    """Request model for Slack URL verification."""
    token: str
    challenge: str
    type: str

class SlackEventRequest(BaseModel):
    """Request model for Slack events."""
    token: str
    team_id: str
    api_app_id: str
    event: Dict[str, Any]
    type: str
    event_id: str
    event_time: int
    authorizations: Optional[List[Dict[str, Any]]] = None
    is_ext_shared_channel: Optional[bool] = None
    context_team_id: Optional[str] = None
    context_enterprise_id: Optional[str] = None

class SlackInteractionRequest(BaseModel):
    """Request model for Slack interactive components."""
    payload: str

# Global variables
_event_handlers: Dict[str, List[Callable[[Dict[str, Any], SlackConnector], Awaitable[None]]]] = {}

# Dependencies
def get_config() -> Config:
    """Dependency to get configuration."""
    return load_config()

async def get_slack_connector(config: Config = Depends(get_config)) -> SlackConnector:
    """Dependency to get Slack connector."""
    connector = SlackConnector(config)
    await connector.initialize()
    try:
        yield connector
    finally:
        await connector.close()

def verify_slack_request(signing_secret: str):
    """
    Decorator to verify Slack requests using the signing secret.
    
    Args:
        signing_secret: Slack signing secret
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Get the request body
            body = await request.body()
            body_str = body.decode("utf-8")
            
            # Get the Slack signature and timestamp
            slack_signature = request.headers.get("X-Slack-Signature")
            slack_timestamp = request.headers.get("X-Slack-Request-Timestamp")
            
            if not slack_signature or not slack_timestamp:
                logger.warning("Missing Slack signature or timestamp")
                raise HTTPException(status_code=401, detail="Invalid Slack request")
            
            # Check if the timestamp is recent (within 5 minutes)
            current_timestamp = int(time.time())
            if abs(current_timestamp - int(slack_timestamp)) > 300:
                logger.warning("Slack request timestamp is too old")
                raise HTTPException(status_code=401, detail="Request timestamp is too old")
            
            # Create the signature base string
            sig_basestring = f"v0:{slack_timestamp}:{body_str}"
            
            # Create the signature to compare
            my_signature = "v0=" + hmac.new(
                signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            if not hmac.compare_digest(my_signature, slack_signature):
                logger.warning("Invalid Slack signature")
                raise HTTPException(status_code=401, detail="Invalid Slack signature")
            
            # If verification passes, call the original function
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator

def register_event_handler(event_type: str):
    """
    Decorator to register an event handler for a specific Slack event type.
    
    Args:
        event_type: Type of Slack event to handle
    """
    def decorator(func):
        if event_type not in _event_handlers:
            _event_handlers[event_type] = []
        _event_handlers[event_type].append(func)
        logger.info(f"Registered handler for Slack event type: {event_type}")
        return func
    return decorator

@router.post("/slack/events")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    slack_connector: SlackConnector = Depends(get_slack_connector)
):
    """
    Handle incoming Slack events.
    
    This endpoint receives events from Slack and processes them based on their type.
    It supports URL verification, app_mention, message, and other event types.
    
    Args:
        request: The incoming request
        background_tasks: FastAPI background tasks
        config: Application configuration
        slack_connector: Slack connector instance
        
    Returns:
        Response: Appropriate response based on the event type
    """
    # Verify the request if signing secret is configured
    if config.slack_signing_secret:
        # Get the request body
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # Get the Slack signature and timestamp
        slack_signature = request.headers.get("X-Slack-Signature")
        slack_timestamp = request.headers.get("X-Slack-Request-Timestamp")
        
        if slack_signature and slack_timestamp:
            # Check if the timestamp is recent (within 5 minutes)
            current_timestamp = int(time.time())
            if abs(current_timestamp - int(slack_timestamp)) > 300:
                logger.warning("Slack request timestamp is too old")
                raise HTTPException(status_code=401, detail="Request timestamp is too old")
            
            # Create the signature base string
            sig_basestring = f"v0:{slack_timestamp}:{body_str}"
            
            # Create the signature to compare
            my_signature = "v0=" + hmac.new(
                config.slack_signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            if not hmac.compare_digest(my_signature, slack_signature):
                logger.warning("Invalid Slack signature")
                raise HTTPException(status_code=401, detail="Invalid Slack signature")
    
    # Parse the request body
    try:
        body = await request.json()
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    # Handle URL verification
    if body.get("type") == "url_verification":
        logger.info("Handling Slack URL verification")
        return {"challenge": body.get("challenge")}
    
    # Handle events
    if body.get("type") == "event_callback":
        event = body.get("event", {})
        event_type = event.get("type")
        
        if event_type:
            logger.info(f"Received Slack event: {event_type}")
            
            # Process the event in the background
            background_tasks.add_task(
                _process_event,
                event_type=event_type,
                event_data=event,
                body=body,
                slack_connector=slack_connector
            )
        
        # Return a 200 OK response immediately to acknowledge receipt
        return Response(status_code=200)
    
    # Handle other request types
    logger.warning(f"Unhandled Slack request type: {body.get('type')}")
    return Response(status_code=200)

@router.post("/slack/interactions")
async def slack_interactions(
    request: Request,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    slack_connector: SlackConnector = Depends(get_slack_connector)
):
    """
    Handle Slack interactive components.
    
    This endpoint receives interactions from Slack buttons, menus, modals, etc.
    
    Args:
        request: The incoming request
        background_tasks: FastAPI background tasks
        config: Application configuration
        slack_connector: Slack connector instance
        
    Returns:
        Response: Appropriate response based on the interaction type
    """
    # Verify the request if signing secret is configured
    if config.slack_signing_secret:
        # Get the request body
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # Get the Slack signature and timestamp
        slack_signature = request.headers.get("X-Slack-Signature")
        slack_timestamp = request.headers.get("X-Slack-Request-Timestamp")
        
        if slack_signature and slack_timestamp:
            # Check if the timestamp is recent (within 5 minutes)
            current_timestamp = int(time.time())
            if abs(current_timestamp - int(slack_timestamp)) > 300:
                logger.warning("Slack request timestamp is too old")
                raise HTTPException(status_code=401, detail="Request timestamp is too old")
            
            # Create the signature base string
            sig_basestring = f"v0:{slack_timestamp}:{body_str}"
            
            # Create the signature to compare
            my_signature = "v0=" + hmac.new(
                config.slack_signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            if not hmac.compare_digest(my_signature, slack_signature):
                logger.warning("Invalid Slack signature")
                raise HTTPException(status_code=401, detail="Invalid Slack signature")
    
    # Parse the request form data
    form_data = await request.form()
    payload = form_data.get("payload")
    
    if not payload:
        logger.error("Missing payload in Slack interaction")
        raise HTTPException(status_code=400, detail="Missing payload")
    
    try:
        interaction_data = json.loads(payload)
        interaction_type = interaction_data.get("type")
        
        if interaction_type:
            logger.info(f"Received Slack interaction: {interaction_type}")
            
            # Process the interaction in the background
            background_tasks.add_task(
                _process_interaction,
                interaction_type=interaction_type,
                interaction_data=interaction_data,
                slack_connector=slack_connector
            )
        
        # Return a 200 OK response immediately to acknowledge receipt
        return Response(status_code=200)
    except json.JSONDecodeError:
        logger.error("Failed to parse interaction payload")
        raise HTTPException(status_code=400, detail="Invalid payload format")

@router.post("/slack/commands")
async def slack_commands(
    request: Request,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    slack_connector: SlackConnector = Depends(get_slack_connector)
):
    """
    Handle Slack slash commands.
    
    This endpoint receives slash commands from Slack.
    
    Args:
        request: The incoming request
        background_tasks: FastAPI background tasks
        config: Application configuration
        slack_connector: Slack connector instance
        
    Returns:
        Response: Appropriate response for the command
    """
    # Verify the request if signing secret is configured
    if config.slack_signing_secret:
        # Get the request body
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # Get the Slack signature and timestamp
        slack_signature = request.headers.get("X-Slack-Signature")
        slack_timestamp = request.headers.get("X-Slack-Request-Timestamp")
        
        if slack_signature and slack_timestamp:
            # Check if the timestamp is recent (within 5 minutes)
            current_timestamp = int(time.time())
            if abs(current_timestamp - int(slack_timestamp)) > 300:
                logger.warning("Slack request timestamp is too old")
                raise HTTPException(status_code=401, detail="Request timestamp is too old")
            
            # Create the signature base string
            sig_basestring = f"v0:{slack_timestamp}:{body_str}"
            
            # Create the signature to compare
            my_signature = "v0=" + hmac.new(
                config.slack_signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            if not hmac.compare_digest(my_signature, slack_signature):
                logger.warning("Invalid Slack signature")
                raise HTTPException(status_code=401, detail="Invalid Slack signature")
    
    # Parse the request form data
    form_data = await request.form()
    command = form_data.get("command")
    text = form_data.get("text", "")
    user_id = form_data.get("user_id")
    channel_id = form_data.get("channel_id")
    team_id = form_data.get("team_id")
    
    if not command:
        logger.error("Missing command in Slack slash command")
        raise HTTPException(status_code=400, detail="Missing command")
    
    logger.info(f"Received Slack slash command: {command} {text}")
    
    # Process the command in the background
    background_tasks.add_task(
        _process_command,
        command=command,
        text=text,
        user_id=user_id,
        channel_id=channel_id,
        team_id=team_id,
        form_data=dict(form_data),
        slack_connector=slack_connector
    )
    
    # Return an immediate response
    return {
        "response_type": "ephemeral",
        "text": f"Processing your command: {command} {text}"
    }

async def _process_event(
    event_type: str,
    event_data: Dict[str, Any],
    body: Dict[str, Any],
    slack_connector: SlackConnector
):
    """
    Process a Slack event in the background.
    
    Args:
        event_type: Type of event
        event_data: Event data
        body: Full request body
        slack_connector: Slack connector instance
    """
    try:
        # Check if we have handlers for this event type
        handlers = _event_handlers.get(event_type, [])
        
        if handlers:
            # Call each registered handler
            for handler in handlers:
                await handler(event_data, slack_connector)
        else:
            # Default handling based on event type
            if event_type == "app_mention":
                await _handle_app_mention(event_data, slack_connector)
            elif event_type == "message":
                await _handle_message(event_data, slack_connector)
            else:
                logger.info(f"No handler for event type: {event_type}")
    except Exception as e:
        logger.exception(f"Error processing Slack event: {e}")

async def _process_interaction(
    interaction_type: str,
    interaction_data: Dict[str, Any],
    slack_connector: SlackConnector
):
    """
    Process a Slack interaction in the background.
    
    Args:
        interaction_type: Type of interaction
        interaction_data: Interaction data
        slack_connector: Slack connector instance
    """
    try:
        # Handle based on interaction type
        if interaction_type == "block_actions":
            await _handle_block_actions(interaction_data, slack_connector)
        elif interaction_type == "view_submission":
            await _handle_view_submission(interaction_data, slack_connector)
        elif interaction_type == "view_closed":
            await _handle_view_closed(interaction_data, slack_connector)
        else:
            logger.info(f"No handler for interaction type: {interaction_type}")
    except Exception as e:
        logger.exception(f"Error processing Slack interaction: {e}")

async def _process_command(
    command: str,
    text: str,
    user_id: str,
    channel_id: str,
    team_id: str,
    form_data: Dict[str, Any],
    slack_connector: SlackConnector
):
    """
    Process a Slack slash command in the background.
    
    Args:
        command: The command (e.g., "/mycommand")
        text: The text after the command
        user_id: ID of the user who triggered the command
        channel_id: ID of the channel where the command was triggered
        team_id: ID of the team
        form_data: All form data from the request
        slack_connector: Slack connector instance
    """
    try:
        # Create an action context
        import uuid
        context = ActionContext(
            action_id=str(uuid.uuid4()),
            user_id=user_id,
            metadata={
                "channel_id": channel_id,
                "team_id": team_id,
                "command": command,
                "text": text
            }
        )
        
        # Handle based on command
        if command == "/meta":
            # Example command handling
            await _handle_meta_command(text, user_id, channel_id, slack_connector, context)
        else:
            logger.info(f"No handler for command: {command}")
    except Exception as e:
        logger.exception(f"Error processing Slack command: {e}")

# Event handlers

async def _handle_app_mention(event_data: Dict[str, Any], slack_connector: SlackConnector):
    """
    Handle app_mention events.
    
    Args:
        event_data: Event data
        slack_connector: Slack connector instance
    """
    try:
        # Extract relevant information
        user = event_data.get("user")
        text = event_data.get("text", "")
        channel = event_data.get("channel")
        ts = event_data.get("ts")
        
        # Remove the bot mention from the text
        # This assumes the mention is at the beginning of the text
        import re
        cleaned_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
        
        if not cleaned_text:
            # If no text after mention, send a help message
            response_text = "Hello! How can I help you today? Try asking me to do something."
        else:
            # Process the request
            # In a real implementation, this would call the NLU pipeline
            response_text = f"I received your message: '{cleaned_text}'. I'm still learning how to respond to specific requests."
        
        # Create an action context
        import uuid
        context = ActionContext(
            action_id=str(uuid.uuid4()),
            user_id=user,
            metadata={
                "channel": channel,
                "thread_ts": ts,
                "original_text": text
            }
        )
        
        # Send a response
        await slack_connector.perform_action(
            "send_message",
            {
                "channel": channel,
                "text": response_text,
                "thread_ts": ts
            },
            context
        )
    except Exception as e:
        logger.exception(f"Error handling app_mention: {e}")

async def _handle_message(event_data: Dict[str, Any], slack_connector: SlackConnector):
    """
    Handle message events.
    
    Args:
        event_data: Event data
        slack_connector: Slack connector instance
    """
    # Skip bot messages and message_changed events
    if event_data.get("bot_id") or event_data.get("subtype") in ["message_changed", "message_deleted"]:
        return
    
    try:
        # Extract relevant information
        user = event_data.get("user")
        text = event_data.get("text", "")
        channel = event_data.get("channel")
        ts = event_data.get("ts")
        thread_ts = event_data.get("thread_ts")
        
        # Only respond to direct messages or if in a thread where the bot is involved
        is_dm = channel.startswith("D")
        if not is_dm and not thread_ts:
            return
        
        # Create an action context
        import uuid
        context = ActionContext(
            action_id=str(uuid.uuid4()),
            user_id=user,
            metadata={
                "channel": channel,
                "thread_ts": thread_ts or ts,
                "original_text": text
            }
        )
        
        # In a real implementation, this would call the NLU pipeline
        # For now, just echo the message in DMs
        if is_dm:
            await slack_connector.perform_action(
                "send_message",
                {
                    "channel": channel,
                    "text": f"I received your message: '{text}'. I'm still learning how to respond to specific requests.",
                    "thread_ts": thread_ts
                },
                context
            )
    except Exception as e:
        logger.exception(f"Error handling message: {e}")

# Interaction handlers

async def _handle_block_actions(interaction_data: Dict[str, Any], slack_connector: SlackConnector):
    """
    Handle block_actions interactions.
    
    Args:
        interaction_data: Interaction data
        slack_connector: Slack connector instance
    """
    try:
        # Extract relevant information
        user = interaction_data.get("user", {}).get("id")
        actions = interaction_data.get("actions", [])
        channel = interaction_data.get("channel", {}).get("id")
        response_url = interaction_data.get("response_url")
        
        for action in actions:
            action_id = action.get("action_id")
            action_value = action.get("value")
            
            logger.info(f"Received block action: {action_id} with value: {action_value}")
            
            # Create an action context
            import uuid
            context = ActionContext(
                action_id=str(uuid.uuid4()),
                user_id=user,
                metadata={
                    "channel": channel,
                    "response_url": response_url,
                    "block_action_id": action_id,
                    "block_action_value": action_value
                }
            )
            
            # Handle specific actions based on action_id
            # This would be expanded in a real implementation
            if action_id == "approve_button":
                await slack_connector.perform_action(
                    "send_message",
                    {
                        "channel": channel,
                        "text": f"<@{user}> approved the request."
                    },
                    context
                )
            elif action_id == "reject_button":
                await slack_connector.perform_action(
                    "send_message",
                    {
                        "channel": channel,
                        "text": f"<@{user}> rejected the request."
                    },
                    context
                )
    except Exception as e:
        logger.exception(f"Error handling block actions: {e}")

async def _handle_view_submission(interaction_data: Dict[str, Any], slack_connector: SlackConnector):
    """
    Handle view_submission interactions.
    
    Args:
        interaction_data: Interaction data
        slack_connector: Slack connector instance
    """
    try:
        # Extract relevant information
        user = interaction_data.get("user", {}).get("id")
        view = interaction_data.get("view", {})
        view_id = view.get("id")
        state = view.get("state", {}).get("values", {})
        
        logger.info(f"Received view submission for view: {view_id}")
        
        # Process form values
        form_values = {}
        for block_id, block_data in state.items():
            for action_id, action_data in block_data.items():
                # Different action types have different value formats
                if "value" in action_data:
                    form_values[action_id] = action_data["value"]
                elif "selected_option" in action_data:
                    form_values[action_id] = action_data["selected_option"]["value"]
                elif "selected_options" in action_data:
                    form_values[action_id] = [option["value"] for option in action_data["selected_options"]]
                elif "selected_date" in action_data:
                    form_values[action_id] = action_data["selected_date"]
        
        # Create an action context
        import uuid
        context = ActionContext(
            action_id=str(uuid.uuid4()),
            user_id=user,
            metadata={
                "view_id": view_id,
                "form_values": form_values
            }
        )
        
        # Handle the form submission based on the callback_id
        callback_id = view.get("callback_id")
        if callback_id == "task_creation_form":
            # Example: Process a task creation form
            task_title = form_values.get("task_title", "Untitled Task")
            task_description = form_values.get("task_description", "")
            task_due_date = form_values.get("task_due_date")
            
            # In a real implementation, this would create a task in the system
            logger.info(f"Creating task: {task_title} due on {task_due_date}")
            
            # Send a confirmation message to the user
            await slack_connector.perform_action(
                "send_message",
                {
                    "channel": user,  # DM to the user
                    "text": f"Task created: *{task_title}*\nDue date: {task_due_date or 'None'}\nDescription: {task_description or 'None'}"
                },
                context
            )
    except Exception as e:
        logger.exception(f"Error handling view submission: {e}")

async def _handle_view_closed(interaction_data: Dict[str, Any], slack_connector: SlackConnector):
    """
    Handle view_closed interactions.
    
    Args:
        interaction_data: Interaction data
        slack_connector: Slack connector instance
    """
    # This is called when a user closes a modal without submitting
    # In most cases, no action is needed
    pass

# Command handlers

async def _handle_meta_command(
    text: str,
    user_id: str,
    channel_id: str,
    slack_connector: SlackConnector,
    context: ActionContext
):
    """
    Handle the /meta slash command.
    
    Args:
        text: Command text
        user_id: User ID
        channel_id: Channel ID
        slack_connector: Slack connector instance
        context: Action context
    """
    try:
        # Parse the command text
        parts = text.strip().split()
        subcommand = parts[0].lower() if parts else "help"
        
        if subcommand == "help":
            # Send help information
            help_text = (
                "*Meta-Agent Slack Commands*\n\n"
                "*/meta help* - Show this help message\n"
                "*/meta create task* <title> - Create a new task\n"
                "*/meta list tasks* - List your active tasks\n"
                "*/meta status* - Show system status\n"
            )
            
            await slack_connector.perform_action(
                "send_message",
                {
                    "channel": channel_id,
                    "text": help_text
                },
                context
            )
        elif subcommand == "create" and len(parts) >= 3 and parts[1].lower() == "task":
            # Create a task
            task_title = " ".join(parts[2:])
            
            # In a real implementation, this would create a task in the system
            # For now, just acknowledge the command
            await slack_connector.perform_action(
                "send_message",
                {
                    "channel": channel_id,
                    "text": f"Creating task: *{task_title}*"
                },
                context
            )
        elif subcommand == "list" and len(parts) >= 2 and parts[1].lower() == "tasks":
            # List tasks
            # In a real implementation, this would fetch tasks from the system
            await slack_connector.perform_action(
                "send_message",
                {
                    "channel": channel_id,
                    "text": "You have no active tasks."
                },
                context
            )
        elif subcommand == "status":
            # Show system status
            await slack_connector.perform_action(
                "send_message",
                {
                    "channel": channel_id,
                    "text": "Meta-Agent is running normally."
                },
                context
            )
        else:
            # Unknown subcommand
            await slack_connector.perform_action(
                "send_message",
                {
                    "channel": channel_id,
                    "text": f"Unknown command: `{text}`. Try `/meta help` for available commands."
                },
                context
            )
    except Exception as e:
        logger.exception(f"Error handling meta command: {e}")
        
        # Send error message
        await slack_connector.perform_action(
            "send_message",
            {
                "channel": channel_id,
                "text": f"Error processing command: {str(e)}"
            },
            context
        )

# Register event handlers
@register_event_handler("app_mention")
async def handle_app_mention(event_data: Dict[str, Any], slack_connector: SlackConnector):
    """
    Handle app_mention events.
    
    Args:
        event_data: Event data
        slack_connector: Slack connector instance
    """
    await _handle_app_mention(event_data, slack_connector)

@register_event_handler("message")
async def handle_message(event_data: Dict[str, Any], slack_connector: SlackConnector):
    """
    Handle message events.
    
    Args:
        event_data: Event data
        slack_connector: Slack connector instance
    """
    await _handle_message(event_data, slack_connector)
