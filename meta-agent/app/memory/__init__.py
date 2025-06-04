"""
Meta-Agent memory package.

This package provides memory storage and retrieval functionality for the Meta-Agent.
It includes interfaces for storing conversation history, user goals, and other
persistent data needed by the agent system.
"""

from app.memory.memory_store import MemoryStore

__all__ = ["MemoryStore"]
