from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
import os

class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """Force HTTPS in production"""
    
    async def dispatch(self, request: Request, call_next):
        if os.getenv("ENVIRONMENT") == "production":
            if request.headers.get("x-forwarded-proto") == "http":
                url = request.url.replace(scheme="https")
                return RedirectResponse(url, status_code=301)
        
        response = await call_next(request)
        return response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # ✅ Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        
        return response