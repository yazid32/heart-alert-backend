# Load environment variables FIRST before any other imports
import os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, HTTPException, status, Query, UploadFile, File, Header, Request
from fastapi.responses import HTMLResponse
import shutil
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
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
    print(f"2. Invite token: {doctor_data.invite_token}")
    
    try:
        # Check if email already exists
        existing = db.query(models.Doctor).filter(models.Doctor.email == doctor_data.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Both doctors and assistants start as 'pending' (needs admin approval)
        user_role = 'pending'
        user_status = 'pending'
        
        # Check if this is a hospital invite
        subscription_plan = 'freemium'
        is_hospital_invite = False
        hospital_admin_id = None
        
        if doctor_data.invite_token:
            # Find the invitation
            invitation = db.query(models.HospitalInvitation).filter(
                models.HospitalInvitation.token == doctor_data.invite_token,
                models.HospitalInvitation.expires_at > datetime.utcnow(),
                models.HospitalInvitation.status == 'pending'
            ).first()
            
            if invitation:
                is_hospital_invite = True
                hospital_admin_id = invitation.hospital_admin_id
                subscription_plan = 'pro'  # Doctor gets Pro for free
                print(f"✅ Hospital invite accepted from admin ID: {hospital_admin_id}")
        
        # Generate email verification token
        verification_token = secrets.token_urlsafe(32)
        
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
            email_verified=False,
            email_verification_token=verification_token,
            email_verification_sent_at=datetime.utcnow(),
            subscription_plan=subscription_plan,
            subscription_status='active',
            monthly_predictions_count=0,
            last_prediction_reset=datetime.utcnow().date(),
        )
        
        db.add(new_doctor)
        db.commit()
        db.refresh(new_doctor)
        
        # ========== HANDLE HOSPITAL INVITATION ==========
        if is_hospital_invite and hospital_admin_id:
            # Link doctor to hospital
            hospital_doctor = models.HospitalDoctor(
                hospital_admin_id=hospital_admin_id,
                doctor_id=new_doctor.id,
                status='active',
                accepted_at=datetime.utcnow()
            )
            db.add(hospital_doctor)
            
            # Mark invitation as used
            invitation.status = 'used'
            db.commit()
            
            print(f"✅ Doctor {new_doctor.email} linked to hospital admin {hospital_admin_id}")
        
        # Create JWT token
        access_token = create_access_token(data={"sub": str(new_doctor.id)})
        
        # Send verification email
        try:
            verification_link = f"{BACKEND_URL}/verify-email-redirect?token={verification_token}"
            send_email(
                to=new_doctor.email,
                subject="Verify Your Heart Alert Email Address",
                html=f"""
                <html>
                <body style="font-family: Arial, sans-serif;">
                    <div style="max-width: 480px; margin: auto; padding: 20px;">
                        <h2 style="color: #7A9E7E;">Welcome to Heart Alert!</h2>
                        <p>Hello {new_doctor.first_name},</p>
                        <p>Please verify your email address to complete your registration.</p>
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{verification_link}"
                               style="background-color: #7A9E7E; color: white; padding: 12px 24px;
                                      text-decoration: none; border-radius: 8px;">
                                Verify Email
                            </a>
                        </div>
                        <p style="color: #888; font-size: 12px;">This link expires in 24 hours.</p>
                    </div>
                </body>
                </html>
                """
            )
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
            "email_verified": False,
            "subscription_plan": subscription_plan
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
        "id": doctor.id,
        "doctor_id": doctor.id,
        "email": doctor.email,
        "first_name": doctor.first_name,
        "last_name": doctor.last_name,
        "profile_picture": doctor.profile_picture,
        "role": doctor.role,
        "status": doctor.status,
        "subscription_plan": doctor.subscription_plan if doctor.subscription_plan else "freemium",
        "plan": doctor.subscription_plan if doctor.subscription_plan else "freemium",
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
        # Web: Show the reset password form directly in this page
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Reset Password - Heart Alert</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f5f5f0;
                    margin: 0;
                    padding: 20px;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                }}
                .container {{
                    background: white;
                    border-radius: 24px;
                    padding: 32px;
                    max-width: 400px;
                    width: 100%;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
                }}
                h2 {{
                    color: #222;
                    margin-bottom: 8px;
                }}
                .subtitle {{
                    color: #666;
                    margin-bottom: 24px;
                }}
                input {{
                    width: 100%;
                    padding: 14px 16px;
                    border: 1px solid #ddd;
                    border-radius: 12px;
                    font-size: 16px;
                    margin-bottom: 16px;
                    box-sizing: border-box;
                }}
                input:focus {{
                    outline: none;
                    border-color: #7A9E7E;
                }}
                button {{
                    width: 100%;
                    padding: 14px;
                    background: #7A9E7E;
                    color: white;
                    border: none;
                    border-radius: 12px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: background 0.3s;
                }}
                button:hover {{
                    background: #6b8a6f;
                }}
                button:disabled {{
                    background: #ccc;
                    cursor: not-allowed;
                }}
                .error {{
                    color: #dc3545;
                    font-size: 13px;
                    margin-bottom: 16px;
                    padding: 10px;
                    background: #f8d7da;
                    border-radius: 8px;
                    display: none;
                }}
                .requirements {{
                    font-size: 12px;
                    color: #666;
                    margin-top: -12px;
                    margin-bottom: 16px;
                    padding-left: 4px;
                }}
                .requirements span {{
                    display: inline-block;
                    margin-right: 12px;
                }}
                .valid {{
                    color: #28a745;
                }}
                .invalid {{
                    color: #dc3545;
                }}
                .spinner {{
                    display: inline-block;
                    width: 18px;
                    height: 18px;
                    border: 2px solid white;
                    border-top-color: transparent;
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                    vertical-align: middle;
                    margin-right: 8px;
                }}
                @keyframes spin {{
                    to {{ transform: rotate(360deg); }}
                }}
                .check-icon {{
                    font-size: 48px;
                    text-align: center;
                    display: block;
                    margin-bottom: 16px;
                }}
                .success-box {{
                    background: #d4edda;
                    padding: 20px;
                    border-radius: 12px;
                    text-align: center;
                }}
                .success-message {{
                    color: #155724;
                    font-size: 14px;
                    margin-bottom: 20px;
                    line-height: 1.5;
                }}
                .login-button {{
                    display: block;
                    width: 100%;
                    background: #7A9E7E;
                    color: white;
                    text-align: center;
                    padding: 14px;
                    border-radius: 12px;
                    text-decoration: none;
                    font-size: 16px;
                    font-weight: 600;
                    box-sizing: border-box;
                    transition: background 0.3s;
                }}
                .login-button:hover {{
                    background: #6b8a6f;
                }}
            </style>
        </head>
        <body>
            <div class="container" id="formContainer">
                <h2>Reset Password</h2>
                <p class="subtitle">Create a new password for your account</p>
                
                <div id="error" class="error"></div>
                
                <input type="password" id="password" placeholder="New password" onkeyup="validatePassword()">
                <div class="requirements">
                    <span id="lengthReq" class="invalid">✗ 8+ characters</span>
                    <span id="upperReq" class="invalid">✗ Uppercase letter</span>
                    <span id="specialReq" class="invalid">✗ Special character</span>
                </div>
                
                <input type="password" id="confirm_password" placeholder="Confirm new password" onkeyup="validateMatch()">
                
                <button id="resetBtn" onclick="resetPassword()">Reset Password</button>
            </div>

            <script>
                let isPasswordValid = false;
                let doPasswordsMatch = false;
                
                function validatePassword() {{
                    const password = document.getElementById('password').value;
                    
                    const hasLength = password.length >= 8;
                    const hasUpper = /[A-Z]/.test(password);
                    const hasSpecial = /[!@#$%^&*(),.?":{{}}|<>]/.test(password);
                    
                    updateRequirement('lengthReq', hasLength);
                    updateRequirement('upperReq', hasUpper);
                    updateRequirement('specialReq', hasSpecial);
                    
                    isPasswordValid = hasLength && hasUpper && hasSpecial;
                    validateMatch();
                    updateButtonState();
                }}
                
                function updateRequirement(elementId, isValid) {{
                    const element = document.getElementById(elementId);
                    if (isValid) {{
                        element.innerHTML = '✓ ' + element.innerHTML.substring(2);
                        element.className = 'valid';
                    }} else {{
                        element.innerHTML = '✗ ' + element.innerHTML.substring(2);
                        element.className = 'invalid';
                    }}
                }}
                
                function validateMatch() {{
                    const password = document.getElementById('password').value;
                    const confirm = document.getElementById('confirm_password').value;
                    doPasswordsMatch = password === confirm && password.length > 0;
                    updateButtonState();
                }}
                
                function updateButtonState() {{
                    const btn = document.getElementById('resetBtn');
                    btn.disabled = !(isPasswordValid && doPasswordsMatch);
                }}
                
                async function resetPassword() {{
                    const password = document.getElementById('password').value;
                    const token = '{token}';
                    
                    const btn = document.getElementById('resetBtn');
                    const errorDiv = document.getElementById('error');
                    const formContainer = document.getElementById('formContainer');
                    
                    errorDiv.style.display = 'none';
                    
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner"></span> Resetting password...';
                    
                    try {{
                        const response = await fetch('/reset-password', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{
                                token: token,
                                new_password: password
                            }})
                        }});
                        
                        const data = await response.json();
                        
                        if (response.ok) {{
                            // Show clean success box with green button
                            formContainer.innerHTML = `
                                <div class="check-icon">✓</div>
                                <h2 style="text-align:center; color:#28a745;">Password Reset!</h2>
                                <div class="success-box">
                                    <div class="success-message">
                                        Your password has been successfully reset.
                                    </div>
                                    <a href="https://heartalert.netlify.app/#/login" class="login-button">
                                        Go to Login
                                    </a>
                                </div>
                            `;
                        }} else {{
                            errorDiv.textContent = data.detail || 'Failed to reset password. The link may have expired.';
                            errorDiv.style.display = 'block';
                            btn.disabled = false;
                            btn.innerHTML = 'Reset Password';
                        }}
                    }} catch (err) {{
                        errorDiv.textContent = 'Network error. Please check your connection and try again.';
                        errorDiv.style.display = 'block';
                        btn.disabled = false;
                        btn.innerHTML = 'Reset Password';
                    }}
                }}
            </script>
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
    check_prediction_limit(current_doctor, db)
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
    increment_prediction_count(current_doctor, db)
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
            "subscription_plan": doctor.subscription_plan,
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
                "subscription_plan": user.subscription_plan,
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
            "subscription_plan": assistant.subscription_plan,
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
        "created_at": doctor.created_at,
        "subscription_plan": doctor.subscription_plan,
        "subscription_status": doctor.subscription_status,
        "subscription_expires_at": doctor.subscription_expires_at,
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


