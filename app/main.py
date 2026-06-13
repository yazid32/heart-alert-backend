# Load environment variables FIRST before any other imports
import os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, HTTPException, status, Query, UploadFile, File, Header
from fastapi.responses import HTMLResponse
import shutil
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.routers import auth
from app.ml.model import predict_heart_disease
from app.database import get_db
from app import models
from app.auth_config import hash_password, verify_password, create_access_token, create_refresh_token, decode_access_token
import re
from datetime import datetime, timedelta
import secrets
from app.email_config import send_email
from pydantic import BaseModel
from typing import Optional
from app.schemas import PatientCreate, PatientUpdate, PatientResponse, PatientListResponse, ProfileResponse
from datetime import date
from app.dependencies import get_current_user, require_role, require_status
from app.schemas import (
    HeartDiseaseInput, 
    DoctorSignup, 
    DoctorLogin, 
    TokenResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UpdateProfileRequest,
    SendVerificationEmailRequest,
    VerifyEmailRequest,
    EmailVerificationResponse,
)
import httpx
import dns.resolver
from email_validator import validate_email, EmailNotValidError
# Pydantic models for request bodies
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
class PhoneVerificationRequest(BaseModel):
    phone_number: str


# ========== CONFIGURATION FROM ENV ==========
BACKEND_URL = os.getenv("BACKEND_URL")
NUMLOOKUP_API_KEY = os.getenv("NUMLOOKUP_API_KEY")
PHONE_VERIFICATION_ENABLED = os.getenv("PHONE_VERIFICATION_ENABLED", "True").lower() == "true"


