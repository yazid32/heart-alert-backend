import resend
import os
from dotenv import load_dotenv

load_dotenv()

def send_email(to: str, subject: str, html: str):
    api_key = os.environ.get("RESEND_API_KEY") or "re_ALbrQtBX_2DPuEpoJK5ze3bgEhszfD4am"
    print(f"🔑 Using key: {api_key[:8]}...")
    resend.api_key = api_key
    return resend.Emails.send({
        "from": "Heart Alert <onboarding@resend.dev>",
        "to": [to],
        "subject": subject,
        "html": html
    })