# ========== SUPPORT TICKETS (Simplest Standard) ==========

class SupportTicketCreate(BaseModel):
    name: str
    email: str
    subject: str
    message: str

@app.post("/support/create")
async def create_support_ticket(
    ticket: SupportTicketCreate,
    db: Session = Depends(get_db)
):
    """Create a support ticket (works with or without login)"""
    
    # Try to get user info if logged in (check Authorization header)
    user_id = None
    try:
        auth_header = HTTPBearer()(None)
        token = auth_header.credentials
        if token:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
    except:
        pass
    
    new_ticket = models.SupportTicket(
        user_id=user_id,
        user_name=ticket.name,
        user_email=ticket.email,
        subject=ticket.subject,
        message=ticket.message,
        status="open"
    )
    
    db.add(new_ticket)
    db.commit()
    db.refresh(new_ticket)
    
    # Get admin emails
    admins = db.query(models.Doctor).filter(models.Doctor.role == 'admin').all()
    admin_emails = [admin.email for admin in admins] if admins else ["byazidmohamed21@gmail.com"]
    
    # Send email notification to admins
    for admin_email in admin_emails:
        send_email(
            to=admin_email,
            subject=f"New Support Ticket #{new_ticket.id}: {ticket.subject}",
            html=f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h3>New Support Ticket #{new_ticket.id}</h3>
                <p><strong>From:</strong> {ticket.name} ({ticket.email})</p>
                <p><strong>Subject:</strong> {ticket.subject}</p>
                <p><strong>Message:</strong></p>
                <p>{ticket.message}</p>
                <p><a href="{BACKEND_URL}/admin/tickets">View in Admin Dashboard</a></p>
            </body>
            </html>
            """
        )
    
    # Send confirmation to user
    send_email(
        to=ticket.email,
        subject="Heart Alert - We received your message",
        html=f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h3>Thank you for contacting us</h3>
            <p>Dear {ticket.name},</p>
            <p>We have received your message and will respond within 24-48 hours.</p>
            <p><strong>Your message:</strong> {ticket.message}</p>
            <p>Best regards,<br>Heart Alert Team</p>
        </body>
        </html>
        """
    )
    
    return {"message": "Ticket created", "ticket_id": new_ticket.id}


