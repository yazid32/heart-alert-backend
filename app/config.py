import os
from typing import List, Optional

class Config:
    """Application configuration with validation for Render.com"""
    
    # ✅ Required environment variables
    REQUIRED_ENV_VARS = [
        "JWT_SECRET_KEY",
        "DATABASE_URL",
    ]
    
    # ✅ Optional but recommended
    RECOMMENDED_ENV_VARS = [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "BREVO_API_KEY",
        "NUMLOOKUP_API_KEY",
        "BACKEND_URL",
    ]
    
    @classmethod
    def validate(cls):
        """Validate required environment variables are set"""
        missing = []
        for var in cls.REQUIRED_ENV_VARS:
            if not os.getenv(var):
                missing.append(var)
        
        if missing:
            # ⚠️ Log error but don't crash - useful for Render startup
            print(f"❌ ERROR: Missing required environment variables: {', '.join(missing)}")
            print(f"   Please add them in Render.com dashboard:")
            print(f"   https://dashboard.render.com/")
            # In production, you might want to raise an error
            # For Render, we'll let it continue but log prominently
            return False
        
        # ✅ Validate JWT_SECRET_KEY length
        jwt_key = os.getenv("JWT_SECRET_KEY")
        if jwt_key and len(jwt_key) < 32:
            print(f"⚠️  WARNING: JWT_SECRET_KEY is only {len(jwt_key)} characters long.")
            print("   Minimum recommended: 32 characters.")
        
        # ✅ Check for optional variables
        missing_recommended = []
        for var in cls.RECOMMENDED_ENV_VARS:
            if not os.getenv(var):
                missing_recommended.append(var)
        
        if missing_recommended:
            print(f"⚠️  Missing recommended environment variables:")
            print(f"   {', '.join(missing_recommended)}")
            print(f"   Some features may be disabled.")
        
        print("✅ Configuration validation complete")
        return True
    
    @classmethod
    def get_environment(cls) -> str:
        """Get current environment from Render"""
        # Render sets this automatically
        env = os.getenv("ENVIRONMENT", "development").lower()
        
        # Render also provides RENDER environment variable
        if os.getenv("RENDER"):
            # If on Render, default to production
            if env == "development":
                env = "production"
        
        return env
    
    @classmethod
    def is_production(cls) -> bool:
        return cls.get_environment() == "production"
    
    @classmethod
    def is_development(cls) -> bool:
        return cls.get_environment() == "development"

# ✅ Validate on import - but don't crash on Render
Config.validate()