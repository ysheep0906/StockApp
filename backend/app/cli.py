import argparse
import getpass
import sys

import pymysql

from app.db import db_cursor
from app.security import hash_password
from app.timeutil import now_kst

MIN_PASSWORD_LENGTH = 12


# 사용자 생성
def create_user(username: str) -> int:
    password = getpass.getpass("비밀번호: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.", file=sys.stderr)
        return 1
    if password != getpass.getpass("비밀번호 확인: "):
        print("비밀번호가 일치하지 않습니다.", file=sys.stderr)
        return 1

    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (%s, %s, %s)",
                (username, hash_password(password), now_kst()),
            )
    except pymysql.err.IntegrityError:
        print(f"이미 존재하는 사용자입니다: {username}", file=sys.stderr)
        return 1

    print(f"사용자 생성 완료: {username}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p_create = sub.add_parser("create-user", help="관리자 계정 생성")
    p_create.add_argument("username")

    args = parser.parse_args()
    if args.command == "create-user":
        return create_user(args.username)
    return 1


if __name__ == "__main__":
    sys.exit(main())