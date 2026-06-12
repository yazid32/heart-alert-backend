import httpx
import os
from dotenv import load_dotenv

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("MAIL_FROM", "byazidmohamed21@gmail.com")
BREVO_SENDER_NAME = os.getenv("MAIL_FROM_NAME", "Heart Alert")

async def send_email(to: str, subject: str, html: str):
    """Send email using Brevo's HTTP API"""
    
    if not BREVO_API_KEY:
        print("❌ BREVO_API_KEY not set in environment variables")
        raise Exception("Email service not configured")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json",
            },
            json={
                "sender": {
                    "name": BREVO_SENDER_NAME,
                    "email": BREVO_SENDER_EMAIL
                },
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": html
            }
        )
        
        if response.status_code not in (200, 201):
            print(f"❌ Brevo API error: {response.status_code} - {response.text}")
            raise Exception(f"Failed to send email: {response.text}")
        
        print(f"✅ Email sent to {to}")
        return response.json()


# Sync wrapper for non-async endpoints
def send_email_sync(to: str, subject: str, html: str):
    """Sync wrapper for send_email"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(send_email(to, subject, html))