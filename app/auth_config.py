import os
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
import secrets

# ✅ Use a context that supports multiple hash schemes
# This allows both bcrypt (new) and sha256_crypt (old) to work
pwd_context = CryptContext(
    schemes=["bcrypt", "sha256_crypt"],  # ✅ Both formats supported
    deprecated="auto",
    bcrypt__default_rounds=12,  # ✅ Good balance of security and performance
)

# ✅ Read JWT secret from environment
SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not SECRET_KEY:
    if os.getenv("ENVIRONMENT") == "production" or os.getenv("RENDER"):
        raise ValueError(
            "❌ JWT_SECRET_KEY is required in production!\n"
            "Please set it in Render.com environment variables:\n"
            "https://dashboard.render.com/"
        )
    else:
        SECRET_KEY = secrets.token_urlsafe(32)
        print(f"⚠️  JWT_SECRET_KEY generated for local development only")
        print(f"   Key: {SECRET_KEY}")
        print(f"   ⚠️  Do not use this in production!")

if len(SECRET_KEY) < 32:
    print(f"⚠️  WARNING: JWT_SECRET_KEY is only {len(SECRET_KEY)} characters long.")
    print("   Minimum recommended: 32 characters.")

ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

print(f"✅ Auth configuration loaded (Algorithm: {ALGORITHM})")
print(f"✅ Supported hash schemes: {pwd_context.schemes()}")

def hash_password(password: str) -> str:
    """Hash a password using bcrypt (preferred)"""
    return pwd_context.hash(password, scheme="bcrypt")  # ✅ Explicitly use bcrypt for new hashes

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash (supports both bcrypt and sha256_crypt)"""
    try:
        # ✅ This will try all schemes in order
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"⚠️ Password verification error: {e}")
        # If verification fails, try to re-hash with bcrypt (for old sha256 users)
        # This is a fallback - if it works, we'll re-hash on next login
        return False

def verify_and_upgrade_password(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    """
    Verify password and return new hash if upgrade needed.
    Returns: (is_valid, new_hash_or_none)
    """
    try:
        # Check if hash needs upgrading (old sha256_crypt)
        needs_upgrade = pwd_context.needs_update(hashed_password)
        
        # Verify the password
        is_valid = pwd_context.verify(plain_password, hashed_password)
        
        if is_valid and needs_upgrade:
            # Re-hash with bcrypt
            new_hash = hash_password(plain_password)
            return (True, new_hash)
        
        return (is_valid, None)
    except Exception as e:
        print(f"⚠️ Password verification error: {e}")
        return (False, None)

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
        if payload.get("type") != "access":
            return None
        return payload
    except ExpiredSignatureError:
        return {"error": "expired"}
    except JWTError:
        return None

def decode_refresh_token(token: str):
    """Decode and verify a refresh token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return payload
    except ExpiredSignatureError:
        return {"error": "expired"}
    except JWTError:
        return None