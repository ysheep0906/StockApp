from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

KST = ZoneInfo("Asia/Seoul")

app = FastAPI(title="Stock Monitor API")

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(KST).isoformat()}
