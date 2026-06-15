from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Date, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime
import stripe
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
    # Add to Doctor class
    subscription_plan = Column(String(50), default="freemium")
    subscription_status = Column(String(50), default="active")
    subscription_expires_at = Column(DateTime, nullable=True)
    stripe_customer_id = Column(String(255), nullable=True)
    monthly_predictions_count = Column(Integer, default=0)
    last_prediction_reset = Column(Date, nullable=True)


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

class SupportTicket(Base):
    __tablename__ = "support_tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # null if not logged in
    user_name = Column(String, nullable=False)
    user_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String, default="open")  # open, in_progress, resolved, closed
    admin_reply = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Add these new models
class PricingPlan(Base):
    __tablename__ = "pricing_plans"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, nullable=False)
    currency = Column(String(3), default="usd")
    interval_type = Column(String(20), nullable=False)
    stripe_price_id = Column(String(255), nullable=True)
    features = Column(JSON, nullable=True)
    doctor_limit = Column(Integer, default=1)
    assistant_limit = Column(Integer, default=0)
    prediction_limit = Column(Integer, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    stripe_subscription_id = Column(String(255), nullable=True)
    plan_name = Column(String(50), nullable=True)
    status = Column(String(50), default="active")
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("Doctor", backref="subscriptions")


class HospitalDoctor(Base):
    __tablename__ = "hospital_doctors"
    
    id = Column(Integer, primary_key=True)
    hospital_admin_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    status = Column(String(50), default="active")
    invited_at = Column(DateTime, default=datetime.utcnow)
    accepted_at = Column(DateTime, nullable=True)
    removed_at = Column(DateTime, nullable=True)


class HospitalInvitation(Base):
    __tablename__ = "hospital_invitations"
    
    id = Column(Integer, primary_key=True)
    hospital_admin_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    doctor_email = Column(String(255), nullable=False)
    token = Column(String(255), unique=True, nullable=False)
    status = Column(String(50), default="pending")
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    stripe_payment_intent_id = Column(String(255), nullable=True)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String(3), default="usd")
    status = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)