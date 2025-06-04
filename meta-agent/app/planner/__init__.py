"""
Meta-Agent planner package.

This package is responsible for mapping parsed intents and slots to sub-agent
specifications. It generates execution plans based on the user's goals and
available connectors.

The planner determines which actions to take and which sub-agents to deploy
to fulfill the user's request.
"""

# Import components to make them available at the package level
# These will be implemented in the plan_generator.py module
from app.planner.plan_generator import PlanGenerator

__all__ = ["PlanGenerator"]
