"""
Memory Store Module

This module provides a flexible memory storage interface for the Meta-Agent.
It supports SQLite as the default storage but is designed to be extensible
for vector databases and other storage options.
"""

import os
import json
import uuid
import sqlite3
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple

import aiosqlite
from sqlalchemy import create_engine, Column, String, Text, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.pool import StaticPool

# Optional imports for vector storage
try:
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

try:
    import pymongo
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from app.utils.logger import setup_logger
from app.utils.config import Config

# Initialize logger
logger = setup_logger(__name__)

# SQLAlchemy Base
Base = declarative_base()

# Database Models
class Conversation(Base):
    """Model for storing conversation data."""
    __tablename__ = "conversations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(255), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    metadata = Column(Text, nullable=True)  # JSON serialized metadata
    
    # Relationships
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": json.loads(self.metadata) if self.metadata else {},
        }


class Message(Base):
    """Model for storing message data."""
    __tablename__ = "messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(50), nullable=False)  # user, assistant, system, etc.
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    metadata = Column(Text, nullable=True)  # JSON serialized metadata
    
    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": json.loads(self.metadata) if self.metadata else {},
        }


class Goal(Base):
    """Model for storing user goals."""
    __tablename__ = "goals"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(255), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="active")  # active, completed, failed, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    metadata = Column(Text, nullable=True)  # JSON serialized metadata
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": json.loads(self.metadata) if self.metadata else {},
        }


