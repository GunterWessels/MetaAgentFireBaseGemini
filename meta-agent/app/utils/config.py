"""
Configuration module for the Meta-Agent application.

This module handles loading configuration from environment variables and default settings.
It supports configurations for different LLM providers, database connections, and deployment settings.
"""

import os
from enum import Enum
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

class Environment(str, Enum):
    """Supported deployment environments."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    HUGGINGFACE = "huggingface"
    COHERE = "cohere"
    CUSTOM = "custom"  # For custom or self-hosted models

class DatabaseType(str, Enum):
    """Supported database types."""
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MONGODB = "mongodb"
    REDIS = "redis"
    CHROMA = "chroma"  # For vector storage

class Config(BaseModel):
    """
    Configuration settings for the Meta-Agent application.
    """
    # Application settings
    app_name: str = Field(default="Meta-Agent")
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug_mode: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    
    # Server settings
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    workers: int = Field(default=1)
    
    # LLM settings
    llm_provider: str = Field(default="openai")
    llm_model: str = Field(default="gpt-4")
    llm_temperature: float = Field(default=0.7)
    llm_api_key: str = Field(default="")
    llm_api_base: Optional[str] = Field(default=None)  # For custom endpoints
    llm_max_tokens: int = Field(default=2000)
    llm_timeout: int = Field(default=30)  # Timeout in seconds
    
    # Memory and database settings
    db_type: DatabaseType = Field(default=DatabaseType.SQLITE)
    db_connection_string: str = Field(default="sqlite:///./meta_agent.db")
    vector_db_type: DatabaseType = Field(default=DatabaseType.CHROMA)
    vector_db_connection_string: Optional[str] = Field(default=None)
    
    # Connector settings
    slack_api_token: Optional[str] = Field(default=None)
    slack_signing_secret: Optional[str] = Field(default=None)
    jira_url: Optional[str] = Field(default=None)
    jira_username: Optional[str] = Field(default=None)
    jira_api_token: Optional[str] = Field(default=None)
    
    # Security settings
    api_key_required: bool = Field(default=False)
    api_keys: List[str] = Field(default=[])
    cors_origins: List[str] = Field(default=["*"])
    
    # Path settings
    templates_dir: str = Field(default="app/templates")
    data_dir: str = Field(default="data")
    
    # Scheduler settings
    scheduler_enabled: bool = Field(default=True)
    scheduler_job_defaults: Dict[str, Any] = Field(default={
        "coalesce": False,
        "max_instances": 3
    })
    
    @validator("llm_api_key", pre=True)
    def validate_api_key(cls, v, values):
        """Validate that API key is provided based on the selected provider."""
        provider = values.get("llm_provider", "").lower()
        if not v and provider in ["openai", "anthropic", "google", "huggingface", "cohere"]:
            env_var_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "google": "GOOGLE_API_KEY",
                "huggingface": "HUGGINGFACE_API_TOKEN",
                "cohere": "COHERE_API_KEY"
            }
            env_var = env_var_map.get(provider)
            if env_var and os.environ.get(env_var):
                return os.environ.get(env_var)
            raise ValueError(f"API key required for {provider} provider")
        return v
    
    @validator("llm_model", pre=True)
    def set_default_model(cls, v, values):
        """Set default model based on provider if not specified."""
        if not v:
            provider = values.get("llm_provider", "").lower()
            default_models = {
                "openai": "gpt-4",
                "anthropic": "claude-2",
                "google": "gemini-pro",
                "huggingface": "mistralai/Mistral-7B-Instruct-v0.1",
                "cohere": "command"
            }
            return default_models.get(provider, v)
        return v
    
    class Config:
        """Pydantic config."""
        env_prefix = "META_AGENT_"
        env_nested_delimiter = "__"
        use_enum_values = True

def load_config() -> Config:
    """
    Load configuration from environment variables and default settings.
    
    Returns:
        Config: Configuration object
    """
    # Load environment-specific settings
    env = os.getenv("META_AGENT_ENVIRONMENT", "development").lower()
    
    # Create base config from environment variables
    config = Config()
    
    # Override with environment-specific settings
    if env == "production":
        config.debug_mode = False
        config.log_level = "WARNING"
        config.api_key_required = True
        config.cors_origins = [os.getenv("META_AGENT_ALLOWED_ORIGIN", "*")]
    elif env == "staging":
        config.debug_mode = True
        config.log_level = "INFO"
    else:  # development
        config.debug_mode = True
        config.log_level = "DEBUG"
    
    # Ensure data directory exists
    Path(config.data_dir).mkdir(exist_ok=True, parents=True)
    
    return config
