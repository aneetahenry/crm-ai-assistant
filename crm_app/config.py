import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def get_settings():
    try:
        mysql_port = int(os.getenv("MYSQL_PORT", "3306"))
    except ValueError:
        mysql_port = 3306
    mysql_keys_present = all(
        os.getenv(key, "").strip()
        for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE")
    )
    return {
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
        "MYSQL_HOST": os.getenv("MYSQL_HOST", "localhost"),
        "MYSQL_PORT": mysql_port,
        "MYSQL_USER": os.getenv("MYSQL_USER", "root"),
        "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD", ""),
        "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE", "crm_ai"),
        "MYSQL_CONFIGURED": mysql_keys_present,
    }
