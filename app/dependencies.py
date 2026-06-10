from fastapi import Depends, HTTPException
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
    """Get current user from JWT token"""
    payload = decode_access_token(token.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    doctor_id = payload.get("sub")
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    doctor = db.query(models.Doctor).filter(models.Doctor.id == int(doctor_id)).first()
    if not doctor:
        raise HTTPException(status_code=401, detail="User not found")
    
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