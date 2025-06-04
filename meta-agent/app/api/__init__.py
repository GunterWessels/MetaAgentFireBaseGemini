"""
Meta-Agent API package.

This package contains the REST API endpoints for the Meta-Agent application.
It provides interfaces for creating, listing, and updating goals, as well as
health check functionality.
"""

# Import API endpoints to make them available
from app.api.create_goal import router as create_goal_router
from app.api.list_goals import router as list_goals_router
from app.api.update_goal import router as update_goal_router
from app.api.health_check import router as health_check_router

# List of all routers to be included in the application
routers = [
    create_goal_router,
    list_goals_router,
    update_goal_router,
    health_check_router,
]

__all__ = [
    "create_goal_router",
    "list_goals_router", 
    "update_goal_router",
    "health_check_router",
    "routers"
]
