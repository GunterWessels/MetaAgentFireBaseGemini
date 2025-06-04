"""
Meta-Agent: Main Application Entry Point

This module initializes the FastAPI application and sets up the LangChain agent.
It provides a simple chat interface as a starting point and is designed to be
modular and extensible for future connectors.
"""

import os
from typing import Dict, List, Optional, Any, Union

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# LangChain imports
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory
from langchain.prompts import PromptTemplate
from langchain_core.language_models import BaseLLM
from langchain_core.callbacks import CallbackManager

# LLM Provider imports - will be loaded dynamically based on config
import importlib

# Local imports
from app.utils.config import load_config, Config
from app.utils.logger import setup_logger
from app.memory.memory_store import MemoryStore

# Initialize logger
logger = setup_logger(__name__)

# Initialize the FastAPI app
app = FastAPI(
    title="Meta-Agent",
    description="A modular agent system with LangChain integration",
    version="0.1.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models for API
class ChatMessage(BaseModel):
    role: str = Field(..., description="The role of the message sender (user or assistant)")
    content: str = Field(..., description="The content of the message")
    
class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="List of messages in the conversation")
    goal_id: Optional[str] = Field(None, description="Optional goal ID for context")
    
class ChatResponse(BaseModel):
    response: str = Field(..., description="The assistant's response")
    conversation_id: str = Field(..., description="Unique identifier for the conversation")

# Global variables
config: Config = None
meta_agent = None

def get_llm_instance(config: Config) -> BaseLLM:
    """
    Dynamically initialize an LLM based on configuration.
    Supports multiple providers through their APIs.
    """
    provider = config.llm_provider.lower()
    
    try:
        if provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=config.llm_model,
                temperature=config.llm_temperature,
                api_key=config.llm_api_key
            )
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=config.llm_model,
                temperature=config.llm_temperature,
                api_key=config.llm_api_key
            )
        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=config.llm_model,
                temperature=config.llm_temperature,
                google_api_key=config.llm_api_key
            )
        elif provider == "huggingface":
            from langchain_community.llms import HuggingFaceHub
            return HuggingFaceHub(
                repo_id=config.llm_model,
                huggingfacehub_api_token=config.llm_api_key
            )
        else:
            logger.error(f"Unsupported LLM provider: {provider}")
            raise ValueError(f"Unsupported LLM provider: {provider}")
    except Exception as e:
        logger.error(f"Failed to initialize LLM: {e}")
        raise

class MetaAgent:
    """
    Core Meta-Agent class that handles the integration with LangChain
    and provides a modular architecture for extensions.
    """
    def __init__(self, config: Config):
        self.config = config
        self.memory_store = MemoryStore(config)
        self.llm = get_llm_instance(config)
        
        # Initialize conversation template
        self.template = """
        You are a helpful AI assistant that can help with various tasks.
        
        Current conversation:
        {history}
        
        Human: {input}
        AI Assistant:
        """
        
        self.prompt = PromptTemplate(
            input_variables=["history", "input"],
            template=self.template
        )
        
        # Initialize conversation chain
        self.conversation = ConversationChain(
            llm=self.llm,
            prompt=self.prompt,
            memory=ConversationBufferMemory(),
            verbose=config.debug_mode
        )
        
        logger.info("MetaAgent initialized successfully")
    
    async def process_message(self, messages: List[ChatMessage], goal_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a message from the user and return a response.
        
        Args:
            messages: List of messages in the conversation
            goal_id: Optional goal ID for context
            
        Returns:
            Dictionary with response and conversation ID
        """
        # Extract the latest user message
        user_message = messages[-1].content if messages else ""
        
        # Reconstruct conversation history for context
        history = ""
        for msg in messages[:-1]:
            role_prefix = "Human: " if msg.role == "user" else "AI Assistant: "
            history += f"{role_prefix}{msg.content}\n\n"
        
        # Process with LangChain
        response = self.conversation.predict(input=user_message, history=history)
        
        # Generate a conversation ID (in a real implementation, this would be stored)
        import uuid
        conversation_id = str(uuid.uuid4())
        
        return {
            "response": response,
            "conversation_id": conversation_id
        }

# Dependency to get the MetaAgent instance
def get_meta_agent():
    if meta_agent is None:
        raise HTTPException(status_code=500, detail="MetaAgent not initialized")
    return meta_agent

@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    meta_agent: MetaAgent = Depends(get_meta_agent)
):
    """
    Simple chat endpoint that processes messages through the LangChain agent.
    """
    try:
        result = await meta_agent.process_message(
            messages=request.messages,
            goal_id=request.goal_id
        )
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "healthy"}

@app.on_event("startup")
async def startup_event():
    """
    Initialize the application on startup.
    """
    global config, meta_agent
    
    try:
        # Load configuration
        config = load_config()
        
        # Initialize the MetaAgent
        meta_agent = MetaAgent(config)
        
        logger.info("Application started successfully")
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """
    Clean up resources on shutdown.
    """
    global meta_agent
    
    if meta_agent and hasattr(meta_agent, "memory_store"):
        await meta_agent.memory_store.close()
    
    logger.info("Application shutdown complete")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
