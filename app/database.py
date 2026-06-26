# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# ✅ Read database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    if os.getenv("RENDER"):
        # On Render but DATABASE_URL not set - critical error
        raise ValueError(
            "❌ DATABASE_URL is required on Render.com!\n"
            "Please add it in the Render dashboard:\n"
            "https://dashboard.render.com/"
        )
    else:
        # Local development fallback
        DATABASE_URL = "sqlite:///./heart_disease.db"
        print(f"⚠️  DATABASE_URL not set. Using SQLite for local development: {DATABASE_URL}")

# ✅ Parse DATABASE_URL to check for valid format (skip for SQLite)
if DATABASE_URL and not DATABASE_URL.startswith("sqlite"):
    if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg2://")):
        print(f"⚠️  DATABASE_URL format may be incorrect: {DATABASE_URL[:20]}...")
        print("   Expected format: postgresql://user:password@host:5432/database")

print("✅ Database configuration loaded")

# ✅ Configure connection pool
if DATABASE_URL.startswith("sqlite"):
    # SQLite configuration for local development
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    # PostgreSQL configuration for production
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=30,
    )

# Create session local
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()