app = FastAPI(title="Heart Disease Prediction API")
app.include_router(auth.router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup security
security = HTTPBearer()

# Configure upload directories
UPLOAD_DIR = "uploads"
PROFILE_UPLOAD_DIR = "uploads/profiles"
os.makedirs(PROFILE_UPLOAD_DIR, exist_ok=True)

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
def root():
    return {"message": "Heart Disease Prediction API is running"}

# ========== AUTHENTICATION ENDPOINTS ==========
# Add this endpoint (add before the @app.post("/signup") section)

# Add this function near the top
def validate_email_address(email: str) -> tuple[bool, str]:
    """
    Validate email address with proper MX record checking
    Returns (is_valid, message)
    """
    # Check format
    if not email or '@' not in email:
        return (False, "Invalid email format")
    
    # Use email-validator library for comprehensive validation
    try:
        # This checks format, deliverability, and domain existence
        valid = validate_email(email, check_deliverability=True)
        return (True, valid.normalized)
    except EmailNotValidError as e:
        return (False, str(e))
    

# Add this near your other config (around line 30-40)
PHONE_VERIFICATION_ENABLED = os.getenv("PHONE_VERIFICATION_ENABLED", "True").lower() == "true"

@app.post("/verify-phone")
async def verify_phone(request: PhoneVerificationRequest):
    """
    Verify if a phone number is valid using NumLookup API
    Free tier: 2,000 requests/month
    """
    phone_number = request.phone_number
    
    # Remove any spaces and ensure proper format
    phone_number = phone_number.replace(" ", "")
    
    print(f"📞 Phone verification request for: {phone_number}")
    print(f"🔧 PHONE_VERIFICATION_ENABLED = {PHONE_VERIFICATION_ENABLED}")
    
    # 🔧 DEVELOPMENT MODE - Skip API call if disabled
    if not PHONE_VERIFICATION_ENABLED:
        print(f"🔧 DEV MODE: Skipping API call for {phone_number}")
        return {
            "valid": True,
            "phone_number": phone_number,
            "carrier": "Development Mode",
            "line_type": "mobile"
        }
    
    # Real API call (only runs when PHONE_VERIFICATION_ENABLED = True)
    try:
        print(f"📡 Calling NumLookup API for: {phone_number}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.numlookupapi.com/v1/validate/{phone_number}",
                params={"apikey": NUMLOOKUP_API_KEY}
            )
            
            print(f"📡 API Response Status: {response.status_code}")
            print(f"📡 API Response Body: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ API Success - Carrier: {data.get('carrier', 'N/A')}")
                
                return {
                    "valid": data.get("valid", False),
                    "phone_number": data.get("number", phone_number),
                    "local_format": data.get("local_format", ""),
                    "country_code": data.get("country_code", ""),
                    "country_name": data.get("country_name", ""),
                    "carrier": data.get("carrier", ""),
                    "line_type": data.get("line_type", ""),
                }
            else:
                print(f"⚠️ API returned status {response.status_code}")
                return {
                    "valid": True,
                    "phone_number": phone_number,
                    "message": "Verification service temporarily unavailable"
                }
                
    except Exception as e:
        print(f"❌ Phone verification error: {e}")
        return {
            "valid": True,
            "phone_number": phone_number,
            "message": f"Could not verify: {str(e)}"
        }
@app.post("/signup", response_model=TokenResponse)
async def signup(doctor_data: DoctorSignup, db: Session = Depends(get_db)):
    """Register a new doctor - requires email verification"""
    
    print(f"1. Received signup for: {doctor_data.email}")
    print(f"2. Selected role: {doctor_data.role}")
    
    try:
        # Check if email already exists
        existing = db.query(models.Doctor).filter(models.Doctor.email == doctor_data.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Both doctors and assistants start as 'pending' (needs admin approval)
        user_role = 'pending'
        user_status = 'pending'
        
        # Generate email verification token
        verification_token = secrets.token_urlsafe(32)
        
        print(f"Setting role to: {user_role} (needs admin approval)")
        
        new_doctor = models.Doctor(
            email=doctor_data.email,
            password_hash=hash_password(doctor_data.password),
            first_name=doctor_data.first_name,
            last_name=doctor_data.last_name,
            license_number=doctor_data.license_number if doctor_data.role == 'doctor' else None,
            hospital=doctor_data.hospital if doctor_data.role == 'doctor' else None,
            country=doctor_data.country if doctor_data.country else None,
            specialty=doctor_data.specialty if doctor_data.specialty else None,
            phone=doctor_data.phone if doctor_data.phone else None,
            medical_license_path=doctor_data.medical_license_path if doctor_data.role == 'doctor' else None,
            government_id_path=doctor_data.government_id_path if doctor_data.government_id_path else None,
            is_verified=True,
            terms_accepted=doctor_data.terms_accepted,
            terms_accepted_at=datetime.utcnow() if doctor_data.terms_accepted else None,
            role=user_role,
            status=user_status,
            assigned_to=None,
            email_verified=False,  # NEW: Not verified yet
            email_verification_token=verification_token,  # NEW
            email_verification_sent_at=datetime.utcnow(),  # NEW
        )
        
        db.add(new_doctor)
        db.commit()
        db.refresh(new_doctor)
        
        # Create JWT token (they can login but with restricted access until approved AND verified)
        access_token = create_access_token(data={"sub": str(new_doctor.id)})
        
        print(f"User created with ID: {new_doctor.id}, waiting for admin approval and email verification")
        
        # Send verification email
        try:
            verification_link = f"{BACKEND_URL}/verify-email-redirect?token={verification_token}"
            send_email(
                to=new_doctor.email,
                subject="Verify Your Heart Alert Email Address",
                html=f"""
                <html>
                <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 40px;">
                    <div style="max-width: 480px; margin: auto; background: white; border-radius: 12px; padding: 40px;">
                        <h2 style="color: #7A9E7E;">Heart Alert</h2>
                        <p style="color: #444;">Hello {new_doctor.first_name},</p>
                        <p style="color: #444;">Thank you for registering. Please verify your email address:</p>
                        <div style="text-align: center; margin: 32px 0;">
                            <a href="{verification_link}"
                               style="background-color: #7A9E7E; color: white; padding: 14px 32px;
                                      text-decoration: none; border-radius: 8px; font-size: 16px;
                                      font-weight: bold; display: inline-block;">
                                Verify Email
                            </a>
                        </div>
                        <p style="color: #888; font-size: 13px;">This link expires in 24 hours.</p>
                        <p style="color: #888; font-size: 13px;">After verification, an admin will review your application.</p>
                    </div>
                </body>
                </html>
                """
            )
            print(f"✅ Verification email sent to {new_doctor.email}")
        except Exception as e:
            print(f"❌ Failed to send verification email: {e}")
        
        return {
            "access_token": access_token,
            "refresh_token": None,
            "token_type": "bearer",
            "expires_in": 86400,
            "remember_me": False,
            "doctor_id": new_doctor.id,
            "email": new_doctor.email,
            "first_name": new_doctor.first_name,
            "last_name": new_doctor.last_name,
            "profile_picture": new_doctor.profile_picture,
            "role": new_doctor.role,
            "status": new_doctor.status,
            "email_verified": False  # NEW: Tell frontend to show verification dialog
        }
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/login")
def login(
    login_data: DoctorLogin,
    db: Session = Depends(get_db)
):
    """Login an existing doctor with remember me support"""
    
    # Find doctor by email
    doctor = db.query(models.Doctor).filter(models.Doctor.email == login_data.email).first()
    if not doctor:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Verify password
    if not verify_password(login_data.password, doctor.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Create access token
    access_token = create_access_token(data={"sub": str(doctor.id)})
    
    # Create refresh token if remember_me is True
    refresh_token = None
    if login_data.remember_me:
        refresh_token = create_refresh_token(data={"sub": str(doctor.id)})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 86400,
        "remember_me": login_data.remember_me,
        "doctor_id": doctor.id,
        "email": doctor.email,
        "first_name": doctor.first_name,
        "last_name": doctor.last_name,
        "profile_picture": doctor.profile_picture,
        "role": doctor.role,
        "status": doctor.status
    }

@app.post("/check-email")
def check_email(request: dict, db: Session = Depends(get_db)):
    """Check if email already exists with enhanced validation"""
    email = request.get('email', '')
    
    # Validate email format
    is_valid, message = validate_email_address(email)
    if not is_valid:
        raise HTTPException(status_code=400, detail=message)
    
    # Check if email exists
    doctor = db.query(models.Doctor).filter(models.Doctor.email == email).first()
    
    return {
        "exists": doctor is not None,
        "normalized_email": message if is_valid else email
    }

@app.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    doctor = db.query(models.Doctor).filter(models.Doctor.email == request.email).first()
    
    if not doctor:
        return {"message": "If email exists, reset link has been sent"}
    
    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    doctor.reset_token = reset_token
    doctor.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    
    # https link so email apps don't block it — redirects to heartalert:// deep link
    reset_link = f"{BACKEND_URL}/redirect-reset?token={reset_token}"
    
    print(f"\n{'='*50}")
    print(f"📧 Attempting to send email to: {doctor.email}")
    print(f"🔗 Reset link: {reset_link}")
    print(f"{'='*50}\n")
    
    try:
        send_email(
            to=doctor.email,
            subject="Reset Your Heart Alert Password",
            html=f"""<html>
            <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 40px;">
                <div style="max-width: 480px; margin: auto; background: white; border-radius: 12px; padding: 40px;">
                    <h2 style="color: #222;">Heart Alert</h2>
                    <p style="color: #444;">Hello {doctor.first_name},</p>
                    <p style="color: #444;">We received a request to reset your password. Click the button below:</p>
                    <div style="text-align: center; margin: 32px 0;">
                        <a href="{reset_link}"
                           style="background-color: #4CAF50; color: white; padding: 14px 32px;
                                  text-decoration: none; border-radius: 8px; font-size: 16px;
                                  font-weight: bold; display: inline-block;">
                            Reset Password
                        </a>
                    </div>
                    <p style="color: #888; font-size: 13px;">This link expires in 1 hour.</p>
                    <p style="color: #888; font-size: 13px;">If you didn't request this, ignore this email.</p>
                </div>
            </body>
            </html>"""
        )

        print(f"✅ Email sent successfully to {doctor.email}")
        
    except Exception as e:
        print(f"❌ Email failed: {e}")
        print(f"Error details: {str(e)}")
    
    return {"message": "If email exists, reset link has been sent"}
@app.get("/redirect-reset")
def redirect_reset(token: str, user_agent: str = Header(None)):
    """Page that email button lands on — redirects to the app via deep link"""
    
    # Check if it's a mobile device
    is_mobile = any(device in user_agent.lower() for device in ['android', 'ios', 'iphone', 'ipad'])
    
    if is_mobile:
        # Mobile: Use deep link
        redirect_url = f"heartalert://reset-password?token={token}"
        html_content = f"""
        <html>
        <head>
            <meta http-equiv="refresh" content="0;url={redirect_url}">
        </head>
        <body>
            <p>Opening app...</p>
            <a href="{redirect_url}">Click here if app doesn't open</a>
        </body>
        </html>
        """
    else:
        # Web: Direct to your Netlify URL with the token
        # REPLACE THIS WITH YOUR ACTUAL NETLIFY URL
        netlify_url = "https://heart-alert.netlify.app"  # ← CHANGE THIS TO YOUR NETLIFY URL
        
        # The Flutter web app will read the token from URL parameter
        redirect_url = f"{netlify_url}/#/reset-password?token={token}"
        
        # Use JavaScript to redirect with proper hash routing
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Redirecting...</title>
            <script>
                // Redirect to the Flutter web app with the token
                window.location.href = "{redirect_url}";
            </script>
        </head>
        <body>
            <p>Redirecting to reset your password...</p>
            <p>If you are not redirected, <a href="{redirect_url}">click here</a></p>
        </body>
        </html>
        """
    
    return HTMLResponse(content=html_content)

@app.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    doctor = db.query(models.Doctor).filter(
        models.Doctor.reset_token == request.token,
        models.Doctor.reset_token_expiry > datetime.utcnow()
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    
    doctor.password_hash = hash_password(request.new_password)
    doctor.reset_token = None
    doctor.reset_token_expiry = None
    db.commit()
    
    return {"message": "Password reset successful"}

# ========== PROFILE ENDPOINTS ==========
@app.get("/me", response_model=ProfileResponse)
def get_my_info(
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
):
    """Get current doctor's information (requires token and approval)"""
    return {
        "id": current_doctor.id,
        "email": current_doctor.email,
        "first_name": current_doctor.first_name,
        "last_name": current_doctor.last_name,
        "license_number": current_doctor.license_number,
        "hospital": current_doctor.hospital,
        "specialty": current_doctor.specialty,
        "phone": current_doctor.phone,
        "country": current_doctor.country,  # ADD THIS LINE
        "profile_picture": current_doctor.profile_picture,
        "is_verified": current_doctor.is_verified,
        "created_at": current_doctor.created_at
    }


@app.put("/me")
def update_profile(
    request: UpdateProfileRequest,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Update doctor profile"""
    
    if request.first_name:
        current_doctor.first_name = request.first_name
    if request.last_name:
        current_doctor.last_name = request.last_name
    if request.phone:
        current_doctor.phone = request.phone
    if request.hospital:
        current_doctor.hospital = request.hospital
    if request.specialty:
        current_doctor.specialty = request.specialty
    if request.country:  # ADD THIS
        current_doctor.country = request.country
    
    db.commit()
    db.refresh(current_doctor)
    
    return {
        "id": current_doctor.id,
        "email": current_doctor.email,
        "first_name": current_doctor.first_name,
        "last_name": current_doctor.last_name,
        "phone": current_doctor.phone,
        "hospital": current_doctor.hospital,
        "specialty": current_doctor.specialty,
        "country": current_doctor.country,  # ADD THIS
        "license_number": current_doctor.license_number,
        "profile_picture": current_doctor.profile_picture,
        "is_verified": current_doctor.is_verified
    }


@app.post("/upload-profile-picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Upload profile picture for the current doctor"""
    
    allowed_extensions = ['.png', '.jpg', '.jpeg']
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Only PNG, JPG, JPEG files allowed")
    
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 5MB")
    
    import uuid
    unique_filename = f"profile_{current_doctor.id}_{uuid.uuid4().hex}{file_ext}"
    file_path = os.path.join(PROFILE_UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    if current_doctor.profile_picture:
        old_file_path = os.path.join(PROFILE_UPLOAD_DIR, current_doctor.profile_picture.split("/")[-1])
        if os.path.exists(old_file_path):
            os.remove(old_file_path)
    
    relative_path = f"/uploads/profiles/{unique_filename}"
    current_doctor.profile_picture = relative_path
    db.commit()
    
    return {
        "profile_picture": relative_path,
        "message": "Profile picture uploaded successfully"
    }

@app.delete("/profile-picture")
def delete_profile_picture(
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Delete profile picture"""
    
    if current_doctor.profile_picture:
        filename = current_doctor.profile_picture.split("/")[-1]
        file_path = os.path.join(PROFILE_UPLOAD_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        current_doctor.profile_picture = None
        db.commit()
        
        return {"message": "Profile picture deleted successfully"}
    
    raise HTTPException(status_code=404, detail="No profile picture found")

@app.post("/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Change doctor password"""
    
    if not verify_password(request.current_password, current_doctor.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    
    current_doctor.password_hash = hash_password(request.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}

# ========== PREDICTION ENDPOINTS ==========

@app.post("/predict")
def predict(
    data: HeartDiseaseInput,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'admin', 'assistant'])),  # ADD 'assistant'
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    print(f"📝 Received patient_name: {data.patient_name}")
    
    # For assistants, store under assigned doctor
    doctor_id = current_doctor.id
    if current_doctor.role == 'assistant' and current_doctor.assigned_to:
        doctor_id = current_doctor.assigned_to
    
    result = predict_heart_disease(
        age=data.age,
        sex=data.sex,
        cp=data.cp,
        trestbps=data.trestbps,
        chol=data.chol,
        fbs=data.fbs,
        restecg=data.restecg,
        thalach=data.thalach,
        exang=data.exang,
        oldpeak=data.oldpeak,
        slope=data.slope,
    )
    
    prediction = models.Prediction(
        doctor_id=doctor_id,
        assistant_id=current_doctor.id if current_doctor.role == 'assistant' else None,
        patient_id=data.patient_id,
        patient_name=data.patient_name,
        age=data.age,
        sex=data.sex,
        cp=data.cp,
        trestbps=data.trestbps,
        chol=data.chol,
        fbs=data.fbs,
        restecg=data.restecg,
        thalach=data.thalach,
        exang=data.exang,
        oldpeak=data.oldpeak,
        slope=data.slope,
        risk_score=result["risk_score"],
        risk_category=result["risk_category"],
        has_disease=result["has_disease"]
    )
    
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    
    return {
        "prediction_id": prediction.id,
        "risk_score": result["risk_score"],
        "risk_category": result["risk_category"],
        "has_disease": result["has_disease"]
    }


@app.get("/history")
def get_history(
    skip: int = 0,
    limit: int = 50,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Get prediction history - assistants see their assigned doctor's history"""
    
    # For assistants, show their assigned doctor's predictions
    if current_doctor.role == 'assistant' and current_doctor.assigned_to:
        doctor_id = current_doctor.assigned_to
        query = db.query(models.Prediction).filter(
            (models.Prediction.doctor_id == doctor_id) |
            (models.Prediction.assistant_id == current_doctor.id)
        )
    else:
        query = db.query(models.Prediction).filter(models.Prediction.doctor_id == current_doctor.id)
    
    total = query.count()
    predictions = query.order_by(desc(models.Prediction.created_at)).offset(skip).limit(limit).all()
    
    result = []
    for p in predictions:
        # Get patient name
        patient_name = p.patient_name
        if p.patient_id and not patient_name:
            patient = db.query(models.Patient).filter(models.Patient.id == p.patient_id).first()
            if patient:
                patient_name = f"{patient.first_name} {patient.last_name}"
        
        result.append({
            "id": p.id,
            "doctor_id": p.doctor_id,
            "age": p.age,
            "sex": p.sex,
            "cp": p.cp,
            "trestbps": p.trestbps,
            "chol": p.chol,
            "fbs": p.fbs,
            "restecg": p.restecg,
            "thalach": p.thalach,
            "exang": p.exang,
            "oldpeak": p.oldpeak,
            "slope": p.slope,
            "risk_score": p.risk_score,
            "risk_category": p.risk_category,
            "has_disease": p.has_disease,
            "patient_name": patient_name or "Anonymous Patient",
            "notes": p.notes,
            "created_at": p.created_at,
            "patient": {"name": patient_name or "Anonymous Patient"}  # For compatibility
        })
    
    return {
        "total": total,
        "predictions": result
    }


# ========== PATIENT MANAGEMENT ENDPOINTS ==========

@app.post("/patients", response_model=PatientResponse)
def create_patient(
    patient: PatientCreate,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Create a new patient - assistants create under assigned doctor"""
    
    # For assistants, associate with their assigned doctor
    doctor_id = current_doctor.id
    if current_doctor.role == 'assistant' and current_doctor.assigned_to:
        doctor_id = current_doctor.assigned_to
    
    new_patient = models.Patient(
        doctor_id=doctor_id,
        assistant_id=current_doctor.id if current_doctor.role == 'assistant' else None,
        first_name=patient.first_name,
        last_name=patient.last_name,
        date_of_birth=patient.date_of_birth,
        gender=patient.gender,
        phone=patient.phone,
        email=patient.email,
        address=patient.address,
        medical_history=patient.medical_history,
        notes=patient.notes,
    )
    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)
    return new_patient


@app.get("/patients", response_model=PatientListResponse)
def get_patients(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Get all patients - assistants see their assigned doctor's patients"""
    
    # For assistants, show their assigned doctor's patients
    if current_doctor.role == 'assistant' and current_doctor.assigned_to:
        doctor_id = current_doctor.assigned_to
        query = db.query(models.Patient).filter(
            (models.Patient.doctor_id == doctor_id) |
            (models.Patient.assistant_id == current_doctor.id)
        )
    else:
        query = db.query(models.Patient).filter(models.Patient.doctor_id == current_doctor.id)
    
    if search:
        query = query.filter(
            (models.Patient.first_name.ilike(f"%{search}%")) |
            (models.Patient.last_name.ilike(f"%{search}%")) |
            (models.Patient.phone.ilike(f"%{search}%"))
        )
    
    total = query.count()
    patients = query.order_by(desc(models.Patient.created_at)).offset(skip).limit(limit).all()
    
    return {"total": total, "patients": patients}


@app.get("/patients/{patient_id}", response_model=PatientResponse)
def get_patient(
    patient_id: int,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Get a specific patient - assistants can access their doctor's patients"""
    
    if current_doctor.role == 'assistant' and current_doctor.assigned_to:
        patient = db.query(models.Patient).filter(
            models.Patient.id == patient_id,
            (models.Patient.doctor_id == current_doctor.assigned_to) |
            (models.Patient.assistant_id == current_doctor.id)
        ).first()
    else:
        patient = db.query(models.Patient).filter(
            models.Patient.id == patient_id,
            models.Patient.doctor_id == current_doctor.id
        ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@app.put("/patients/{patient_id}", response_model=PatientResponse)
def update_patient(
    patient_id: int,
    patient_update: PatientUpdate,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Update a patient - assistants can update their doctor's patients"""
    
    if current_doctor.role == 'assistant' and current_doctor.assigned_to:
        patient = db.query(models.Patient).filter(
            models.Patient.id == patient_id,
            (models.Patient.doctor_id == current_doctor.assigned_to) |
            (models.Patient.assistant_id == current_doctor.id)
        ).first()
    else:
        patient = db.query(models.Patient).filter(
            models.Patient.id == patient_id,
            models.Patient.doctor_id == current_doctor.id
        ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    for field, value in patient_update.dict(exclude_unset=True).items():
        setattr(patient, field, value)
    
    db.commit()
    db.refresh(patient)
    return patient
@app.delete("/patients/{patient_id}")
def delete_patient(
    patient_id: int,
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Delete a patient and all associated predictions"""
    
    patient = db.query(models.Patient).filter(
        models.Patient.id == patient_id,
        models.Patient.doctor_id == current_doctor.id
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    db.query(models.Prediction).filter(
        models.Prediction.patient_id == patient_id
    ).delete()
    
    db.delete(patient)
    db.commit()
    
    return {"message": "Patient and associated predictions deleted successfully"}

# ========== ASSISTANT REQUEST ENDPOINTS ==========

@app.post("/doctor/request-assistant")
def request_assistant(
    request_data: dict,
    current_doctor: models.Doctor = Depends(require_role(['doctor'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Doctor requests an assistant"""
    
    assistant_email = request_data.get('assistant_email')
    assistant_name = request_data.get('assistant_name')
    assistant_phone = request_data.get('assistant_phone')
    notes = request_data.get('notes')
    
    if not assistant_email or not assistant_name:
        raise HTTPException(status_code=400, detail="Email and name are required")
    
    # Check if doctor already has an assistant
    existing_assistant = db.query(models.Doctor).filter(
        models.Doctor.assigned_to == current_doctor.id,
        models.Doctor.role == 'assistant'
    ).first()
    
    if existing_assistant:
        raise HTTPException(status_code=400, detail="You already have an assistant")
    
    # Check if there's already a pending request
    existing_request = db.query(models.AssistantRequest).filter(
        models.AssistantRequest.doctor_id == current_doctor.id,
        models.AssistantRequest.status == 'pending'
    ).first()
    
    if existing_request:
        raise HTTPException(status_code=400, detail="You already have a pending request")
    
    # Create request
    new_request = models.AssistantRequest(
        doctor_id=current_doctor.id,
        assistant_email=assistant_email,
        assistant_name=assistant_name,
        assistant_phone=assistant_phone,
        status='pending',
        notes=notes
    )
    
    db.add(new_request)
    db.commit()
    db.refresh(new_request)
    
    return {
        "message": "Assistant request submitted. Admin will review it.",
        "request_id": new_request.id
    }

@app.get("/admin/assistant-requests")
def get_assistant_requests(
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Get all PENDING assistant requests (admin only)"""
    
    # Filter to only show pending requests
    requests = db.query(models.AssistantRequest).filter(
        models.AssistantRequest.status == 'pending'
    ).order_by(
        desc(models.AssistantRequest.created_at)
    ).all()
    
    result = []
    for req in requests:
        doctor = db.query(models.Doctor).filter(models.Doctor.id == req.doctor_id).first()
        result.append({
            "id": req.id,
            "doctor_id": req.doctor_id,
            "doctor_name": f"{doctor.first_name} {doctor.last_name}" if doctor else "Unknown",
            "doctor_email": doctor.email if doctor else "",
            "assistant_email": req.assistant_email,
            "assistant_name": req.assistant_name,
            "assistant_phone": req.assistant_phone,
            "status": req.status,
            "notes": req.notes,
            "created_at": req.created_at
        })
    
    return result

@app.post("/admin/approve-request/{request_id}")
async def approve_request(
    request_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Approve an assistant request and assign to the requesting doctor"""
    
    # Get the request
    request = db.query(models.AssistantRequest).filter(
        models.AssistantRequest.id == request_id,
        models.AssistantRequest.status == 'pending'
    ).first()
    
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Check if doctor already has an assistant
    existing_assistant = db.query(models.Doctor).filter(
        models.Doctor.assigned_to == request.doctor_id,
        models.Doctor.role == 'assistant'
    ).first()
    
    if existing_assistant:
        request.status = 'rejected'
        db.commit()
        raise HTTPException(status_code=400, detail="Doctor already has an assistant")
    
    import secrets
    from app.auth_config import hash_password
    
    # Generate a single password that will be used for both hash and email
    temp_password = secrets.token_urlsafe(12)
    
    # Hash the SAME password
    hashed_password = hash_password(temp_password)
    
    # Check if assistant already exists (by email)
    existing_assistant_account = db.query(models.Doctor).filter(
        models.Doctor.email == request.assistant_email
    ).first()
    
    if existing_assistant_account:
        # Assistant exists - update their password and assign them
        existing_assistant_account.password_hash = hashed_password
        existing_assistant_account.role = 'assistant'
        existing_assistant_account.status = 'approved'
        existing_assistant_account.assigned_to = request.doctor_id
        assistant_id = existing_assistant_account.id
        assistant_email = existing_assistant_account.email
        assistant_name = f"{existing_assistant_account.first_name} {existing_assistant_account.last_name}"
        is_new = False
    else:
        # Create new assistant account with the hashed password
        name_parts = request.assistant_name.split(' ')
        first_name = name_parts[0]
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        
        new_assistant = models.Doctor(
            email=request.assistant_email,
            password_hash=hashed_password,  # Use the same hashed password
            first_name=first_name,
            last_name=last_name,
            phone=request.assistant_phone,
            role='assistant',
            status='approved',
            assigned_to=request.doctor_id,
            is_verified=True,
            terms_accepted=True
        )
        db.add(new_assistant)
        db.flush()
        assistant_id = new_assistant.id
        assistant_email = new_assistant.email
        assistant_name = f"{first_name} {last_name}"
        is_new = True
    
    # Update request status
    request.status = 'approved'
    
    # Get doctor name for email
    doctor = db.query(models.Doctor).filter(models.Doctor.id == request.doctor_id).first()
    
    db.commit()
    
    # Verify the password works before sending email
    from app.auth_config import verify_password
    verify_test = verify_password(temp_password, hashed_password)
    
    print(f"🔑 Password: {temp_password}")
    print(f"📧 Sent to: {assistant_email}")
    print(f"✅ Verification test: {'PASSED' if verify_test else 'FAILED'}")
    
    # Send email to assistant with the password
    try:
        send_email(
            to=assistant_email,
            subject="Your Heart Alert Assistant Account",
            html=f"""
            <html>
            <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 40px;">
                <div style="max-width: 480px; margin: auto; background: white; border-radius: 12px; padding: 40px;">
                    <h2 style="color: #7A9E7E;">Heart Alert</h2>
                    <p style="color: #444;">Dear {assistant_name},</p>
                    <p style="color: #444;">Dr. {doctor.first_name} {doctor.last_name} has requested you as their assistant in Heart Alert.</p>
                    <p style="color: #444;">Your account has been created:</p>
                    <div style="background: #f4f4f4; padding: 16px; border-radius: 8px; margin: 16px 0;">
                        <p style="margin: 4px 0;"><strong>Email:</strong> {assistant_email}</p>
                        <p style="margin: 4px 0;"><strong>Temporary Password:</strong> {temp_password}</p>
                    </div>
                    <p style="color: #444;">Please login and change your password immediately.</p>
                    <div style="text-align: center; margin: 32px 0;">
                        <a href="heartalert://login"
                           style="background-color: #7A9E7E; color: white; padding: 12px 24px;
                                  text-decoration: none; border-radius: 8px;">
                            Open Heart Alert App
                        </a>
                    </div>
                    <p style="color: #888; font-size: 12px;">This is an automated message, please do not reply.</p>
                </div>
            </body>
            </html>
            """
        )
        print(f"📧 Welcome email sent to {assistant_email}")
        
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        # Don't fail the request if email fails
    
    return {
        "message": f"Assistant approved and assigned to Dr. {doctor.first_name} {doctor.last_name}",
        "assistant_id": assistant_id,
        "is_new": is_new,
        "temp_password": temp_password if is_new else None
    }

@app.post("/admin/reject-request/{request_id}")
def reject_request(
    request_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Reject an assistant request"""
    
    request = db.query(models.AssistantRequest).filter(
        models.AssistantRequest.id == request_id,
        models.AssistantRequest.status == 'pending'
    ).first()
    
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    request.status = 'rejected'
    db.commit()
    
    return {"message": "Request rejected"}

# ========== CHATBOT ENDPOINT ==========

import httpx

GEMINI_API_KEY = "your-key"

@app.post("/chat")
async def chat(
    message: str, 
    current_doctor: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": message}]}]}
        )
    return response.json()

# ========== ADMIN ENDPOINTS ==========

@app.get("/admin/doctors")
def get_all_doctors(
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Get all approved doctors (for admin to assign assistants)"""
    doctors = db.query(models.Doctor).filter(
        models.Doctor.role == 'doctor',
        models.Doctor.status == 'approved'
    ).all()
    
    result = []
    for doctor in doctors:
        # Check if doctor already has an assistant
        assistant = db.query(models.Doctor).filter(
            models.Doctor.assigned_to == doctor.id,
            models.Doctor.role == 'assistant'
        ).first()
        
        result.append({
            "id": doctor.id,
            "first_name": doctor.first_name,
            "last_name": doctor.last_name,
            "email": doctor.email,
            "specialty": doctor.specialty,
            "has_assistant": assistant is not None,
            "assistant_id": assistant.id if assistant else None,
            "assistant_name": f"{assistant.first_name} {assistant.last_name}" if assistant else None
        })
    
    return result

@app.get("/admin/pending-assistants")
def get_pending_assistants(
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Get all pending assistant registrations (users who signed up as assistants)"""
    # Get all pending users
    all_pending = db.query(models.Doctor).filter(
        models.Doctor.role == 'pending',
        models.Doctor.status == 'pending'
    ).all()
    
    # Filter only those who signed up as assistants (no license_number or hospital)
    assistants = []
    for user in all_pending:
        if not user.license_number and not user.hospital:
            assistants.append(user)
    
    return assistants


@app.get("/doctor/pending-request")
def get_doctor_pending_request(
    current_doctor: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Check if doctor has a pending assistant request"""
    
    pending_request = db.query(models.AssistantRequest).filter(
        models.AssistantRequest.doctor_id == current_doctor.id,
        models.AssistantRequest.status == 'pending'
    ).first()
    
    return {
        "has_pending": pending_request is not None,
        "request_id": pending_request.id if pending_request else None
    }


@app.get("/admin/pending-doctors")
def get_pending_doctors(
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Get all pending doctor registrations with email verification status"""
    
    all_pending = db.query(models.Doctor).filter(
        models.Doctor.role == 'pending',
        models.Doctor.status == 'pending'
    ).all()
    
    doctors = []
    for user in all_pending:
        if user.license_number or user.hospital:
            doctors.append({
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "license_number": user.license_number,
                "hospital": user.hospital,
                "specialty": user.specialty,
                "country": user.country,
                "phone": user.phone,
                "created_at": user.created_at,
                "email_verified": user.email_verified,  # ADD THIS
                "email_verification_sent_at": user.email_verification_sent_at,  # ADD THIS
                "medical_license_url": f"{BACKEND_URL}/{user.medical_license_path}" if user.medical_license_path else None,
                "government_id_url": f"{BACKEND_URL}/{user.government_id_path}" if user.government_id_path else None,
            })
    
    return doctors

@app.put("/admin/approve-assistant/{assistant_id}")
def approve_assistant(
    assistant_id: int,
    assigned_doctor_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Approve an assistant and assign them to a doctor (one-to-one)"""
    
    # Check if assistant exists and is pending
    assistant = db.query(models.Doctor).filter(
        models.Doctor.id == assistant_id,
        models.Doctor.role == 'pending'
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found or already processed")
    
    # Verify this is actually an assistant (no license/hospital)
    if assistant.license_number or assistant.hospital:
        raise HTTPException(status_code=400, detail="This user is a doctor, not an assistant")
    
    # Check if doctor exists and is approved
    doctor = db.query(models.Doctor).filter(
        models.Doctor.id == assigned_doctor_id,
        models.Doctor.role == 'doctor',
        models.Doctor.status == 'approved'
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found or not approved")
    
    # Check if doctor already has an assistant
    existing_assistant = db.query(models.Doctor).filter(
        models.Doctor.assigned_to == assigned_doctor_id,
        models.Doctor.role == 'assistant'
    ).first()
    
    if existing_assistant:
        raise HTTPException(
            status_code=400, 
            detail=f"Doctor already has an assistant: {existing_assistant.first_name} {existing_assistant.last_name}"
        )
    
    # Update assistant
    assistant.role = 'assistant'
    assistant.status = 'approved'
    assistant.assigned_to = assigned_doctor_id
    
    db.commit()
    db.refresh(assistant)
    
    return {
        "message": f"Assistant {assistant.first_name} {assistant.last_name} approved and assigned to Dr. {doctor.first_name} {doctor.last_name}",
        "assistant_id": assistant.id,
        "doctor_id": doctor.id
    }

@app.put("/admin/approve-doctor/{doctor_id}")
def approve_doctor(
    doctor_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Approve a doctor registration - only if email is verified"""
    
    doctor = db.query(models.Doctor).filter(
        models.Doctor.id == doctor_id,
        models.Doctor.role == 'pending'
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found or already processed")
    
    if not doctor.license_number and not doctor.hospital:
        raise HTTPException(status_code=400, detail="This user is an assistant, not a doctor")
    
    # CHECK IF EMAIL IS VERIFIED
    if not doctor.email_verified:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot approve: {doctor.email} has not verified their email. Please ask them to check their inbox."
        )
    
    doctor.role = 'doctor'
    doctor.status = 'approved'
    db.commit()
    db.refresh(doctor)
    
    return {
        "message": f"Doctor {doctor.first_name} {doctor.last_name} approved",
        "doctor_id": doctor.id,
        "email_verified": doctor.email_verified
    }

@app.post("/admin/reject-assistant/{assistant_id}")
def reject_assistant(
    assistant_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Reject an assistant registration"""
    
    assistant = db.query(models.Doctor).filter(
        models.Doctor.id == assistant_id,
        models.Doctor.role == 'pending'
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    assistant.status = 'suspended'
    db.commit()
    
    return {"message": f"Assistant {assistant.first_name} {assistant.last_name} rejected"}

@app.post("/admin/reject-doctor/{doctor_id}")
def reject_doctor(
    doctor_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Reject a doctor registration"""
    
    doctor = db.query(models.Doctor).filter(
        models.Doctor.id == doctor_id,
        models.Doctor.role == 'pending'
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    doctor.status = 'suspended'
    db.commit()
    
    return {"message": f"Doctor {doctor.first_name} {doctor.last_name} rejected"}

@app.get("/admin/assistants")
def get_all_assistants(
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Get all approved assistants with their assigned doctors"""
    
    assistants = db.query(models.Doctor).filter(
        models.Doctor.role == 'assistant',
        models.Doctor.status == 'approved'
    ).all()
    
    result = []
    for assistant in assistants:
        doctor = None
        if assistant.assigned_to:
            doctor = db.query(models.Doctor).filter(
                models.Doctor.id == assistant.assigned_to
            ).first()
        
        result.append({
            "id": assistant.id,
            "first_name": assistant.first_name,
            "last_name": assistant.last_name,
            "email": assistant.email,
            "phone": assistant.phone,
            "assigned_doctor_id": assistant.assigned_to,
            "assigned_doctor_name": f"{doctor.first_name} {doctor.last_name}" if doctor else None,
            "created_at": assistant.created_at
        })
    
    return result

@app.delete("/admin/remove-assistant/{assistant_id}")
def remove_assistant(
    assistant_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Remove an assistant (set role back to pending)"""
    
    assistant = db.query(models.Doctor).filter(
        models.Doctor.id == assistant_id,
        models.Doctor.role == 'assistant'
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    assistant.role = 'pending'
    assistant.status = 'pending'
    assistant.assigned_to = None
    
    db.commit()
    
    return {"message": "Assistant removed successfully"}

@app.get("/doctor/assistant")
def get_my_assistant(
    current_doctor: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Get the assistant assigned to this doctor"""
    assistant = db.query(models.Doctor).filter(
        models.Doctor.assigned_to == current_doctor.id,
        models.Doctor.role == 'assistant',
        models.Doctor.status == 'approved'
    ).first()
    
    if not assistant:
        return {"has_assistant": False}
    
    return {
        "has_assistant": True,
        "id": assistant.id,
        "first_name": assistant.first_name,
        "last_name": assistant.last_name,
        "email": assistant.email,
        "phone": assistant.phone,
    }

# ========== DOCUMENT UPLOAD ==========
@app.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...),
):
    """Upload medical license or government ID - stored as base64 in DB (no auth required at signup)"""
    import base64

    allowed_extensions = ['.png', '.jpg', '.jpeg', '.pdf']
    file_ext = os.path.splitext(file.filename)[1].lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Only PNG, JPG, JPEG, PDF files allowed")

    # Read and check file size (5MB max)
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 5MB")

    # Encode as base64 data URL so it persists in DB (Render filesystem is ephemeral)
    mime_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.pdf': 'application/pdf'
    }
    mime_type = mime_map.get(file_ext, 'application/octet-stream')
    b64 = base64.b64encode(contents).decode('utf-8')
    data_url = f"data:{mime_type};base64,{b64}"

    return {"file_path": data_url}

@app.get("/my-status")
def get_my_status(
    current_user: models.Doctor = Depends(get_current_user),  # No require_status here!
    db: Session = Depends(get_db)
):
    """Get current user's status (works even for pending users)"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "status": current_user.status,
        "assigned_to": current_user.assigned_to
    }

@app.get("/admin/doctor/{doctor_id}")
def get_doctor_details(
    doctor_id: int,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Get detailed doctor information including document paths (admin only)"""
    
    doctor = db.query(models.Doctor).filter(
        models.Doctor.id == doctor_id,
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    backend_url = BACKEND_URL.rstrip('/')
    
    medical_license_url = None
    government_id_url = None
    
    if doctor.medical_license_path:
        medical_license_url = f"{backend_url}/{doctor.medical_license_path}"
    if doctor.government_id_path:
        government_id_url = f"{backend_url}/{doctor.government_id_path}"
    
    return {
        "id": doctor.id,
        "email": doctor.email,
        "first_name": doctor.first_name,
        "last_name": doctor.last_name,
        "license_number": doctor.license_number,
        "hospital": doctor.hospital,
        "country": doctor.country,
        "specialty": doctor.specialty,
        "phone": doctor.phone,
        "role": doctor.role,
        "status": doctor.status,
        "email_verified": doctor.email_verified,  # MAKE SURE THIS LINE EXISTS
        "email_verification_sent_at": doctor.email_verification_sent_at,  # ADD THIS TOO
        "medical_license_path": doctor.medical_license_path,
        "medical_license_url": medical_license_url,
        "government_id_path": doctor.government_id_path,
        "government_id_url": government_id_url,
        "created_at": doctor.created_at
    }

@app.get("/assistant/doctor")
def get_assigned_doctor(
    current_user: models.Doctor = Depends(require_role(['assistant'])),
    db: Session = Depends(get_db)
):
    """Get the doctor this assistant is assigned to"""
    
    # Check if user is approved
    if current_user.status != 'approved':
        raise HTTPException(status_code=403, detail="Account not approved")
    
    if not current_user.assigned_to:
        return {
            "id": 0,
            "first_name": "No",
            "last_name": "Doctor Assigned",
            "email": "",
            "specialty": "Not assigned",
            "hospital": "Contact administrator"
        }
    
    doctor = db.query(models.Doctor).filter(
        models.Doctor.id == current_user.assigned_to
    ).first()
    
    if not doctor:
        return {
            "id": 0,
            "first_name": "Unknown",
            "last_name": "Doctor",
            "email": "",
            "specialty": "Not assigned",
            "hospital": "Contact administrator"
        }
    
    return {
        "id": doctor.id,
        "first_name": doctor.first_name,
        "last_name": doctor.last_name,
        "email": doctor.email,
        "specialty": doctor.specialty or "Cardiologist",
        "hospital": doctor.hospital or "Hospital"
    }

    # ========== EMAIL VERIFICATION ENDPOINTS ==========

@app.post("/send-verification-email")
async def send_verification_email(
    request: SendVerificationEmailRequest,
    db: Session = Depends(get_db)
):
    """Send a verification email to the user"""
    
    doctor = db.query(models.Doctor).filter(models.Doctor.email == request.email).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="User not found")
    
    if doctor.email_verified:
        return {"message": "Email already verified", "already_verified": True}
    
    # Generate verification token
    verification_token = secrets.token_urlsafe(32)
    doctor.email_verification_token = verification_token
    doctor.email_verification_sent_at = datetime.utcnow()
    db.commit()
    
    # Create verification link
    verification_link = f"{BACKEND_URL}/verify-email-redirect?token={verification_token}"
    
    try:
        send_email(
            to=doctor.email,
            subject="Verify Your Heart Alert Email Address",
            html=f"""
            <html>
            <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 40px;">
                <div style="max-width: 480px; margin: auto; background: white; border-radius: 12px; padding: 40px;">
                    <h2 style="color: #7A9E7E;">Heart Alert</h2>
                    <p style="color: #444;">Hello {doctor.first_name},</p>
                    <p style="color: #444;">Please verify your email address to complete your registration.</p>
                    <div style="text-align: center; margin: 32px 0;">
                        <a href="{verification_link}"
                        style="background-color: #7A9E7E; color: white; padding: 14px 32px;
                                text-decoration: none; border-radius: 8px; font-size: 16px;
                                font-weight: bold; display: inline-block;">
                            Verify Email
                        </a>
                    </div>
                    <p style="color: #888; font-size: 13px;">This link expires in 24 hours.</p>
                    <p style="color: #888; font-size: 13px;">If you didn't create an account, ignore this email.</p>
                </div>
            </body>
            </html>
            """
        )
        print(f"✅ Verification email sent to {doctor.email}")
        
        return {"message": "Verification email sent", "already_verified": False}
        
    except Exception as e:
        print(f"❌ Failed to send verification email: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@app.get("/verify-email-redirect")
def verify_email_redirect(token: str):
    """Page that email button lands on - automatically verifies and shows result"""
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Email Verification | Heart Alert</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background: #f5f5f0;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
            }}
            .card {{
                background: white;
                border-radius: 24px;
                padding: 40px 32px;
                max-width: 400px;
                margin: 20px;
                text-align: center;
                box-shadow: 0 10px 40px rgba(0,0,0,0.08);
                border: 1px solid #e8e8e0;
            }}
            .spinner {{
                width: 50px;
                height: 50px;
                border: 3px solid #e8e8e0;
                border-top-color: #7A9E7E;
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
                margin: 0 auto 20px;
            }}
            @keyframes spin {{
                to {{ transform: rotate(360deg); }}
            }}
            .success-icon {{
                width: 50px;
                height: 50px;
                background: #e8f5e9;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 20px;
                font-size: 28px;
                font-weight: bold;
                color: #2e7d32;
            }}
            .error-icon {{
                width: 50px;
                height: 50px;
                background: #ffebee;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 20px;
                font-size: 28px;
                font-weight: bold;
                color: #c62828;
            }}
            h2 {{
                color: #222;
                font-size: 24px;
                font-weight: 700;
                margin: 0 0 12px;
            }}
            p {{
                color: #555;
                font-size: 15px;
                line-height: 1.5;
                margin: 0 0 24px;
            }}
        </style>
    </head>
    <body>
        <div class="card" id="content">
            <div class="spinner" id="spinner"></div>
            <h2 id="title">Verifying your email...</h2>
            <p id="message">Please wait while we verify your email address.</p>
        </div>

        <script>
            async function verifyEmail() {{
                const token = '{token}';
                
                if (!token) {{
                    showError('Invalid verification link');
                    return;
                }}
                
                try {{
                    const response = await fetch('/verify-email', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ token: token }})
                    }});
                    
                    const data = await response.json();
                    
                    if (response.ok && data.verified) {{
                        showSuccess('Email verified successfully! You can now close this page.');
                    }} else {{
                        showError(data.message || 'Verification failed. The link may be expired.');
                    }}
                }} catch (error) {{
                    console.error('Error:', error);
                    showError('Network error. Please check your connection.');
                }}
            }}
            
            function showSuccess(message) {{
                document.getElementById('spinner').style.display = 'none';
                document.getElementById('spinner').outerHTML = '<div class="success-icon">✓</div>';
                document.getElementById('title').textContent = 'Email Verified!';
                document.getElementById('message').textContent = message;
            }}
            
            function showError(message) {{
                document.getElementById('spinner').style.display = 'none';
                document.getElementById('spinner').outerHTML = '<div class="error-icon">✗</div>';
                document.getElementById('title').textContent = 'Verification Failed';
                document.getElementById('message').textContent = message;
            }}
            
            // Start verification
            verifyEmail();
        </script>
    </body>
    </html>
    """)

@app.post("/verify-email")
def verify_email(
    request: VerifyEmailRequest,
    db: Session = Depends(get_db)
):
    """Verify email using token"""
    
    doctor = db.query(models.Doctor).filter(
        models.Doctor.email_verification_token == request.token,
        models.Doctor.email_verification_sent_at > datetime.utcnow() - timedelta(days=1)
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    
    doctor.email_verified = True
    doctor.email_verification_token = None
    db.commit()
    
    return {
        "verified": True,
        "message": "Email verified successfully",
        "email": doctor.email
    }


@app.get("/check-email-verified")
def check_email_verified(
    email: str,
    db: Session = Depends(get_db)
):
    """Check if an email has been verified"""
    
    doctor = db.query(models.Doctor).filter(models.Doctor.email == email).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "verified": doctor.email_verified,
        "email": doctor.email
    }

@app.post("/doctor/cancel-request/{request_id}")
def cancel_assistant_request(
    request_id: int,
    current_doctor: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Cancel a pending assistant request"""
    
    request = db.query(models.AssistantRequest).filter(
        models.AssistantRequest.id == request_id,
        models.AssistantRequest.doctor_id == current_doctor.id,
        models.AssistantRequest.status == 'pending'
    ).first()
    
    if not request:
        raise HTTPException(status_code=404, detail="Pending request not found")
    
    db.delete(request)
    db.commit()
    
    return {"message": "Request cancelled successfully"}