import os
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
import secrets

# ✅ Use bcrypt with proper error handling
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception as e:
    print(f"⚠️ Bcrypt not available, falling back to sha256_crypt: {e}")
    pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

# ✅ Read JWT secret from environment
SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not SECRET_KEY:
    # 🔴 Critical: Generate a temporary one for local dev only
    if os.getenv("ENVIRONMENT") == "production" or os.getenv("RENDER"):
        raise ValueError(
            "❌ JWT_SECRET_KEY is required in production!\n"
            "Please set it in Render.com environment variables:\n"
            "https://dashboard.render.com/"
        )
    else:
        # Local development: generate a random key
        SECRET_KEY = secrets.token_urlsafe(32)
        print(f"⚠️  JWT_SECRET_KEY generated for local development only")
        print(f"   Key: {SECRET_KEY}")
        print(f"   ⚠️  Do not use this in production!")

# ✅ Validate key length
if len(SECRET_KEY) < 32:
    print(f"⚠️  WARNING: JWT_SECRET_KEY is only {len(SECRET_KEY)} characters long.")
    print("   Minimum recommended: 32 characters.")
    print("   Generate a new one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'")

# ✅ Configuration from environment with defaults
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# ✅ Log status (don't expose the key)
print(f"✅ Auth configuration loaded (Algorithm: {ALGORITHM})")

# ... rest of the functions remain the same ...
def hash_password(password: str) -> str:
    """Hash a password using bcrypt/sha256"""
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
    """Decode and verify a JWT token with proper error handling"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Check if it's an access token
        if payload.get("type") != "access":
            return None
        return payload
    except ExpiredSignatureError:
        # Token expired - specific error for better handling
        return {"error": "expired"}
    except JWTError:
        # Invalid token - generic error
        return None

def decode_refresh_token(token: str):
    """Decode and verify a refresh token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Check if it's a refresh token
        if payload.get("type") != "refresh":
            return None
        return payload
    except ExpiredSignatureError:
        return {"error": "expired"}
    except JWTError:
        return None