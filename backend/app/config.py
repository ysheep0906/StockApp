import os 
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# 필수 환경 변수: 없으면 KeyError
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]

SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))
# 운영(HTTPS)에서는 true, 로컬 개발(http)에서는 false
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"