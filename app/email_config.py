import resend
import os
from dotenv import load_dotenv

load_dotenv()

def send_email(to: str, subject: str, html: str):
    resend.api_key = os.getenv("RESEND_API_KEY")
    if not resend.api_key:
        raise Exception("RESEND_API_KEY is not set")
    return resend.Emails.send({
        "from": "Heart Alert <onboarding@resend.dev>",
        "to": [to],
        "subject": subject,
        "html": html
    })