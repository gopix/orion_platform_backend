import logging
import os
from src.core.config import settings

LOG_DIR = settings.log_dir
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "orion.log")

LOG_LEVEL = getattr(logging, settings.log_level.upper(), logging.INFO)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

def get_logger(name: str):
    return logging.getLogger(name)