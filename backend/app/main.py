import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.db import get_conn

from app.auth import router as auth_router
from app.watchlist import router as watchlist_router
from app.prices import router as prices_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("stockapp")

KST = ZoneInfo("Asia/Seoul")

app = FastAPI(title="Stock Monitor API")

@app.get("/api/health")
def health():
    now = datetime.now(KST).isoformat()
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1") # DB 연결 확인 쿼리
        finally:
            conn.close()
        return {"status": "ok", "db": "ok", "time": now}
    except Exception as e:
        # 상세 원인은 서버 로그에만 남기고, 응답에는 노출하지 않음
        logger.error("DB health check failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": "unreachable", "time": now},
        )
    
app.include_router(auth_router)
app.include_router(watchlist_router)
app.include_router(prices_router)