class MemoryStoreBase(ABC):
    """
    Abstract base class for memory storage.
    
    This defines the interface that all memory store implementations must follow.
    """
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the memory store."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close the memory store and clean up resources."""
        pass
    
    @abstractmethod
    async def create_conversation(
        self, user_id: Optional[str] = None, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new conversation and return its ID."""
        pass
    
    @abstractmethod
    async def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a conversation by ID."""
        pass
    
    @abstractmethod
    async def list_conversations(
        self, user_id: Optional[str] = None, limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List conversations, optionally filtered by user ID."""
        pass
    
    @abstractmethod
    async def add_message(
        self, conversation_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a message to a conversation and return its ID."""
        pass
    
    @abstractmethod
    async def get_messages(
        self, conversation_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get messages for a conversation."""
        pass
    
    @abstractmethod
    async def create_goal(
        self, title: str, description: Optional[str] = None, user_id: Optional[str] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new goal and return its ID."""
        pass
    
    @abstractmethod
    async def get_goal(self, goal_id: str) -> Optional[Dict[str, Any]]:
        """Get a goal by ID."""
        pass
    
    @abstractmethod
    async def list_goals(
        self, user_id: Optional[str] = None, status: Optional[str] = None, 
        limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List goals, optionally filtered by user ID and status."""
        pass
    
    @abstractmethod
    async def update_goal(
        self, goal_id: str, status: Optional[str] = None, title: Optional[str] = None,
        description: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update a goal and return success status."""
        pass
    
    @abstractmethod
    async def store_embedding(
        self, text: str, embedding: List[float], metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Store a text embedding and return its ID."""
        pass
    
    @abstractmethod
    async def search_embeddings(
        self, query_embedding: List[float], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar embeddings."""
        pass


class SQLiteMemoryStore(MemoryStoreBase):
    """
    SQLite implementation of the memory store.
    
    This provides a simple, file-based storage option that works out of the box.
    """
    
    def __init__(self, config: Config):
        """Initialize the SQLite memory store."""
        self.config = config
        self.db_path = config.db_connection_string
        
        # Extract file path from SQLite connection string if needed
        if self.db_path.startswith("sqlite:///"):
            self.db_path = self.db_path[10:]
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        
        # Create sync engine for initialization
        self.sync_engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        
        # Create async engine for operations
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def initialize(self) -> None:
        """Initialize the database schema."""
        # Create tables using the sync engine (SQLAlchemy async doesn't support create_all yet)
        Base.metadata.create_all(self.sync_engine)
        logger.info(f"SQLite memory store initialized at {self.db_path}")
    
    async def close(self) -> None:
        """Close the database connection."""
        await self.engine.dispose()
        logger.info("SQLite memory store closed")
    
    async def create_conversation(
        self, user_id: Optional[str] = None, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new conversation and return its ID."""
        async with self.async_session() as session:
            conversation = Conversation(
                user_id=user_id,
                title=title,
                metadata=json.dumps(metadata) if metadata else None
            )
            session.add(conversation)
            await session.commit()
            return conversation.id
    
    async def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a conversation by ID."""
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
            conversation = result.scalars().first()
            if conversation:
                return conversation.to_dict()
            return None
    
    async def list_conversations(
        self, user_id: Optional[str] = None, limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List conversations, optionally filtered by user ID."""
        async with self.async_session() as session:
            from sqlalchemy import select
            query = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
            
            if user_id:
                query = query.where(Conversation.user_id == user_id)
            
            result = await session.execute(query)
            conversations = result.scalars().all()
            return [conversation.to_dict() for conversation in conversations]
    
    async def add_message(
        self, conversation_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a message to a conversation and return its ID."""
        async with self.async_session() as session:
            # First check if the conversation exists
            from sqlalchemy import select
            result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
            conversation = result.scalars().first()
            
            if not conversation:
                raise ValueError(f"Conversation with ID {conversation_id} not found")
            
            # Add the message
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                metadata=json.dumps(metadata) if metadata else None
            )
            session.add(message)
            
            # Update the conversation's updated_at timestamp
            conversation.updated_at = datetime.utcnow()
            
            await session.commit()
            return message.id
    
    async def get_messages(
        self, conversation_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get messages for a conversation."""
        async with self.async_session() as session:
            from sqlalchemy import select
            query = select(Message).where(Message.conversation_id == conversation_id) \
                .order_by(Message.created_at).limit(limit).offset(offset)
            
            result = await session.execute(query)
            messages = result.scalars().all()
            return [message.to_dict() for message in messages]
    
    async def create_goal(
        self, title: str, description: Optional[str] = None, user_id: Optional[str] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new goal and return its ID."""
        async with self.async_session() as session:
            goal = Goal(
                user_id=user_id,
                title=title,
                description=description,
                metadata=json.dumps(metadata) if metadata else None
            )
            session.add(goal)
            await session.commit()
            return goal.id
    
    async def get_goal(self, goal_id: str) -> Optional[Dict[str, Any]]:
        """Get a goal by ID."""
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(select(Goal).where(Goal.id == goal_id))
            goal = result.scalars().first()
            if goal:
                return goal.to_dict()
            return None
    
    async def list_goals(
        self, user_id: Optional[str] = None, status: Optional[str] = None, 
        limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List goals, optionally filtered by user ID and status."""
        async with self.async_session() as session:
            from sqlalchemy import select
            query = select(Goal).order_by(Goal.updated_at.desc()).limit(limit).offset(offset)
            
            if user_id:
                query = query.where(Goal.user_id == user_id)
            
            if status:
                query = query.where(Goal.status == status)
            
            result = await session.execute(query)
            goals = result.scalars().all()
            return [goal.to_dict() for goal in goals]
    
    async def update_goal(
        self, goal_id: str, status: Optional[str] = None, title: Optional[str] = None,
        description: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update a goal and return success status."""
        async with self.async_session() as session:
            from sqlalchemy import select
            result = await session.execute(select(Goal).where(Goal.id == goal_id))
            goal = result.scalars().first()
            
            if not goal:
                return False
            
            if status:
                goal.status = status
                if status == "completed":
                    goal.completed_at = datetime.utcnow()
            
            if title:
                goal.title = title
            
            if description:
                goal.description = description
            
            if metadata:
                # Merge with existing metadata if present
                existing = json.loads(goal.metadata) if goal.metadata else {}
                existing.update(metadata)
                goal.metadata = json.dumps(existing)
            
            goal.updated_at = datetime.utcnow()
            await session.commit()
            return True
    
    async def store_embedding(
        self, text: str, embedding: List[float], metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Store a text embedding.
        
        Note: This is a stub implementation that doesn't actually store embeddings.
        For real embedding storage, use a vector database like ChromaDB.
        """
        logger.warning("SQLite does not support vector embeddings. Use a vector database instead.")
        return str(uuid.uuid4())
    
    async def search_embeddings(
        self, query_embedding: List[float], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar embeddings.
        
        Note: This is a stub implementation that doesn't actually search embeddings.
        For real embedding search, use a vector database like ChromaDB.
        """
        logger.warning("SQLite does not support vector embeddings. Use a vector database instead.")
        return []


class ChromaMemoryStore(MemoryStoreBase):
    """
    ChromaDB implementation of the memory store for vector storage.
    
    This provides efficient storage and retrieval of embeddings for semantic search.
    """
    
    def __init__(self, config: Config):
        """Initialize the ChromaDB memory store."""
        if not CHROMA_AVAILABLE:
            raise ImportError("ChromaDB is not installed. Install it with 'pip install chromadb'.")
        
        self.config = config
        self.sqlite_store = SQLiteMemoryStore(config)  # For non-vector data
        
        # Extract path from connection string or use default
        if config.vector_db_connection_string:
            self.chroma_path = config.vector_db_connection_string
        else:
            self.chroma_path = os.path.join(os.path.dirname(self.sqlite_store.db_path), "chroma_db")
        
        # Ensure directory exists
        os.makedirs(self.chroma_path, exist_ok=True)
    
    async def initialize(self) -> None:
        """Initialize the memory store."""
        # Initialize SQLite for non-vector data
        await self.sqlite_store.initialize()
        
        # Initialize ChromaDB
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        
        # Create collections if they don't exist
        self.memory_collection = self.chroma_client.get_or_create_collection("memory")
        self.knowledge_collection = self.chroma_client.get_or_create_collection("knowledge")
        
        logger.info(f"ChromaDB memory store initialized at {self.chroma_path}")
    
    async def close(self) -> None:
        """Close the memory store and clean up resources."""
        await self.sqlite_store.close()
        # ChromaDB doesn't require explicit closing
        logger.info("ChromaDB memory store closed")
    
    # Delegate non-vector methods to SQLite store
    async def create_conversation(self, *args, **kwargs) -> str:
        return await self.sqlite_store.create_conversation(*args, **kwargs)
    
    async def get_conversation(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        return await self.sqlite_store.get_conversation(*args, **kwargs)
    
    async def list_conversations(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return await self.sqlite_store.list_conversations(*args, **kwargs)
    
    async def add_message(self, *args, **kwargs) -> str:
        return await self.sqlite_store.add_message(*args, **kwargs)
    
    async def get_messages(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return await self.sqlite_store.get_messages(*args, **kwargs)
    
    async def create_goal(self, *args, **kwargs) -> str:
        return await self.sqlite_store.create_goal(*args, **kwargs)
    
    async def get_goal(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        return await self.sqlite_store.get_goal(*args, **kwargs)
    
    async def list_goals(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return await self.sqlite_store.list_goals(*args, **kwargs)
    
    async def update_goal(self, *args, **kwargs) -> bool:
        return await self.sqlite_store.update_goal(*args, **kwargs)
    
    # Vector-specific methods
    async def store_embedding(
        self, text: str, embedding: List[float], metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Store a text embedding and return its ID."""
        # Generate a unique ID
        doc_id = str(uuid.uuid4())
        
        # Store the embedding in ChromaDB
        self.memory_collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata or {}]
        )
        
        return doc_id
    
    async def search_embeddings(
        self, query_embedding: List[float], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar embeddings."""
        # Run the query
        results = self.memory_collection.query(
            query_embeddings=[query_embedding],
            n_results=limit
        )
        
        # Format the results
        formatted_results = []
        for i, (doc_id, document, distance) in enumerate(zip(
            results["ids"][0], results["documents"][0], results["distances"][0]
        )):
            metadata = results["metadatas"][0][i] if "metadatas" in results else {}
            formatted_results.append({
                "id": doc_id,
                "text": document,
                "similarity": 1.0 - distance,  # Convert distance to similarity
                "metadata": metadata
            })
        
        return formatted_results


class MemoryStore:
    """
    Factory class for creating memory store instances.
    
    This provides a unified interface for different memory store implementations.
    """
    
    def __init__(self, config: Config):
        """Initialize the memory store factory."""
        self.config = config
        self.store = None
    
    async def __aenter__(self):
        """Context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()
    
    async def initialize(self) -> None:
        """Initialize the appropriate memory store based on configuration."""
        db_type = self.config.db_type.lower()
        vector_db_type = self.config.vector_db_type.lower() if hasattr(self.config, "vector_db_type") else None
        
        # Choose the appropriate store implementation
        if vector_db_type == "chroma" and CHROMA_AVAILABLE:
            self.store = ChromaMemoryStore(self.config)
        elif db_type == "sqlite":
            self.store = SQLiteMemoryStore(self.config)
        else:
            # Default to SQLite if no valid option is specified
            logger.warning(f"Unsupported database type: {db_type}. Using SQLite instead.")
            self.store = SQLiteMemoryStore(self.config)
        
        await self.store.initialize()
    
    async def close(self) -> None:
        """Close the memory store."""
        if self.store:
            await self.store.close()
    
    # Delegate all methods to the underlying store
    async def create_conversation(self, *args, **kwargs) -> str:
        return await self.store.create_conversation(*args, **kwargs)
    
    async def get_conversation(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        return await self.store.get_conversation(*args, **kwargs)
    
    async def list_conversations(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return await self.store.list_conversations(*args, **kwargs)
    
    async def add_message(self, *args, **kwargs) -> str:
        return await self.store.add_message(*args, **kwargs)
    
    async def get_messages(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return await self.store.get_messages(*args, **kwargs)
    
    async def create_goal(self, *args, **kwargs) -> str:
        return await self.store.create_goal(*args, **kwargs)
    
    async def get_goal(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        return await self.store.get_goal(*args, **kwargs)
    
    async def list_goals(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return await self.store.list_goals(*args, **kwargs)
    
    async def update_goal(self, *args, **kwargs) -> bool:
        return await self.store.update_goal(*args, **kwargs)
    
    async def store_embedding(self, *args, **kwargs) -> str:
        return await self.store.store_embedding(*args, **kwargs)
    
    async def search_embeddings(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return await self.store.search_embeddings(*args, **kwargs)
