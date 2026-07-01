import os
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

_UNSAFE_DEFAULT = "change-this-in-production-super-secret"
_ENV = os.getenv("ENVIRONMENT", "production").lower()

SECRET_KEY = os.getenv("SECRET_KEY", "")

if _ENV != "development":
    if not SECRET_KEY or SECRET_KEY == _UNSAFE_DEFAULT or len(SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY environment variable is missing, uses the unsafe default, or is shorter than 32 characters. "
            "Set a strong SECRET_KEY before starting the server."
        )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None