@app.get("/admin/tickets")
def get_all_tickets(
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Admin: Get all support tickets"""
    tickets = db.query(models.SupportTicket).order_by(
        desc(models.SupportTicket.created_at)
    ).all()
    
    return tickets


@app.post("/admin/tickets/{ticket_id}/reply")
def reply_to_ticket(
    ticket_id: int,
    request: dict,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Admin: Reply to a ticket"""
    
    ticket = db.query(models.SupportTicket).filter(
        models.SupportTicket.id == ticket_id
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    reply_message = request.get("message")
    new_status = request.get("status", "resolved")
    
    ticket.admin_reply = reply_message
    ticket.status = new_status
    ticket.updated_at = datetime.utcnow()
    db.commit()
    
    # Send email to user with admin's reply
    send_email(
        to=ticket.user_email,
        subject=f"Re: {ticket.subject} (Heart Alert Support)",
        html=f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h3>Reply to your support ticket #{ticket.id}</h3>
            <p><strong>Your message:</strong> {ticket.message}</p>
            <p><strong>Admin response:</strong></p>
            <p>{reply_message}</p>
            <p><strong>Status:</strong> {new_status}</p>
            <p>If you have further questions, please reply to this email.</p>
            <p>Best regards,<br>Heart Alert Support Team</p>
        </body>
        </html>
        """
    )
    
    return {"message": "Reply sent"}


@app.put("/admin/tickets/{ticket_id}/status")
def update_ticket_status(
    ticket_id: int,
    request: dict,
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Admin: Update ticket status only"""
    
    ticket = db.query(models.SupportTicket).filter(
        models.SupportTicket.id == ticket_id
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket.status = request.get("status", ticket.status)
    ticket.updated_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Status updated"}


@app.get("/my-tickets")
def get_my_tickets(
    current_user: models.Doctor = Depends(require_role(['doctor', 'assistant', 'admin'])),
    db: Session = Depends(get_db)
):
    """User: Get their own tickets"""
    tickets = db.query(models.SupportTicket).filter(
        models.SupportTicket.user_id == current_user.id
    ).order_by(desc(models.SupportTicket.created_at)).all()
    
    return tickets


# ========== DOCTOR REMOVE ASSISTANT ==========
@app.delete("/doctor/remove-assistant")
def doctor_remove_assistant(
    current_doctor: models.Doctor = Depends(require_role(['doctor'])),
    current_user: models.Doctor = Depends(require_status(['approved'])),
    db: Session = Depends(get_db)
):
    """Doctor removes their own assistant - no admin approval needed"""
    
    # Find assistant assigned to this doctor
    assistant = db.query(models.Doctor).filter(
        models.Doctor.assigned_to == current_doctor.id,
        models.Doctor.role == 'assistant'
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="No assistant found for this doctor")
    
    # Remove the assistant's assignment
    assistant.assigned_to = None
    assistant.role = 'pending'
    assistant.status = 'pending'
    
    db.commit()
    
    return {"message": "Assistant removed successfully"}

# ========== CONTACT SUPPORT ==========
class ContactSupportRequest(BaseModel):
    name: str
    email: str
    subject: str
    message: str


# ========== ADMIN STATS ==========
@app.get("/admin/stats")
def get_admin_stats(
    current_user: models.Doctor = Depends(require_role(['admin'])),
    db: Session = Depends(get_db)
):
    """Get system statistics for admin dashboard"""
    
    # User counts
    total_doctors = db.query(models.Doctor).filter(
        models.Doctor.role == 'doctor',
        models.Doctor.status == 'approved'
    ).count()
    
    total_assistants = db.query(models.Doctor).filter(
        models.Doctor.role == 'assistant',
        models.Doctor.status == 'approved'
    ).count()
    
    pending_doctors = db.query(models.Doctor).filter(
        models.Doctor.role == 'pending',
        models.Doctor.status == 'pending'
    ).count()
    
    total_users = db.query(models.Doctor).count()
    
    # Prediction counts
    total_predictions = db.query(models.Prediction).count()
    
    # Today's predictions
    today = datetime.utcnow().date()
    today_predictions = db.query(models.Prediction).filter(
        func.date(models.Prediction.created_at) == today
    ).count()
    
    # This week's predictions
    week_ago = datetime.utcnow() - timedelta(days=7)
    week_predictions = db.query(models.Prediction).filter(
        models.Prediction.created_at >= week_ago
    ).count()
    
    # Email verification rate
    verified_users = db.query(models.Doctor).filter(
        models.Doctor.email_verified == True
    ).count()
    verification_rate = (verified_users / total_users * 100) if total_users > 0 else 0
    
    # Pending assistant requests
    pending_requests = db.query(models.AssistantRequest).filter(
        models.AssistantRequest.status == 'pending'
    ).count()
    
    # Open support tickets
    open_tickets = db.query(models.SupportTicket).filter(
        models.SupportTicket.status == 'open'
    ).count()
    
    pro_users = db.query(models.Doctor).filter(
        models.Doctor.subscription_plan == 'pro',
        models.Doctor.subscription_status == 'active'
    ).count()
    
    hospital_users = db.query(models.Doctor).filter(
        models.Doctor.subscription_plan.in_(['hospital', 'hospital_pro']),
        models.Doctor.subscription_status == 'active'
    ).count()

    return {
        "doctors": total_doctors,
        "assistants": total_assistants,
        "pending_approvals": pending_doctors,
        "total_users": total_users,
        "verified_users": verified_users,
        "verification_rate": round(verification_rate, 1),
        "total_predictions": total_predictions,
        "today_predictions": today_predictions,
        "week_predictions": week_predictions,
        "pending_requests": pending_requests,
        "open_tickets": open_tickets,
        "pro_users": pro_users,
        "hospital_users": hospital_users,
    }


@app.post("/contact-support")
async def contact_support(
    request: ContactSupportRequest,
    db: Session = Depends(get_db)
):
    """Send a message to admin (no login required)"""
    
    # Get admin emails
    admins = db.query(models.Doctor).filter(
        models.Doctor.role == 'admin'
    ).all()
    
    admin_emails = [admin.email for admin in admins]
    
    if not admin_emails:
        raise HTTPException(status_code=500, detail="No admin found")
    
    # Send email to all admins
    email_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 40px;">
        <div style="max-width: 480px; margin: auto; background: white; border-radius: 12px; padding: 40px;">
            <h2 style="color: #7A9E7E;">Heart Alert - Support Request</h2>
            <p style="color: #444;"><strong>From:</strong> {request.name} ({request.email})</p>
            <p style="color: #444;"><strong>Subject:</strong> {request.subject}</p>
            <hr>
            <p style="color: #444;"><strong>Message:</strong></p>
            <p style="color: #444; background: #f9f9f9; padding: 16px; border-radius: 8px;">
                {request.message}
            </p>
            <p style="color: #888; font-size: 12px;">Reply to: {request.email}</p>
        </div>
    </body>
    </html>
    """
    
    for admin_email in admin_emails:
        send_email(
            to=admin_email,
            subject=f"Support Request: {request.subject}",
            html=email_body
        )
    
    # Also send confirmation to user
    send_email(
        to=request.email,
        subject="Heart Alert - We received your message",
        html=f"""
        <html>
        <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 40px;">
            <div style="max-width: 480px; margin: auto; background: white; border-radius: 12px; padding: 40px;">
                <h2 style="color: #7A9E7E;">Thank you for contacting us</h2>
                <p style="color: #444;">Dear {request.name},</p>
                <p style="color: #444;">We have received your message and will respond within 24-48 hours.</p>
                <p style="color: #444;"><strong>Your message:</strong></p>
                <p style="color: #444; background: #f9f9f9; padding: 16px; border-radius: 8px;">
                    {request.message}
                </p>
                <p style="color: #888; font-size: 12px;">Best regards,<br>Heart Alert Team</p>
            </div>
        </body>
        </html>
        """
    )
    
    return {"message": "Message sent successfully"}

# ========== SUBSCRIPTION SYSTEM ==========
import stripe
import secrets
from datetime import date, timedelta

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Helper function to check subscription limits
def check_prediction_limit(doctor: models.Doctor, db: Session):
    """Check if user can make a prediction based on their plan"""
    
    # Reset monthly counter if needed
    today = date.today()
    if doctor.last_prediction_reset != today:
        doctor.monthly_predictions_count = 0
        doctor.last_prediction_reset = today
        db.commit()
    
    # Get plan details
    plan = db.query(models.PricingPlan).filter(
        models.PricingPlan.name == doctor.subscription_plan
    ).first()
    
    if plan and plan.prediction_limit:
        if doctor.monthly_predictions_count >= plan.prediction_limit:
            raise HTTPException(
                status_code=403, 
                detail=f"Monthly prediction limit reached ({plan.prediction_limit}). Please upgrade to continue."
            )
    
    return True


def increment_prediction_count(doctor: models.Doctor, db: Session):
    """Increment prediction count after successful prediction"""
    doctor.monthly_predictions_count += 1
    db.commit()


# ========== PRICING PLANS ==========
@app.get("/pricing-plans")
def get_pricing_plans(db: Session = Depends(get_db)):
    """Get all pricing plans"""
    plans = db.query(models.PricingPlan).filter(
        models.PricingPlan.is_active == True
    ).order_by(models.PricingPlan.sort_order).all()
    
    return [
        {
            "id": p.id,
            "name": p.name,
            "display_name": p.display_name,
            "description": p.description,
            "price_cents": p.price_cents,
            "price_dollars": p.price_cents / 100,
            "interval_type": p.interval_type,
            "features": p.features,
            "doctor_limit": p.doctor_limit,
            "assistant_limit": p.assistant_limit,
            "prediction_limit": p.prediction_limit
        }
        for p in plans
    ]


# ========== CREATE CHECKOUT SESSION ==========
class CheckoutRequest(BaseModel):
    plan_name: str  # 'pro' or 'hospital'
    success_url: str
    cancel_url: str

@app.post("/create-checkout-session")
async def create_checkout_session(
    request: CheckoutRequest,
    current_user: models.Doctor = Depends(require_role(['doctor', 'hospital_admin'])),
    db: Session = Depends(get_db)
):
    """Create Stripe Checkout session for subscription"""
    
    # Get the plan
    plan = db.query(models.PricingPlan).filter(
        models.PricingPlan.name == request.plan_name
    ).first()
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    try:
        # Create or get Stripe customer
        customer_id = current_user.stripe_customer_id
        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=f"{current_user.first_name} {current_user.last_name}",
                metadata={"user_id": current_user.id}
            )
            customer_id = customer.id
            current_user.stripe_customer_id = customer_id
            db.commit()
        
        # Create or get Stripe price ID
        if not plan.stripe_price_id:
            price = stripe.Price.create(
                unit_amount=plan.price_cents,
                currency=plan.currency,
                recurring={"interval": plan.interval_type},
                product_data={"name": plan.display_name},
            )
            plan.stripe_price_id = price.id
            db.commit()
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
            mode="subscription" if plan.interval_type != "one_time" else "payment",
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            metadata={
                "user_id": str(current_user.id),
                "plan_name": plan.name
            }
        )
        
        # ✅ DEMO MODE: Immediately upgrade user to Pro (for testing)
        # ⚠️ Remove this line when webhook is working in production ⚠️
        current_user.subscription_plan = request.plan_name
        current_user.subscription_status = "active"
        current_user.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
        db.commit()
        print(f"✅ DEMO MODE: User {current_user.email} upgraded to {request.plan_name}")
        
        return {"session_url": checkout_session.url}
        
    except Exception as e:
        print(f"Stripe error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ========== WEBHOOK ==========
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events"""
    print("🔔 Webhook endpoint was called!")

    payload = await request.body()
    print(f"📦 Payload length: {len(payload)}")
    
    sig_header = request.headers.get("stripe-signature")
    print(f"🔑 Signature header: {sig_header[:20] if sig_header else 'None'}...")
    
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    print(f"🤫 Webhook secret exists: {bool(webhook_secret)}")
    
    if not webhook_secret:
        print("❌ Webhook secret not configured!")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        print(f"✅ Webhook verified: {event['type']}")
    except Exception as e:
        print(f"❌ Webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook")
    
    # Handle checkout completed
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print(f"📦 Session data: {session.get('id')}")
        
        user_id = int(session["metadata"]["user_id"])
        plan_name = session["metadata"]["plan_name"]
        
        print(f"👤 User ID: {user_id}, Plan: {plan_name}")
        
        user = db.query(models.Doctor).filter(models.Doctor.id == user_id).first()
        
        if user:
            print(f"✅ Found user: {user.email}")
            
            # Update user's subscription
            user.subscription_plan = plan_name
            user.subscription_status = "active"
            
            # Save Stripe customer ID if not already set
            if session.get("customer") and not user.stripe_customer_id:
                user.stripe_customer_id = session.get("customer")
                print(f"💳 Saved Stripe customer: {user.stripe_customer_id}")
            
            # CRITICAL: Commit user update FIRST
            db.commit()
            print(f"✅ User {user.email} updated to {plan_name}")
            
            # Get subscription details from Stripe
            if session.get("subscription"):
                try:
                    stripe_sub = stripe.Subscription.retrieve(session["subscription"])
                    print(f"📅 Subscription period: {stripe_sub.current_period_start} to {stripe_sub.current_period_end}")
                    
                    # Save to subscriptions table
                    sub = models.Subscription(
                        user_id=user.id,
                        stripe_subscription_id=session["subscription"],
                        plan_name=plan_name,
                        status="active",
                        current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start),
                        current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end)
                    )
                    db.add(sub)
                    db.commit()
                    print(f"✅ Subscription saved to DB")
                    
                except Exception as e:
                    print(f"❌ Error retrieving Stripe subscription: {e}")
            
            # Record payment
            if session.get("payment_intent"):
                payment = models.Payment(
                    user_id=user.id,
                    stripe_payment_intent_id=session.get("payment_intent"),
                    amount_cents=session["amount_total"],
                    currency=session["currency"],
                    status="succeeded"
                )
                db.add(payment)
                db.commit()
                print(f"✅ Payment recorded: {session['amount_total']} {session['currency']}")
            
        else:
            print(f"❌ User not found for ID: {user_id}")
    
    # Handle subscription updated
    elif event["type"] == "customer.subscription.updated":
        subscription_obj = event["data"]["object"]
        print(f"📅 Subscription updated: {subscription_obj['id']}")
        
        sub = db.query(models.Subscription).filter(
            models.Subscription.stripe_subscription_id == subscription_obj["id"]
        ).first()
        
        if sub:
            sub.status = subscription_obj["status"]
            sub.current_period_end = datetime.fromtimestamp(subscription_obj["current_period_end"])
            sub.cancel_at_period_end = subscription_obj["cancel_at_period_end"]
            
            # Update user's subscription status
            user = db.query(models.Doctor).filter(models.Doctor.id == sub.user_id).first()
            if user:
                user.subscription_status = subscription_obj["status"]
                if subscription_obj["status"] != "active":
                    user.subscription_plan = "freemium"
            
            db.commit()
            print(f"✅ Subscription updated for user: {user.email if user else 'Unknown'}")
    
    # Handle subscription deleted
    elif event["type"] == "customer.subscription.deleted":
        subscription_obj = event["data"]["object"]
        print(f"❌ Subscription deleted: {subscription_obj['id']}")
        
        sub = db.query(models.Subscription).filter(
            models.Subscription.stripe_subscription_id == subscription_obj["id"]
        ).first()
        
        if sub:
            sub.status = "canceled"
            user = db.query(models.Doctor).filter(models.Doctor.id == sub.user_id).first()
            if user:
                user.subscription_plan = "freemium"
                user.subscription_status = "canceled"
            db.commit()
            print(f"✅ Subscription canceled for user: {user.email if user else 'Unknown'}")
    
    return {"status": "success"}


# ========== HOSPITAL ADMIN ENDPOINTS ==========

@app.get("/hospital/my-doctors")
def get_hospital_doctors(
    current_user: models.Doctor = Depends(require_role(['hospital_admin'])),
    db: Session = Depends(get_db)
):
    """Hospital admin gets all linked doctors"""
    
    # Check if hospital subscription is active
    if current_user.subscription_status != "active":
        raise HTTPException(status_code=403, detail="Hospital subscription expired or inactive")
    
    doctors = db.query(models.HospitalDoctor).filter(
        models.HospitalDoctor.hospital_admin_id == current_user.id,
        models.HospitalDoctor.status == 'active'
    ).all()
    
    result = []
    for hd in doctors:
        doctor = db.query(models.Doctor).filter(models.Doctor.id == hd.doctor_id).first()
        if doctor:
            result.append({
                "id": doctor.id,
                "name": f"{doctor.first_name} {doctor.last_name}",
                "email": doctor.email,
                "joined_at": hd.accepted_at or hd.invited_at,
                "predictions_count": doctor.monthly_predictions_count
            })
    
    # Get plan details for limit
    plan = db.query(models.PricingPlan).filter(
        models.PricingPlan.name == current_user.subscription_plan
    ).first()
    
    return {
        "doctors": result,
        "current_count": len(result),
        "max_doctors": plan.doctor_limit if plan else 20,
        "subscription_end": current_user.subscription_expires_at
    }


@app.post("/hospital/invite-doctor")
async def invite_doctor(
    request: dict,
    current_user: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Invite a doctor to join the hospital"""
    
    doctor_email = request.get("email")
    if not doctor_email:
        raise HTTPException(status_code=400, detail="Email required")
    
    # Check subscription is hospital
    if current_user.subscription_plan != "hospital":
        raise HTTPException(status_code=403, detail="Hospital subscription required")
    
    # Check subscription active
    if current_user.subscription_status != "active":
        raise HTTPException(status_code=403, detail="Hospital subscription expired")
    
    # ========== CHECK FOR DUPLICATES ==========
    
    # 1. Check if doctor already exists and is linked to this hospital
    existing_doctor = db.query(models.Doctor).filter(
        models.Doctor.email == doctor_email
    ).first()
    
    if existing_doctor:
        # Check if already linked to this hospital
        already_linked = db.query(models.HospitalDoctor).filter(
            models.HospitalDoctor.hospital_admin_id == current_user.id,
            models.HospitalDoctor.doctor_id == existing_doctor.id
        ).first()
        
        if already_linked:
            raise HTTPException(status_code=400, detail="This doctor is already in your hospital")
    
    # 2. Check if there's already a pending invitation for this email
    existing_invitation = db.query(models.HospitalInvitation).filter(
        models.HospitalInvitation.hospital_admin_id == current_user.id,
        models.HospitalInvitation.doctor_email == doctor_email,
        models.HospitalInvitation.status == "pending"
    ).first()
    
    if existing_invitation:
        raise HTTPException(
            status_code=400, 
            detail=f"An invitation has already been sent to {doctor_email}. Please wait for them to respond or cancel the existing invitation."
        )
    
    # ========== PROCEED WITH NEW INVITATION ==========
    
    # Send invitation email
    token = secrets.token_urlsafe(32)
    invitation = models.HospitalInvitation(
        hospital_admin_id=current_user.id,
        doctor_email=doctor_email,
        token=token,
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    db.add(invitation)
    db.commit()
    
    # Create redirect link
    invite_link = f"{BACKEND_URL}/invite-redirect?token={token}"
    
    try:
        send_email(
            to=doctor_email,
            subject="Invitation to join Heart Alert Hospital Plan",
            html=f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="max-width: 480px; margin: auto; padding: 20px;">
                    <h2 style="color: #7A9E7E;">You've been invited!</h2>
                    <p>Dr. {current_user.first_name} {current_user.last_name} has invited you to join their hospital on Heart Alert.</p>
                    <p>You will get <strong>FREE Pro access</strong> under their hospital subscription.</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{invite_link}"
                           style="background-color: #7A9E7E; color: white; padding: 12px 24px;
                                  text-decoration: none; border-radius: 8px;">
                            Accept Invitation
                        </a>
                    </div>
                    <p style="color: #888; font-size: 12px;">This link expires in 7 days.</p>
                    <p style="color: #888; font-size: 12px;">If you already have an account, you will be prompted to login.</p>
                </div>
            </body>
            </html>
            """
        )
        print(f"✅ Invitation email sent to {doctor_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
    
    return {"message": f"Invitation sent to {doctor_email}"}


@app.delete("/hospital/remove-doctor/{doctor_id}")
def remove_hospital_doctor(
    doctor_id: int,
    current_user: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Remove a doctor from the hospital and revert to freemium"""
    
    if current_user.subscription_plan != "hospital":
        raise HTTPException(status_code=403, detail="Hospital subscription required")
    
    hospital_doctor = db.query(models.HospitalDoctor).filter(
        models.HospitalDoctor.hospital_admin_id == current_user.id,
        models.HospitalDoctor.doctor_id == doctor_id,
        models.HospitalDoctor.status == 'active'
    ).first()
    
    if not hospital_doctor:
        raise HTTPException(status_code=404, detail="Doctor not found in your hospital")
    
    # Remove the link
    hospital_doctor.status = 'removed'
    hospital_doctor.removed_at = datetime.utcnow()
    
    # Revert doctor to freemium
    doctor = db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()
    if doctor:
        doctor.subscription_plan = 'freemium'
        doctor.subscription_status = 'active'
    
    db.commit()
    
    return {"message": "Doctor removed and reverted to Freemium"}

# ========== USER SUBSCRIPTION STATUS ==========
@app.get("/my-subscription")
def get_my_subscription(
    current_user: models.Doctor = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's subscription details"""
    
    # Check if user is part of hospital
    hospital_link = db.query(models.HospitalDoctor).filter(
        models.HospitalDoctor.doctor_id == current_user.id,
        models.HospitalDoctor.status == 'active'
    ).first()
    
    is_hospital_linked = hospital_link is not None
    hospital_admin_name = None
    
    if is_hospital_linked:
        admin = db.query(models.Doctor).filter(
            models.Doctor.id == hospital_link.hospital_admin_id
        ).first()
        hospital_admin_name = f"{admin.first_name} {admin.last_name}" if admin else None
    
    # Get plan details
    plan = db.query(models.PricingPlan).filter(
        models.PricingPlan.name == current_user.subscription_plan
    ).first()
    
    return {
        "plan": current_user.subscription_plan,
        "status": current_user.subscription_status,
        "expires_at": current_user.subscription_expires_at,
        "is_hospital_linked": is_hospital_linked,
        "hospital_admin": hospital_admin_name,
        "monthly_predictions_used": current_user.monthly_predictions_count,
        "prediction_limit": plan.prediction_limit if plan else 15,
        "features": plan.features if plan else None
    }

    
@app.get("/hospital/stats")
def get_hospital_stats(
    current_user: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Get hospital statistics for the dashboard"""
    
    # Check if user has hospital subscription
    if current_user.subscription_plan != "hospital":
        raise HTTPException(status_code=403, detail="Hospital subscription required")
    
    # Get doctors count
    hospital_doctors = db.query(models.HospitalDoctor).filter(
        models.HospitalDoctor.hospital_admin_id == current_user.id,
        models.HospitalDoctor.status == 'active'
    ).count()
    
    return {
        "total_doctors": hospital_doctors,
        "total_patients": 0,
        "total_predictions": 0,
        "total_assistants": 0,
    }


@app.get("/hospital/doctors")
def get_hospital_doctors_list(
    current_user: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Get all doctors linked to this hospital"""
    
    if current_user.subscription_plan != "hospital":
        raise HTTPException(status_code=403, detail="Hospital subscription required")
    
    hospital_doctors = db.query(models.HospitalDoctor).filter(
        models.HospitalDoctor.hospital_admin_id == current_user.id,
        models.HospitalDoctor.status == 'active'
    ).all()
    
    result = []
    for hd in hospital_doctors:
        doctor = db.query(models.Doctor).filter(models.Doctor.id == hd.doctor_id).first()
        if doctor:
            result.append({
                "id": doctor.id,
                "name": f"Dr. {doctor.first_name} {doctor.last_name}",
                "first_name": doctor.first_name,
                "last_name": doctor.last_name,
                "email": doctor.email,
                "specialty": doctor.specialty or "General Practitioner",
                "status": "active"
            })
    
    return result


@app.get("/hospital/pending-invitations")
def get_pending_hospital_invitations(
    current_user: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Get pending invitations sent by this hospital"""
    
    if current_user.subscription_plan != "hospital":
        raise HTTPException(status_code=403, detail="Hospital subscription required")
    
    invitations = db.query(models.HospitalInvitation).filter(
        models.HospitalInvitation.hospital_admin_id == current_user.id,
        models.HospitalInvitation.status == "pending"
    ).all()
    
    return [
        {
            "id": inv.id,
            "email": inv.doctor_email,
            "name": "Pending Doctor",
            "specialty": "Pending",
            "status": inv.status,
            "created_at": inv.created_at
        }
        for inv in invitations
    ]


@app.delete("/hospital/cancel-invitation/{invitation_id}")
def cancel_hospital_invitation(
    invitation_id: int,
    current_user: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Cancel a pending invitation"""
    
    # Check if user has hospital subscription
    if current_user.subscription_plan != "hospital":
        raise HTTPException(status_code=403, detail="Hospital subscription required")
    
    # Find the invitation
    invitation = db.query(models.HospitalInvitation).filter(
        models.HospitalInvitation.id == invitation_id,
        models.HospitalInvitation.hospital_admin_id == current_user.id,
        models.HospitalInvitation.status == "pending"
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    # Delete the invitation
    db.delete(invitation)
    db.commit()
    
    return {"message": "Invitation cancelled successfully"}
# In main.py, update the invite_redirect endpoint

@app.get("/invite-redirect")
def invite_redirect(token: str, user_agent: Optional[str] = Header(None)):  # ✅ ADD Optional and default None
    """Redirect to the appropriate signup page based on device"""
    
    FRONTEND_URL = "https://heartalert.netlify.app"  # Your Netlify URL
    
    # ✅ FIX BUG 3: Handle None user_agent
    is_mobile = False
    if user_agent:
        user_agent_lower = user_agent.lower()
        is_mobile = any(device in user_agent_lower for device in ['android', 'ios', 'iphone', 'ipad', 'mobile'])
    
    print(f"📱 User-Agent: {user_agent}")
    print(f"📱 Is mobile: {is_mobile}")
    
    # Mobile: Use JavaScript redirect (works better than meta refresh)
    if is_mobile:
        deep_link = f"heartalert://signup?invite_token={token}"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Opening Heart Alert...</title>
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
                    text-align: center;
                }}
                .container {{
                    max-width: 300px;
                    padding: 20px;
                }}
                .logo {{
                    width: 80px;
                    height: 80px;
                    background: #7A9E7E;
                    border-radius: 20px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 20px;
                    font-size: 40px;
                }}
                h2 {{
                    color: #2C3E2F;
                    margin-bottom: 10px;
                }}
                p {{
                    color: #666;
                    line-height: 1.5;
                }}
                .button {{
                    display: inline-block;
                    background: #7A9E7E;
                    color: white;
                    padding: 12px 24px;
                    text-decoration: none;
                    border-radius: 8px;
                    margin-top: 20px;
                }}
                .fallback {{
                    margin-top: 30px;
                    font-size: 12px;
                    color: #999;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="logo">❤️</div>
                <h2>Heart Alert</h2>
                <p>Opening the app to complete your registration...</p>
                <a href="{deep_link}" class="button">Open App</a>
                <div class="fallback">
                    <p>Don't have the app? <a href="{FRONTEND_URL}/#/signup?invite_token={token}">Sign up on web</a></p>
                    <p style="margin-top: 10px;">Can't open the app? <a href="{FRONTEND_URL}/#/signup?invite_token={token}">Continue in browser</a></p>
                </div>
            </div>
            <script>
                // ✅ FIX BUG 4: Use JavaScript redirect instead of meta refresh
                window.location.href = "{deep_link}";
                
                // Fallback: if app doesn't open after 2.5 seconds, show web option
                setTimeout(function() {{
                    // User can click the web link manually
                    console.log("App didn't open, user can click web link");
                }}, 2500);
            </script>
        </body>
        </html>
        """
    else:
        # Web: Redirect to web signup page
        redirect_url = f"{FRONTEND_URL}/#/signup?invite_token={token}"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta http-equiv="refresh" content="0;url={redirect_url}">
            <title>Redirecting to Heart Alert...</title>
        </head>
        <body>
            <p>Redirecting to signup...</p>
            <p><a href="{redirect_url}">Click here if not redirected</a></p>
        </body>
        </html>
        """
    
    return HTMLResponse(content=html_content)

@app.post("/hospital/resend-invitation")
def resend_hospital_invitation(
    request: dict,
    current_user: models.Doctor = Depends(require_role(['doctor'])),
    db: Session = Depends(get_db)
):
    """Resend a pending invitation"""
    
    # Check if user has hospital subscription
    if current_user.subscription_plan != "hospital":
        raise HTTPException(status_code=403, detail="Hospital subscription required")
    
    invitation_id = request.get("invitation_id")
    if not invitation_id:
        raise HTTPException(status_code=400, detail="Invitation ID required")
    
    # Find the invitation
    invitation = db.query(models.HospitalInvitation).filter(
        models.HospitalInvitation.id == invitation_id,
        models.HospitalInvitation.hospital_admin_id == current_user.id,
        models.HospitalInvitation.status == "pending"
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    # Generate new token
    import secrets
    new_token = secrets.token_urlsafe(32)
    invitation.token = new_token
    invitation.expires_at = datetime.utcnow() + timedelta(days=7)
    db.commit()
    
    # Resend email
    invite_link = f"{BACKEND_URL}/invite-redirect?token={new_token}"
    
    try:
        send_email(
            to=invitation.doctor_email,
            subject="Invitation to join Heart Alert (Resent)",
            html=f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="max-width: 480px; margin: auto; padding: 20px;">
                    <h2 style="color: #7A9E7E;">You've been invited!</h2>
                    <p>This is a reminder to accept your invitation to join Heart Alert.</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{invite_link}"
                           style="background-color: #7A9E7E; color: white; padding: 12px 24px;
                                  text-decoration: none; border-radius: 8px;">
                            Accept Invitation
                        </a>
                    </div>
                    <p style="color: #888; font-size: 12px;">This link expires in 7 days.</p>
                </div>
            </body>
            </html>
            """
        )
        print(f"✅ Invitation resent to {invitation.doctor_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
    
    return {"message": "Invitation resent successfully"}


