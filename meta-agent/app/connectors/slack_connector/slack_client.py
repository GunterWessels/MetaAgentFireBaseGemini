"""
Slack Connector Module

This module provides a connector for interacting with the Slack platform.
It implements the PlatformAdapter interface and provides methods for
performing actions on Slack such as sending messages, creating channels,
and retrieving information.
"""

import os
import re
import json
import asyncio
import logging
from typing import Dict, List, Any, Optional, Union, Tuple, cast
from datetime import datetime, timedelta

import slack_sdk
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from app.connectors.platform_adapter import (
    PlatformAdapter, 
    ActionResult, 
    ActionStatus, 
    ActionContext
)
from app.utils.logger import setup_logger
from app.utils.config import Config

# Initialize logger
logger = setup_logger(__name__)

class SlackConnector(PlatformAdapter):
    """
    Slack connector for the Meta-Agent.
    
    This class implements the PlatformAdapter interface for the Slack platform.
    It provides methods for performing actions on Slack such as sending messages,
    creating channels, and retrieving information.
    """
    
    def __init__(self, config: Config):
        """
        Initialize the Slack connector.
        
        Args:
            config: Application configuration containing Slack credentials
        """
        self.config = config
        self.token = config.slack_api_token
        self.signing_secret = config.slack_signing_secret
        self.client = None
        self.async_client = None
        self._connected = False
        
        # Define supported actions and their parameters
        self._supported_actions = {
            "send_message": {
                "required": ["channel", "text"],
                "optional": ["thread_ts", "blocks", "attachments", "unfurl_links", "reply_broadcast"]
            },
            "create_channel": {
                "required": ["name"],
                "optional": ["is_private", "user_ids"]
            },
            "invite_to_channel": {
                "required": ["channel", "user_ids"],
                "optional": []
            },
            "get_channel_history": {
                "required": ["channel"],
                "optional": ["latest", "oldest", "inclusive", "limit"]
            },
            "search_messages": {
                "required": ["query"],
                "optional": ["sort", "sort_dir", "count", "page"]
            },
            "update_message": {
                "required": ["channel", "ts", "text"],
                "optional": ["blocks", "attachments", "as_user"]
            },
            "delete_message": {
                "required": ["channel", "ts"],
                "optional": ["as_user"]
            },
            "create_reminder": {
                "required": ["text", "time"],
                "optional": ["user"]
            },
            "get_user_info": {
                "required": ["user"],
                "optional": ["include_locale"]
            },
            "set_status": {
                "required": ["status_text", "status_emoji"],
                "optional": ["status_expiration"]
            }
        }
        
        logger.info("Slack connector initialized")
    
    @property
    def platform_name(self) -> str:
        """Get the name of the platform."""
        return "slack"
    
    async def initialize(self) -> bool:
        """
        Initialize the Slack connector.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        if not self.token:
            logger.error("Slack API token not provided")
            return False
        
        try:
            # Initialize the sync client for operations that don't have async equivalents
            self.client = WebClient(token=self.token)
            
            # Initialize the async client for most operations
            self.async_client = AsyncWebClient(token=self.token)
            
            # Test the connection
            response = await self.async_client.auth_test()
            if response["ok"]:
                self._connected = True
                logger.info(f"Connected to Slack as {response['user']} in workspace {response['team']}")
                return True
            else:
                logger.error(f"Failed to connect to Slack: {response}")
                return False
        except Exception as e:
            logger.exception(f"Error initializing Slack connector: {e}")
            return False
    
    async def close(self) -> None:
        """Close the connector and clean up resources."""
        # The Slack SDK doesn't require explicit cleanup
        self._connected = False
        logger.info("Slack connector closed")
    
    async def is_connected(self) -> bool:
        """
        Check if the connector is connected to the platform.
        
        Returns:
            bool: True if connected, False otherwise
        """
        if not self._connected or not self.async_client:
            return False
        
        try:
            # Re-test the connection
            response = await self.async_client.auth_test()
            return response["ok"]
        except Exception:
            self._connected = False
            return False
    
    async def perform_action(
        self, action_type: str, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Perform an action on Slack.
        
        Args:
            action_type: Type of action to perform
            parameters: Parameters for the action
            context: Context for the action
            
        Returns:
            ActionResult: Result of the action
        """
        if not self._connected:
            return ActionResult(
                status=ActionStatus.UNAUTHORIZED,
                error_message="Not connected to Slack",
                platform=self.platform_name,
                action_type=action_type,
                context=context
            )
        
        if action_type not in self._supported_actions:
            return ActionResult(
                status=ActionStatus.INVALID_REQUEST,
                error_message=f"Unsupported action type: {action_type}",
                platform=self.platform_name,
                action_type=action_type,
                context=context
            )
        
        # Validate parameters
        is_valid, error_message = await self.validate_parameters(action_type, parameters)
        if not is_valid:
            return ActionResult(
                status=ActionStatus.INVALID_REQUEST,
                error_message=error_message,
                platform=self.platform_name,
                action_type=action_type,
                context=context
            )
        
        try:
            # Dispatch to the appropriate method based on action type
            method_name = f"_action_{action_type}"
            if hasattr(self, method_name):
                method = getattr(self, method_name)
                result = await method(parameters, context)
                return result
            else:
                # Fallback for actions without specific implementations
                return await self._generic_action(action_type, parameters, context)
        except SlackApiError as e:
            # Handle Slack API errors
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 60))
                return ActionResult(
                    status=ActionStatus.RATE_LIMITED,
                    error_message=f"Rate limited by Slack. Retry after {retry_after} seconds.",
                    platform=self.platform_name,
                    action_type=action_type,
                    context=context,
                    data={"retry_after": retry_after}
                )
            elif e.response["error"] == "not_authed":
                self._connected = False
                return ActionResult(
                    status=ActionStatus.UNAUTHORIZED,
                    error_message="Not authenticated with Slack",
                    platform=self.platform_name,
                    action_type=action_type,
                    context=context
                )
            else:
                return ActionResult(
                    status=ActionStatus.FAILURE,
                    error_message=f"Slack API error: {e.response['error']}",
                    platform=self.platform_name,
                    action_type=action_type,
                    context=context,
                    data={"slack_error": e.response["error"]}
                )
        except Exception as e:
            logger.exception(f"Error performing {action_type} on Slack: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type=action_type,
                context=context
            )
    
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
        if action_type not in self._supported_actions:
            return False, f"Unsupported action type: {action_type}"
        
        # Check required parameters
        required_params = self._supported_actions[action_type]["required"]
        for param in required_params:
            if param not in parameters:
                return False, f"Missing required parameter: {param}"
            
            # Check for empty values
            if parameters[param] is None or (isinstance(parameters[param], str) and not parameters[param].strip()):
                return False, f"Required parameter {param} cannot be empty"
        
        # Action-specific validations
        if action_type == "send_message":
            # Validate channel format
            channel = parameters.get("channel", "")
            if not channel.startswith(("#", "D", "C", "G")) and not re.match(r"^[A-Z0-9]+$", channel):
                return False, f"Invalid channel format: {channel}"
        
        elif action_type == "create_channel":
            # Validate channel name
            name = parameters.get("name", "")
            if not re.match(r"^[a-z0-9_-]{1,80}$", name):
                return False, "Channel name can only contain lowercase letters, numbers, hyphens, and underscores"
        
        return True, None
    
    def get_supported_actions(self) -> List[str]:
        """
        Get a list of actions supported by this connector.
        
        Returns:
            List[str]: List of supported action types
        """
        return list(self._supported_actions.keys())
    
    def get_required_parameters(self, action_type: str) -> List[str]:
        """
        Get a list of required parameters for an action.
        
        Args:
            action_type: Type of action
            
        Returns:
            List[str]: List of required parameter names
        """
        if action_type not in self._supported_actions:
            return []
        return self._supported_actions[action_type]["required"]
    
    def get_optional_parameters(self, action_type: str) -> List[str]:
        """
        Get a list of optional parameters for an action.
        
        Args:
            action_type: Type of action
            
        Returns:
            List[str]: List of optional parameter names
        """
        if action_type not in self._supported_actions:
            return []
        return self._supported_actions[action_type]["optional"]
    
    # Action implementations
    
    async def _action_send_message(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Send a message to a Slack channel or user.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            channel = parameters["channel"]
            text = parameters["text"]
            thread_ts = parameters.get("thread_ts")
            blocks = parameters.get("blocks")
            attachments = parameters.get("attachments")
            unfurl_links = parameters.get("unfurl_links", True)
            reply_broadcast = parameters.get("reply_broadcast", False)
            
            # Build the message payload
            message_params = {
                "channel": channel,
                "text": text,
                "unfurl_links": unfurl_links
            }
            
            if thread_ts:
                message_params["thread_ts"] = thread_ts
                if reply_broadcast:
                    message_params["reply_broadcast"] = reply_broadcast
            
            if blocks:
                message_params["blocks"] = blocks
            
            if attachments:
                message_params["attachments"] = attachments
            
            # Send the message
            response = await self.async_client.chat_postMessage(**message_params)
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="send_message",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error sending message: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="send_message",
                context=context
            )
    
    async def _action_create_channel(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Create a new Slack channel.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            name = parameters["name"]
            is_private = parameters.get("is_private", False)
            user_ids = parameters.get("user_ids", [])
            
            # Create the channel
            if is_private:
                response = await self.async_client.conversations_create(
                    name=name,
                    is_private=True
                )
            else:
                response = await self.async_client.conversations_create(
                    name=name,
                    is_private=False
                )
            
            channel_id = response["channel"]["id"]
            
            # Invite users if specified
            if user_ids:
                await self.async_client.conversations_invite(
                    channel=channel_id,
                    users=user_ids if isinstance(user_ids, str) else ",".join(user_ids)
                )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="create_channel",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error creating channel: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="create_channel",
                context=context
            )
    
    async def _action_invite_to_channel(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Invite users to a Slack channel.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            channel = parameters["channel"]
            user_ids = parameters["user_ids"]
            
            # Convert user_ids to string if it's a list
            if isinstance(user_ids, list):
                user_ids = ",".join(user_ids)
            
            # Invite users
            response = await self.async_client.conversations_invite(
                channel=channel,
                users=user_ids
            )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="invite_to_channel",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error inviting to channel: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="invite_to_channel",
                context=context
            )
    
    async def _action_get_channel_history(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Get the message history of a Slack channel.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            channel = parameters["channel"]
            latest = parameters.get("latest")
            oldest = parameters.get("oldest")
            inclusive = parameters.get("inclusive", False)
            limit = parameters.get("limit", 100)
            
            # Build the request parameters
            history_params = {
                "channel": channel,
                "limit": limit,
                "inclusive": inclusive
            }
            
            if latest:
                history_params["latest"] = latest
            
            if oldest:
                history_params["oldest"] = oldest
            
            # Get the history
            response = await self.async_client.conversations_history(**history_params)
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="get_channel_history",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error getting channel history: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="get_channel_history",
                context=context
            )
    
    async def _action_search_messages(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Search for messages in Slack.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            query = parameters["query"]
            sort = parameters.get("sort", "score")
            sort_dir = parameters.get("sort_dir", "desc")
            count = parameters.get("count", 20)
            page = parameters.get("page", 1)
            
            # Search messages
            response = await self.async_client.search_messages(
                query=query,
                sort=sort,
                sort_dir=sort_dir,
                count=count,
                page=page
            )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="search_messages",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error searching messages: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="search_messages",
                context=context
            )
    
    async def _action_update_message(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Update a message in Slack.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            channel = parameters["channel"]
            ts = parameters["ts"]
            text = parameters["text"]
            blocks = parameters.get("blocks")
            attachments = parameters.get("attachments")
            as_user = parameters.get("as_user", True)
            
            # Build the update parameters
            update_params = {
                "channel": channel,
                "ts": ts,
                "text": text,
                "as_user": as_user
            }
            
            if blocks:
                update_params["blocks"] = blocks
            
            if attachments:
                update_params["attachments"] = attachments
            
            # Update the message
            response = await self.async_client.chat_update(**update_params)
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="update_message",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error updating message: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="update_message",
                context=context
            )
    
    async def _action_delete_message(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Delete a message in Slack.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            channel = parameters["channel"]
            ts = parameters["ts"]
            as_user = parameters.get("as_user", True)
            
            # Delete the message
            response = await self.async_client.chat_delete(
                channel=channel,
                ts=ts,
                as_user=as_user
            )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="delete_message",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error deleting message: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="delete_message",
                context=context
            )
    
    async def _action_create_reminder(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Create a reminder in Slack.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            text = parameters["text"]
            time_param = parameters["time"]  # Can be a timestamp or natural language like "in 30 minutes"
            user = parameters.get("user", "me")
            
            # Create the reminder
            response = await self.async_client.reminders_add(
                text=text,
                time=time_param,
                user=user
            )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="create_reminder",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error creating reminder: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="create_reminder",
                context=context
            )
    
    async def _action_get_user_info(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Get information about a Slack user.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            user = parameters["user"]
            include_locale = parameters.get("include_locale", False)
            
            # Get user info
            response = await self.async_client.users_info(
                user=user,
                include_locale=include_locale
            )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="get_user_info",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error getting user info: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="get_user_info",
                context=context
            )
    
    async def _action_set_status(
        self, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Set a user's status in Slack.
        
        Args:
            parameters: Action parameters
            context: Action context
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Extract parameters
            status_text = parameters["status_text"]
            status_emoji = parameters["status_emoji"]
            status_expiration = parameters.get("status_expiration", 0)
            
            # Build the profile
            profile = {
                "status_text": status_text,
                "status_emoji": status_emoji,
                "status_expiration": status_expiration
            }
            
            # Set the status
            response = await self.async_client.users_profile_set(
                profile=profile
            )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type="set_status",
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error setting status: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type="set_status",
                context=context
            )
    
    async def _generic_action(
        self, action_type: str, parameters: Dict[str, Any], context: ActionContext
    ) -> ActionResult:
        """
        Perform a generic action by calling the Slack API directly.
        
        This is a fallback for actions that don't have specific implementations.
        
        Args:
            action_type: Type of action to perform
            parameters: Parameters for the action
            context: Context for the action
            
        Returns:
            ActionResult: Result of the action
        """
        try:
            # Convert action_type to a method name (e.g., "send_message" -> "chat_postMessage")
            method_map = {
                "send_message": "chat_postMessage",
                "create_channel": "conversations_create",
                "invite_to_channel": "conversations_invite",
                "get_channel_history": "conversations_history",
                "search_messages": "search_messages",
                "update_message": "chat_update",
                "delete_message": "chat_delete",
                "create_reminder": "reminders_add",
                "get_user_info": "users_info",
                "set_status": "users_profile_set"
            }
            
            method_name = method_map.get(action_type, action_type.replace("_", ".", 1))
            
            # Check if the method exists
            if not hasattr(self.async_client, method_name):
                return ActionResult(
                    status=ActionStatus.INVALID_REQUEST,
                    error_message=f"Unsupported Slack API method: {method_name}",
                    platform=self.platform_name,
                    action_type=action_type,
                    context=context
                )
            
            # Call the method
            method = getattr(self.async_client, method_name)
            response = await method(**parameters)
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=response,
                platform=self.platform_name,
                action_type=action_type,
                context=context
            )
        except SlackApiError as e:
            raise e
        except Exception as e:
            logger.exception(f"Error performing generic action {action_type}: {e}")
            return ActionResult(
                status=ActionStatus.FAILURE,
                error_message=str(e),
                platform=self.platform_name,
                action_type=action_type,
                context=context
            )
    
    # Helper methods
    
    async def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Find a Slack user by email address.
        
        Args:
            email: Email address to search for
            
        Returns:
            Optional[Dict[str, Any]]: User information if found, None otherwise
        """
        try:
            response = await self.async_client.users_lookupByEmail(email=email)
            return response["user"]
        except SlackApiError:
            return None
    
    async def find_channel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Find a Slack channel by name.
        
        Args:
            name: Channel name to search for
            
        Returns:
            Optional[Dict[str, Any]]: Channel information if found, None otherwise
        """
        try:
            # Remove the # prefix if present
            if name.startswith("#"):
                name = name[1:]
            
            # List all channels
            response = await self.async_client.conversations_list()
            for channel in response["channels"]:
                if channel["name"] == name:
                    return channel
            
            # Check pagination
            while response.get("response_metadata", {}).get("next_cursor"):
                cursor = response["response_metadata"]["next_cursor"]
                response = await self.async_client.conversations_list(cursor=cursor)
                
                for channel in response["channels"]:
                    if channel["name"] == name:
                        return channel
            
            return None
        except SlackApiError:
            return None
    
    async def get_channel_id(self, channel_name: str) -> Optional[str]:
        """
        Get a channel ID from a channel name.
        
        Args:
            channel_name: Channel name (with or without #)
            
        Returns:
            Optional[str]: Channel ID if found, None otherwise
        """
        # If it's already an ID, return it
        if re.match(r"^[A-Z0-9]+$", channel_name):
            return channel_name
        
        # If it's a direct message, return it
        if channel_name.startswith(("D", "G")):
            return channel_name
        
        # Otherwise, look up the channel
        channel = await self.find_channel_by_name(channel_name)
        return channel["id"] if channel else None
