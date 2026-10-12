import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# backend/.env 를 읽음
load_dotenv(Path(__file__).resolve().parent.parent / ".env") # 실행 위치에 따라 못 찾는 문제 방지

def get_conn():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5, # 서버 무응답 시 5초 후 timeout
    )