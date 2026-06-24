import os
from dotenv import load_dotenv
from .logging_config import setup_logging

# Load environment variables from the absolute path of the backend directory
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(base_dir, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    load_dotenv()  # Fallback to standard lookup

class Settings:
    # Redis configuration
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB: int = int(os.getenv("REDIS_DB", 0))

    # API Keys
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
    TENOR_API_KEY: str = os.getenv("TENOR_API_KEY", "")
    GIPHY_API_KEY: str = os.getenv("GIPHY_API_KEY", "")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    UPLOADTHING_API_KEY: str = os.getenv("UPLOADTHING_API_KEY", "")

    # Storage paths (local temp storage)
    TEMP_DIR: str = os.getenv("TEMP_DIR", "/tmp/ugc_platform")

    # MongoDB configuration
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB: str = os.getenv("MONGO_DB", "ugc_video_platform")

    # Logging configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "/tmp/ugc_platform/app.log")

    # Supabase (Optional fallback)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

settings = Settings()

# Ensure temp directory exists
os.makedirs(settings.TEMP_DIR, exist_ok=True)

# Centralized Logging Initialization
setup_logging(log_level_str=settings.LOG_LEVEL, log_file_path=settings.LOG_FILE)
