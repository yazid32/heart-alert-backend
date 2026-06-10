from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Date, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime

class Doctor(Base):
    __tablename__ = "doctors"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    license_number = Column(String)
    hospital = Column(String)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(String, nullable=True)
    
    # Add these new fields
    country = Column(String, nullable=True)
    specialty = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    reset_token = Column(String, nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    medical_license_path = Column(String, nullable=True)
    government_id_path = Column(String, nullable=True)
    terms_accepted = Column(Boolean, default=False)
    terms_accepted_at = Column(DateTime, nullable=True)
    
    # ========== FIELDS FOR ROLES ==========
    profile_picture = Column(String, nullable=True)
    role = Column(String, default='pending')
    status = Column(String, default='pending')
    assigned_to = Column(Integer, ForeignKey("doctors.id"), nullable=True, unique=True)
    
    # Relationships
    assistant_requests = relationship("AssistantRequest", back_populates="doctor")

    email_verified = Column(Boolean, default=False)
    email_verification_token = Column(String, nullable=True)
    email_verification_sent_at = Column(DateTime, nullable=True)


class AssistantRequest(Base):
    __tablename__ = "assistant_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    assistant_email = Column(String)
    assistant_name = Column(String)
    assistant_phone = Column(String, nullable=True)
    status = Column(String, default='pending')  # pending, approved, rejected
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    doctor = relationship("Doctor", back_populates="assistant_requests")


class Prediction(Base):
    __tablename__ = "predictions"
    assistant_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    
    # Patient parameters
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    age = Column(Integer)
    sex = Column(Integer)
    cp = Column(Integer)
    trestbps = Column(Integer)
    chol = Column(Integer)
    fbs = Column(Integer)
    restecg = Column(Integer)
    thalach = Column(Integer)
    exang = Column(Integer)
    oldpeak = Column(Float)
    slope = Column(Integer)
    
    # Prediction results
    risk_score = Column(Float)
    risk_category = Column(String)
    has_disease = Column(Boolean)
    
    # Metadata
    patient_name = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Patient(Base):
    __tablename__ = "patients"
    assistant_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    first_name = Column(String)
    last_name = Column(String)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    address = Column(String, nullable=True)
    medical_history = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())