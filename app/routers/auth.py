from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.auth_config import verify_password, create_access_token, create_refresh_token, decode_refresh_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login")
async def login(
    email: str,
    password: str,
    remember_me: bool = False,
    db: Session = Depends(get_db)
):
    # Find user - THIS WAS MISSING!
    user = db.query(models.Doctor).filter(models.Doctor.email == email).first()
    
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.email})
    
    refresh_token = None
    if remember_me:
        refresh_token = create_refresh_token(data={"sub": user.email})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 86400,
        "remember_me": remember_me
    }

@router.post("/refresh")
async def refresh_token(
    refresh_token: str,
    db: Session = Depends(get_db)
):
    payload = decode_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    user = db.query(models.Doctor).filter(models.Doctor.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    new_access_token = create_access_token(data={"sub": user.email})
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }