"""
Slack Connector Package

This package provides integration with the Slack platform for the Meta-Agent.
It includes a connector implementation that follows the PlatformAdapter interface,
event handlers for Slack events, and templates for generating Slack-specific code.

The main components are:
- SlackConnector: Implementation of the PlatformAdapter for Slack
- event_handler: FastAPI routes for handling Slack events and interactions
"""

from app.connectors.slack_connector.slack_client import SlackConnector

# Import event handler when implemented
# from app.connectors.slack_connector.event_handler import router as slack_event_router

__all__ = ["SlackConnector"]
