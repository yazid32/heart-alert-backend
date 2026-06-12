import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

def send_email(to: str, subject: str, html: str):
    sender = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Heart Alert <{sender}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))
    
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, to, msg.as_string())