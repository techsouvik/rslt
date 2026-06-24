import os
import sys
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(log_level_str: str = "INFO", log_file_path: str = None) -> None:
    """
    Configures standard Python logging globally.
    Ensures logs are written to both standard output and a rotating file.
    Suppresses verbose logging from external libraries unless set to DEBUG.
    """
    # Parse log level
    numeric_level = getattr(logging, log_level_str.upper(), logging.INFO)
    
    # Formatter with timestamp, level, logger name, filename, function name, line number, and message
    log_format = "%(asctime)s - %(levelname)s - [%(name)s:%(filename)s:%(funcName)s:%(lineno)d] - %(message)s"
    formatter = logging.Formatter(log_format)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers to prevent duplicate logging
    if root_logger.handlers:
        root_logger.handlers.clear()
        
    # 1. Console (Stdout) Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    root_logger.addHandler(console_handler)
    
    # 2. File Handler (if log_file_path is provided)
    if log_file_path:
        try:
            # Ensure parent directory of log file exists
            os.makedirs(os.path.dirname(os.path.abspath(log_file_path)), exist_ok=True)
            
            # Rotating file handler (Max 10MB per file, keep 5 backups)
            file_handler = RotatingFileHandler(
                log_file_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(numeric_level)
            root_logger.addHandler(file_handler)
            
            # Log successful setup of file logger
            logging.getLogger(__name__).info(f"Logging file handler initialized at: {log_file_path}")
        except Exception as e:
            # If log file initialization fails, log to stdout
            logging.getLogger(__name__).error(f"Failed to initialize rotating file handler: {e}")
            
    # Suppress chatty third-party loggers unless they are warnings or errors
    suppressed_loggers = [
        "httpx",
        "httpcore",
        "urllib3",
        "redis",
        "asyncio",
        "uvicorn.access",
        "pydantic"
    ]
    for logger_name in suppressed_loggers:
        third_party_logger = logging.getLogger(logger_name)
        # If global level is DEBUG, let them be INFO, otherwise WARNING
        third_party_logger.setLevel(logging.INFO if numeric_level == logging.DEBUG else logging.WARNING)
        
    logging.getLogger(__name__).info(f"Global logger initialized at level: {logging.getLevelName(numeric_level)}")
