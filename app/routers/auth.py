from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.auth_config import verify_password, create_access_token, create_refresh_token, decode_refresh_token, decode_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Get current user from token"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    user = db.query(models.Doctor).filter(models.Doctor.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    return user


@router.post("/login")
async def login(
    email: str,
    password: str,
    remember_me: bool = False,
    db: Session = Depends(get_db)
):
    # Find user
    user = db.query(models.Doctor).filter(models.Doctor.email == email).first()
    
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create tokens with user data
    access_token = create_access_token(data={
        "sub": user.email,
        "doctor_id": user.id,
        "role": user.role,
        "subscription_plan": user.subscription_plan
    })
    
    refresh_token = None
    if remember_me:
        refresh_token = create_refresh_token(data={
            "sub": user.email,
            "doctor_id": user.id
        })
    
    # Return complete user data including subscription plan
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 86400,
        "remember_me": remember_me,
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "status": user.status,
        "profile_picture": user.profile_picture,
        "specialty": user.specialty,
        "hospital": user.hospital,
        "subscription_plan": user.subscription_plan,
        "plan": user.subscription_plan,
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
    
    new_access_token = create_access_token(data={
        "sub": user.email,
        "doctor_id": user.id,
        "role": user.role,
        "subscription_plan": user.subscription_plan
    })
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "status": user.status,
        "subscription_plan": user.subscription_plan,
        "plan": user.subscription_plan,
    }


# ADD THIS ENDPOINT AT THE BOTTOM
@router.get("/me")
async def get_current_user_info(
    current_user: models.Doctor = Depends(get_current_user)
):
    """Get current user information"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "status": current_user.status,
        "profile_picture": current_user.profile_picture,
        "specialty": current_user.specialty,
        "hospital": current_user.hospital,
        "phone": current_user.phone,
        "country": current_user.country,
        "subscription_plan": current_user.subscription_plan,
        "plan": current_user.subscription_plan,
        "is_verified": current_user.is_verified,
        "email_verified": current_user.email_verified,
        "created_at": current_user.created_at,
    }