"""
Meta-Agent Connectors Package

This package provides platform-specific connectors for the Meta-Agent to interact
with external services and platforms. It includes a common platform adapter interface
and specific implementations for supported platforms like Slack and JIRA.

The connectors are responsible for:
1. Authenticating with external platforms
2. Sending and receiving data
3. Handling platform-specific events and webhooks
4. Translating between platform-specific formats and Meta-Agent's internal formats
"""

from typing import Dict, Any, List, Optional, Type

from app.connectors.platform_adapter import (
    PlatformAdapter,
    ActionResult,
    ActionStatus,
    ActionContext,
    perform_action
)

# Import connector implementations
# These will be implemented in their respective modules
try:
    from app.connectors.slack_connector.slack_client import SlackConnector
except ImportError:
    SlackConnector = None

try:
    from app.connectors.jira_connector.jira_client import JiraConnector
except ImportError:
    JiraConnector = None

# Registry of available connectors
AVAILABLE_CONNECTORS: Dict[str, Type[PlatformAdapter]] = {}

# Register connectors if available
if SlackConnector:
    AVAILABLE_CONNECTORS["slack"] = SlackConnector

if JiraConnector:
    AVAILABLE_CONNECTORS["jira"] = JiraConnector

__all__ = [
    "PlatformAdapter",
    "ActionResult",
    "ActionStatus",
    "ActionContext",
    "perform_action",
    "AVAILABLE_CONNECTORS",
    "SlackConnector",
    "JiraConnector"
]
