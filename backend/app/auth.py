import logging
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import config
from app.db import db_cursor
from app.security import new_session_token, token_hash, verify_password
from app.timeutil import now_kst

logger = logging.getLogger("stockapp.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "sid"
LOGIN_FAILED_MSG = "아이디 또는 비밀번호가 올바르지 않습니다"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


# 현재 로그인한 사용자 정보 조회
def get_current_user(sid: str | None = Cookie(default=None)) -> dict:
    """쿠키의 세션 토큰으로 로그인 사용자를 찾는다. 다른 API에서 Depends로 재사용."""
    if not sid:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.username
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > %s
            """,
            (token_hash(sid), now_kst()),
        )
        user = cur.fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return user


# 로그인
@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    client_ip = request.client.host if request.client else "-"

    with db_cursor() as cur:
        cur.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (body.username,),
        )
        user = cur.fetchone()

        if not verify_password(user["password_hash"] if user else None, body.password):
            # %r: 사용자 입력의 줄바꿈 등을 이스케이프해서 로그 위조를 막음
            logger.warning("LOGIN_FAILED username=%r ip=%s", body.username, client_ip)
            raise HTTPException(status_code=401, detail=LOGIN_FAILED_MSG)

        token = new_session_token()
        now = now_kst()
        cur.execute(
            """
            INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (token_hash(token), user["id"], now, now + timedelta(hours=config.SESSION_HOURS)),
        )
        cur.execute("UPDATE users SET last_login_at = %s WHERE id = %s", (now, user["id"]))

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,          # 자바스크립트에서 읽을 수 없음 (XSS로 토큰 탈취 방지)
        samesite="lax",         # 다른 사이트에서 보내는 POST 요청에는 쿠키가 실리지 않음
        secure=config.COOKIE_SECURE,
        max_age=config.SESSION_HOURS * 3600,
        path="/",
    )
    logger.info("LOGIN_SUCCESS username=%r ip=%s", user["username"], client_ip)
    return {"username": user["username"]}


# 로그아웃
@router.post("/logout")
def logout(response: Response, sid: str | None = Cookie(default=None)):
    if sid:
        with db_cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(sid),))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


# 현재 로그인한 사용자 정보 조회
@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"]}