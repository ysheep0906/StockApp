from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.auth import get_current_user
from app.db import db_cursor
from app.market import is_trading_time
from app.timeutil import now_kst
from app.watchlist import CODE_PATTERN

router = APIRouter(tags=["prices"], dependencies=[Depends(get_current_user)])

# 장중인데 마지막 수집이 이보다 오래되면 '지연'으로 표시
STALE_MINUTES = 3


@router.get("/api/dashboard")
def dashboard(user: dict = Depends(get_current_user)):
    now = now_kst()
    trading = is_trading_time(now)

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT w.stock_code, s.name, p.price, p.change_rate, p.ts
            FROM watchlist w
            JOIN stocks s ON s.code = w.stock_code
            LEFT JOIN price_minute p
              ON p.stock_code = w.stock_code
             AND p.ts = (SELECT MAX(ts) FROM price_minute WHERE stock_code = w.stock_code)
            WHERE w.user_id = %s
            ORDER BY w.created_at
            """,
            (user["id"],),
        )
        items = cur.fetchall()

    for item in items:
        last = item["ts"]
        item["stale"] = trading and (
            last is None or now - last > timedelta(minutes=STALE_MINUTES)
        )

    return {"now": now, "trading": trading, "items": items}


@router.get("/api/stocks/{stock_code}/chart")
def chart(
    stock_code: str = Path(pattern=CODE_PATTERN),
    day: date | None = Query(default=None, alias="date"),
):
    with db_cursor() as cur:
        cur.execute("SELECT name FROM stocks WHERE code = %s", (stock_code,))
        stock = cur.fetchone()
        if not stock:
            raise HTTPException(status_code=404, detail="존재하지 않는 종목코드입니다")

        if day is None:
            # 날짜를 안 주면 데이터가 있는 가장 최근 날짜
            cur.execute(
                "SELECT MAX(ts) AS last_ts FROM price_minute WHERE stock_code = %s",
                (stock_code,),
            )
            last_ts = cur.fetchone()["last_ts"]
            if last_ts is None:
                return {"code": stock_code, "name": stock["name"], "date": None, "points": []}
            day = last_ts.date()

        start = datetime.combine(day, datetime.min.time())
        # DATE(ts) = ? 대신 범위 조건을 써야 인덱스(PRIMARY KEY)를 제대로 탄다
        cur.execute(
            """
            SELECT ts, price, source FROM price_minute
            WHERE stock_code = %s AND ts >= %s AND ts < %s
            ORDER BY ts
            """,
            (stock_code, start, start + timedelta(days=1)),
        )
        points = cur.fetchall()

    return {"code": stock_code, "name": stock["name"], "date": day, "points": points}