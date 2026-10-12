import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()

# 존재하지 않는 사용자로 로그인할 때도 비슷한 시간이 걸리게 하기 위한 더미 해시
_DUMMY_HASH = _ph.hash("dummy-password-for-timing")


# 비밀번호 해시
def hash_password(password: str) -> str:
    return _ph.hash(password)


# 비밀번호 검증
def verify_password(password_hash: str | None, password: str) -> bool:
    if password_hash is None:
        # 사용자가 없어도 검증 연산은 수행하고, 결과는 항상 실패
        try:
            _ph.verify(_DUMMY_HASH, password)
        except VerificationError:
            pass
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False
    

# 세션 토큰 생성
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


# 토큰 해시
def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()