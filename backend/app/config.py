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

# 시세 수집
PRICE_PROVIDER = os.environ.get("PRICE_PROVIDER", "mock")   # mock | kis
MOCK_FAIL_RATE = float(os.environ.get("MOCK_FAIL_RATE", "0"))  # 0~1, mock 실패 확률
REQUEST_INTERVAL_SEC = float(os.environ.get("REQUEST_INTERVAL_SEC", "0.6"))

# KIS Open API (PRICE_PROVIDER=kis 일 때만 필요)
KIS_APP_KEY = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
# 기본값은 모의투자 도메인. 실전 키는 주문 권한이 있어 이 프로젝트에서는 쓰지 않는다
KIS_BASE_URL = os.environ.get("KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443")
KIS_TOKEN_FILE = os.environ.get("KIS_TOKEN_FILE", str(BASE_DIR / "var" / "kis_token.json"))

# DART Open API (40자리 인증키)
DART_API_KEY = os.environ.get("DART_API_KEY", "")