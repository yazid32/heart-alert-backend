from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt

# Use sha256_crypt instead of bcrypt (avoids the bcrypt version bug)
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

# JWT Configuration
SECRET_KEY = "your-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS = 7

print("✅ Auth configuration loaded (using sha256_crypt)")

def hash_password(password: str) -> str:
    """Hash a password using sha256"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create a JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict):
    """Create a refresh token that lasts 7 days"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Check if it's an access token
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.JWTError:
        return None

def decode_refresh_token(token: str):
    """Decode and verify a refresh token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Check if it's a refresh token
        if payload.get("type") != "refresh":
            return None
        return payload
    except jwt.JWTError:
        return None