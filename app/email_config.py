import httpx
import os
from dotenv import load_dotenv
import asyncio
import nest_asyncio

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("MAIL_FROM", "byazidmohamed21@gmail.com")
BREVO_SENDER_NAME = os.getenv("MAIL_FROM_NAME", "Heart Alert")

async def send_email_async(to: str, subject: str, html: str):
    """Send email using Brevo's HTTP API (async version)"""
    
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


def send_email_sync(to: str, subject: str, html: str):
    """Sync wrapper for send_email_async - for use in regular def endpoints"""
    return asyncio.run(send_email_async(to, subject, html))


# Alias for backward compatibility
send_email = send_email_sync