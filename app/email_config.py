import os
import requests
from dotenv import load_dotenv

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("MAIL_FROM", "byazidmohamed21@gmail.com")
BREVO_SENDER_NAME = os.getenv("MAIL_FROM_NAME", "Heart Alert")

def send_email(to: str, subject: str, html: str):
    """Send email using Brevo's HTTP API"""
    
    if not BREVO_API_KEY:
        print("❌ BREVO_API_KEY not set")
        print("Add BREVO_API_KEY to Render environment variables")
        return
    
    url = "https://api.brevo.com/v3/smtp/email"
    
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }
    
    data = {
        "sender": {
            "name": BREVO_SENDER_NAME,
            "email": BREVO_SENDER_EMAIL
        },
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        if response.status_code in (200, 201):
            print(f"✅ Email sent to {to}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
            raise Exception(f"Email failed: {response.text}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        raise