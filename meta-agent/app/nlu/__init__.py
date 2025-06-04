"""
Meta-Agent NLU (Natural Language Understanding) package.

This package provides natural language understanding capabilities for the Meta-Agent,
including intent parsing, slot extraction, and follow-up question generation.
It leverages LangChain to create processing chains that interpret user goals
and extract structured information.
"""

# Import components to make them available at the package level
# These will be implemented in separate modules
from app.nlu.parse_goal_chain import ParseGoalChain
from app.nlu.follow_up_chain import FollowUpChain

__all__ = ["ParseGoalChain", "FollowUpChain"]
