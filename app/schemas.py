from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
from enum import Enum
class HeartDiseaseInput(BaseModel):
    patient_id: Optional[int] = None
    patient_name: Optional[str] = None
    age: int
    sex: int
    cp: int
    trestbps: int
    chol: int
    fbs: int
    restecg: int
    thalach: int
    exang: int
    oldpeak: float
    slope: int

class PredictionResponse(BaseModel):
    id: int
    doctor_id: int
    age: int
    sex: int
    cp: int
    trestbps: int
    chol: int
    fbs: int
    restecg: int
    thalach: int
    exang: int
    oldpeak: float
    slope: int
    risk_score: float
    risk_category: str
    has_disease: bool
    patient_name: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

class PredictionListResponse(BaseModel):
    total: int
    predictions: list[PredictionResponse]

class DoctorSignup(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    license_number: Optional[str] = None  # ← Change to Optional
    hospital: Optional[str] = None  # ← Change to Optional
    country: Optional[str] = None
    specialty: Optional[str] = None
    phone: Optional[str] = None
    medical_license_path: Optional[str] = None
    government_id_path: Optional[str] = None
    terms_accepted: Optional[bool] = False
    role: Optional[str] = 'pending'
    assigned_to: Optional[int] = None

class DoctorLogin(BaseModel):
    email: str
    password: str
    remember_me: bool = False

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    doctor_id: int
    email: str
    first_name: str
    last_name: str
    profile_picture: Optional[str] = None  # ← Add this

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    hospital: Optional[str] = None
    specialty: Optional[str] = None
    country: Optional[str] = None  # ADD THIS

class ProfileResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    license_number: Optional[str] = None
    hospital: Optional[str] = None
    specialty: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None  # ADD THIS LINE
    profile_picture: Optional[str] = None
    is_verified: bool
    created_at: datetime

class PatientBase(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    medical_history: Optional[str] = None
    notes: Optional[str] = None

class PatientCreate(PatientBase):
    pass

class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    medical_history: Optional[str] = None
    notes: Optional[str] = None

class PatientResponse(PatientBase):
    id: int
    doctor_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

class PatientListResponse(BaseModel):
    total: int
    patients: List[PatientResponse]

    # Add these to existing schemas.py

class UserRole(str, Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"
    ASSISTANT = "assistant"
    PENDING = "pending"

class UserStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    SUSPENDED = "suspended"

class DoctorUpdateRole(BaseModel):
    role: UserRole
    status: UserStatus
    assigned_to: Optional[int] = None

class AssistantInfo(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    assigned_to: Optional[int] = None

class AssistantSignup(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    government_id_path: Optional[str] = None
    terms_accepted: Optional[bool] = False
    role: str = 'pending'  # Will be changed to assistant by admin

class SendVerificationEmailRequest(BaseModel):
    email: str

class VerifyEmailRequest(BaseModel):
    token: str

class EmailVerificationResponse(BaseModel):
    verified: bool
    message: str