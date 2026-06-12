import resend
import os
from dotenv import load_dotenv

load_dotenv()

def send_email(to: str, subject: str, html: str):
    api_key = os.getenv("re_ALbrQtBX_2DPuEpoJK5ze3bgEhszfD4am")
    print(f"🔑 RESEND_API_KEY value: {'SET ('+str(len(api_key))+' chars)' if api_key else 'NOT SET'}")
    print(f"🔑 All env vars with RESEND: {[k for k in os.environ.keys() if 'RESEND' in k]}")
    resend.api_key = api_key
    if not resend.api_key:
        raise Exception("RESEND_API_KEY is not set")
    return resend.Emails.send({
        "from": "Heart Alert <onboarding@resend.dev>",
        "to": [to],
        "subject": subject,
        "html": html
    })