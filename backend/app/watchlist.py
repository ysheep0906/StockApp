from decimal import Decimal

import pymysql
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.db import db_cursor
from app.timeutil import now_kst

# 라우터 단위 인증: 이 파일의 모든 API는 로그인해야 호출 가능
router = APIRouter(tags=["watchlist"], dependencies=[Depends(get_current_user)])

# 수집기가 종목당 1분에 1회 외부 API를 호출하므로, 호출량 한도를 고려해 상한을 둔다
WATCHLIST_MAX = 10

# 종목코드: 숫자 6자리가 일반적이지만, 최근 신규 상장 종목은 영문이 섞이기도 함
CODE_PATTERN = r"^[0-9A-Z]{6}$"


class AlertSettings(BaseModel):
    # 국내 주식 일일 가격제한폭이 ±30% 이므로 0 초과 30 이하만 허용. None 이면 알림 끔
    alert_up_pct: Decimal | None = Field(default=None, gt=0, le=30, decimal_places=2)
    alert_down_pct: Decimal | None = Field(default=None, gt=0, le=30, decimal_places=2)


class WatchAdd(AlertSettings):
    stock_code: str = Field(pattern=CODE_PATTERN)


@router.get("/api/stocks/search")
def search_stocks(q: str = Query(min_length=1, max_length=20)):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT code, name FROM stocks
            WHERE code LIKE %s OR name LIKE %s
            ORDER BY name
            LIMIT 20
            """,
            (f"{q}%", f"%{q}%"),
        )
        return cur.fetchall()


@router.get("/api/watchlist")
def list_watchlist(user: dict = Depends(get_current_user)):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT w.stock_code, s.name, w.alert_up_pct, w.alert_down_pct
            FROM watchlist w
            JOIN stocks s ON s.code = w.stock_code
            WHERE w.user_id = %s
            ORDER BY w.created_at
            """,
            (user["id"],),
        )
        return cur.fetchall()


@router.post("/api/watchlist", status_code=201)
def add_watchlist(body: WatchAdd, user: dict = Depends(get_current_user)):
    with db_cursor() as cur:
        cur.execute("SELECT name FROM stocks WHERE code = %s", (body.stock_code,))
        stock = cur.fetchone()
        if not stock:
            raise HTTPException(status_code=404, detail="존재하지 않는 종목코드입니다")

        cur.execute("SELECT COUNT(*) AS cnt FROM watchlist WHERE user_id = %s", (user["id"],))
        if cur.fetchone()["cnt"] >= WATCHLIST_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"관심종목은 최대 {WATCHLIST_MAX}개까지 등록할 수 있습니다",
            )

        try:
            cur.execute(
                """
                INSERT INTO watchlist
                    (user_id, stock_code, alert_up_pct, alert_down_pct, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user["id"], body.stock_code, body.alert_up_pct, body.alert_down_pct, now_kst()),
            )
        except pymysql.err.IntegrityError:
            raise HTTPException(status_code=409, detail="이미 등록된 종목입니다") from None

    return {"stock_code": body.stock_code, "name": stock["name"]}


@router.put("/api/watchlist/{stock_code}/alerts")
def update_alerts(
    body: AlertSettings,
    stock_code: str = Path(pattern=CODE_PATTERN),
    user: dict = Depends(get_current_user),
):
    with db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM watchlist WHERE user_id = %s AND stock_code = %s",
            (user["id"], stock_code),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="관심종목에 없는 종목입니다")

        cur.execute(
            """
            UPDATE watchlist SET alert_up_pct = %s, alert_down_pct = %s
            WHERE user_id = %s AND stock_code = %s
            """,
            (body.alert_up_pct, body.alert_down_pct, user["id"], stock_code),
        )
    return {"ok": True}


@router.delete("/api/watchlist/{stock_code}", status_code=204)
def delete_watchlist(
    stock_code: str = Path(pattern=CODE_PATTERN),
    user: dict = Depends(get_current_user),
):
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM watchlist WHERE user_id = %s AND stock_code = %s",
            (user["id"], stock_code),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="관심종목에 없는 종목입니다")