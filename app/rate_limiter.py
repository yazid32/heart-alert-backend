from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, HTTPException
import os

# ✅ Create rate limiter with Redis support (optional)
REDIS_URL = os.getenv("REDIS_URL", None)

if REDIS_URL:
    # Use Redis for distributed rate limiting
    from slowapi.storage import RedisStorage
    storage = RedisStorage(REDIS_URL)
    limiter = Limiter(key_func=get_remote_address, storage=storage)
else:
    # Use memory storage (single instance only)
    limiter = Limiter(key_func=get_remote_address)

# ✅ Custom response for rate limit exceeded
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return HTTPException(
        status_code=429,
        detail="Too many requests. Please slow down and try again later.",
        headers={"Retry-After": str(exc.retry_after)}
    )

# ✅ Attach to app in main.py