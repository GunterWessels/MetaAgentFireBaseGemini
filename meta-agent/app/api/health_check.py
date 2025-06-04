"""
Health Check API Module

This module provides a simple health check endpoint to verify that the Meta-Agent
service is running correctly. It can be extended to include checks for dependent
services and components.
"""

import time
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.utils.logger import setup_logger
from app.utils.config import Config, load_config

# Initialize logger
logger = setup_logger(__name__)

# Create router
router = APIRouter(tags=["health"])

# Models
class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str
    version: str
    uptime: float
    components: Dict[str, Dict[str, Any]]

# Global variables
start_time = time.time()
version = "0.1.0"  # Should be loaded from config or package metadata

def get_config() -> Config:
    """Dependency to get configuration."""
    return load_config()

@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request, config: Config = Depends(get_config)) -> Dict[str, Any]:
    """
    Health check endpoint to verify the service is running correctly.
    
    Returns:
        JSON response with health status information
    """
    # Calculate uptime
    uptime = time.time() - start_time
    
    # Check component status
    # In a real implementation, this would check database connections,
    # external services, etc.
    components = {
        "database": {
            "status": "healthy",
            "type": config.db_type
        },
        "llm_provider": {
            "status": "healthy",
            "provider": config.llm_provider
        }
    }
    
    # Log health check request
    logger.debug(f"Health check requested from {request.client.host if request.client else 'unknown'}")
    
    return {
        "status": "healthy",
        "version": version,
        "uptime": uptime,
        "components": components
    }

@router.get("/ping")
async def ping() -> Dict[str, str]:
    """
    Simple ping endpoint for basic connectivity checks.
    
    Returns:
        JSON response with pong message
    """
    return {"ping": "pong"}
