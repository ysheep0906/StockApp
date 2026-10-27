from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user
from app.db import db_cursor
from app.watchlist import CODE_PATTERN

router = APIRouter(tags=["disclosures"], dependencies=[Depends(get_current_user)])


@router.get("/api/disclosures")
def list_disclosures(
    stock_code: str | None = Query(default=None, pattern=CODE_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    # 내 관심종목의 공시만 보여준다
    sql = """
        SELECT d.rcept_no, d.stock_code, s.name, d.report_nm, d.rcept_dt,
               d.summary, d.summary_status
        FROM disclosures d
        JOIN watchlist w ON w.stock_code = d.stock_code AND w.user_id = %s
        JOIN stocks s ON s.code = d.stock_code
    """
    params: list = [user["id"]]
    if stock_code:
        sql += " WHERE d.stock_code = %s"
        params.append(stock_code)
    sql += " ORDER BY d.rcept_dt DESC, d.rcept_no DESC LIMIT %s"
    params.append(limit)

    with db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()