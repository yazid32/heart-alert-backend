from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.auth_config import decode_access_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.Doctor:
    """Get current user from JWT token with improved error handling"""
    
    # ✅ Validate token format
    if not token or not token.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ✅ Decode token with proper error handling
    payload = decode_access_token(token.credentials)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ✅ Handle expired token
    if isinstance(payload, dict) and payload.get("error") == "expired":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ✅ Extract user ID
    doctor_id = payload.get("sub")
    if not doctor_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ✅ Validate user exists
    try:
        doctor = db.query(models.Doctor).filter(models.Doctor.id == int(doctor_id)).first()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ✅ Check if account is suspended
    if doctor.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been suspended",
        )
    
    return doctor

def require_role(allowed_roles: list):
    """Decorator to check if user has required role"""
    def decorator(current_user: models.Doctor = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Permission denied. Required role: {allowed_roles}"
            )
        return current_user
    return decorator

def require_status(allowed_statuses: list):
    """Decorator to check if user has required status"""
    def decorator(current_user: models.Doctor = Depends(get_current_user)):
        if current_user.status not in allowed_statuses:
            raise HTTPException(
                status_code=403, 
                detail=f"Account not approved. Status: {current_user.status}"
            )
        return current_user
    return decorator