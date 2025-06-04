"""
Logging configuration for the Meta-Agent application.

This module sets up logging with proper formatting, log levels, and file handling.
It provides a consistent logging interface across the application.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional, Union, Dict, Any

# Default log format
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DETAILED_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

# Log levels mapping
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

class LoggerConfig:
    """Configuration for logger setup."""
    
    def __init__(
        self,
        log_level: str = "INFO",
        log_format: str = DEFAULT_LOG_FORMAT,
        log_file: Optional[str] = None,
        log_dir: str = "logs",
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        console_output: bool = True,
        detailed_format: bool = False,
    ):
        self.log_level = LOG_LEVELS.get(log_level.upper(), logging.INFO)
        self.log_format = DETAILED_LOG_FORMAT if detailed_format else log_format
        self.log_file = log_file
        self.log_dir = log_dir
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.console_output = console_output


def setup_logger(
    name: str,
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    log_dir: str = "logs",
    config: Optional[Dict[str, Any]] = None,
) -> logging.Logger:
    """
    Set up and configure a logger instance.
    
    Args:
        name: Name of the logger (typically __name__)
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file name
        log_dir: Directory to store log files
        config: Optional configuration dictionary that overrides other parameters
        
    Returns:
        Configured logger instance
    """
    # If config is provided, use it to override parameters
    if config:
        logger_config = LoggerConfig(
            log_level=config.get("log_level", "INFO"),
            log_file=config.get("log_file", log_file),
            log_dir=config.get("log_dir", log_dir),
            detailed_format=config.get("debug_mode", False),
        )
    else:
        logger_config = LoggerConfig(
            log_level=log_level or os.environ.get("META_AGENT_LOG_LEVEL", "INFO"),
            log_file=log_file,
            log_dir=log_dir,
            detailed_format=os.environ.get("META_AGENT_DEBUG_MODE", "false").lower() == "true",
        )
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(logger_config.log_level)
    
    # Clear existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(logger_config.log_format)
    
    # Add console handler if enabled
    if logger_config.console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # Add file handler if log file is specified
    if logger_config.log_file or name == "__main__":
        # Create log directory if it doesn't exist
        log_dir_path = Path(logger_config.log_dir)
        log_dir_path.mkdir(exist_ok=True, parents=True)
        
        # Determine log file name
        if not logger_config.log_file:
            log_file_name = f"{name.replace('.', '_')}.log"
            if name == "__main__":
                log_file_name = "meta_agent.log"
        else:
            log_file_name = logger_config.log_file
        
        log_file_path = log_dir_path / log_file_name
        
        # Set up rotating file handler
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=logger_config.max_file_size,
            backupCount=logger_config.backup_count
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get an existing logger or create a new one.
    
    Args:
        name: Name of the logger (typically __name__)
        
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    
    # If logger is not configured, set up with defaults
    if not logger.handlers:
        return setup_logger(name)
    
    return logger


# Set up root logger
root_logger = setup_logger("meta_agent")
