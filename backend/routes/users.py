from datetime import datetime, timedelta
from fastapi import APIRouter, Body, HTTPException, Depends, Request, Header
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
import secrets
import random
import os
import smtplib
from email.mime.text import MIMEText

# Models & Config
from backend.models.user import (
    UserSchema, 
    GoogleAuthSchema, 
    ForgotPasswordSchema, 
    ResetPasswordSchema
)
from backend.config.database import user_collection, otp_collection
from backend.auth.jwt_handler import signJWT, decodeJWT
from backend.middleware.security import JWTBearer
from backend.config.limiter import limiter

# Helpers
from backend.auth.recaptcha import verify_recaptcha 
from backend.auth.google_verify import verify_google_token

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------- EMAIL HELPER FOR OTP ----------
def send_otp_email(recipient_email: str, otp: str) -> None:
    """
    Sends the OTP to the user's email using SMTP.
    Uses env vars:
      - MAIL_USER
      - MAIL_PASS
      - MAIL_SERVER
      - MAIL_PORT
    """
    sender_email = os.getenv("MAIL_USER")
    sender_password = os.getenv("MAIL_PASS")
    smtp_server = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("MAIL_PORT", "587"))

    subject = "Your SCMXpertLite Password Reset OTP"
    body = (
        f"Hello,\n\n"
        f"Your OTP for resetting your SCMXpertLite password is: {otp}\n\n"
        f"This code is valid for 5 minutes.\n"
        f"If you did not request this, you can ignore this email.\n\n"
        f"Regards,\nSCMXpertLite"
    )

    # If email config is missing, fall back to printing so app still works
    if not sender_email or not sender_password:
        print("\n" + "=" * 40)
        print(" EMAIL CONFIG NOT SET - FALLBACK TO CONSOLE ")
        print(f" To: {recipient_email}")
        print(f" OTP: {otp}")
        print("=" * 40 + "\n")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            print(f"OTP email sent to {recipient_email}")
    except smtplib.SMTPAuthenticationError as e:
        # Bad credentials: log and fallback to console, do NOT crash the API
        print("\n" + "=" * 40)
        print(" SMTP AUTHENTICATION ERROR ")
        print(e)
        print(f" Fallback OTP for {recipient_email}: {otp}")
        print("=" * 40 + "\n")
    except Exception as e:
        # Any other SMTP error
        print("\n" + "=" * 40)
        print(" SMTP ERROR WHILE SENDING OTP ")
        print(e)
        print(f" Fallback OTP for {recipient_email}: {otp}")
        print("=" * 40 + "\n")


# --- 1. SIGNUP ROUTE ---
@router.post("/signup")
@limiter.limit("5/minute") 
async def create_user(request: Request, users: UserSchema = Body(...)):
    # Check if user exists
    if await user_collection.find_one({"email": users.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = pwd_context.hash(users.password)
    
    # Create User Dictionary
    user_dict = {
        "username": users.username, # Saves the username provided at signup
        "email": users.email,
        "password": hashed_password,
        "auth_provider": "local",
        "last_login": datetime.now().isoformat() # FIX: Set initial login time
    }
    
    # Save to DB
    new_user = await user_collection.insert_one(user_dict)
    return signJWT(str(new_user.inserted_id), users.email)

# --- 2. LOGIN ROUTE ---
@router.post("/token")
@limiter.limit("10/minute")
async def login(
    request: Request, 
    form_data: OAuth2PasswordRequestForm = Depends(),
    x_recaptcha_token: str = Header(None) 
):
    # A. Verify ReCAPTCHA
    if not x_recaptcha_token:
         raise HTTPException(status_code=400, detail="ReCAPTCHA is missing.")
    
    is_valid_captcha = verify_recaptcha(x_recaptcha_token)
    if not is_valid_captcha:
        raise HTTPException(status_code=400, detail="Invalid ReCAPTCHA. Are you a robot?")

    # B. Standard Login Logic
    user = await user_collection.find_one({"email": form_data.username})
    if user and pwd_context.verify(form_data.password, user["password"]):
        
        # FIX: Update Last Login Time
        await user_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_login": datetime.now().isoformat()}}
        )
        
        return signJWT(str(user["_id"]), user["email"])
    
    raise HTTPException(status_code=401, detail="Invalid login details")

# --- 3. GOOGLE AUTH ROUTE ---
@router.post("/auth/google")
@limiter.limit("20/minute")
async def google_login(request: Request, payload: GoogleAuthSchema):
    google_data = verify_google_token(payload.id_token)
    
    if not google_data:
        raise HTTPException(status_code=400, detail="Invalid Google Token")

    email = google_data.get("email")
    user = await user_collection.find_one({"email": email})
    
    current_time = datetime.now().isoformat() # Get current time
    
    if not user:
        # Auto-register if not found
        random_password = secrets.token_urlsafe(16)
        hashed_password = pwd_context.hash(random_password)
        
        # Use Google name or fallback to email prefix
        username_from_google = google_data.get("name")
        if not username_from_google:
             username_from_google = email.split("@")[0]

        new_user_dict = {
            "username": username_from_google,
            "email": email,
            "password": hashed_password,
            "auth_provider": "google",
            "last_login": current_time # FIX: Set time for new Google user
        }
        
        new_user = await user_collection.insert_one(new_user_dict)
        user_id = str(new_user.inserted_id)
    else:
        # User exists, update last_login
        await user_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_login": current_time}} # FIX: Update time for existing Google user
        )
        user_id = str(user["_id"])

    return signJWT(user_id, email)

# --- 4. PASSWORD RESET LOGIC ---
def generate_otp():
    return str(random.randint(100000, 999999))

@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordSchema):
    # 1. Check if user exists
    user = await user_collection.find_one({"email": payload.email})
    if not user:
        # Do not reveal whether email exists
        return {"message": "If email exists, OTP sent."}

    # 2. Generate OTP
    otp = generate_otp()

    # 3. Save to DB with expiration (5 minutes)
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    # 🔹 IMPORTANT: remove any old OTPs for this email
    await otp_collection.delete_many({"email": payload.email})

    await otp_collection.insert_one({
        "email": payload.email,
        "otp": otp,
        "expires_at": expires_at
    })

    # 4. Send email
    send_otp_email(payload.email, otp)

    return {"message": "OTP sent to email"}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordSchema):
    # 1. Find OTP record
    record = await otp_collection.find_one({"email": payload.email})
    
    if not record:
        raise HTTPException(status_code=400, detail="Invalid request or OTP expired")
    
    # 2. Verify OTP and Expiration
    if record["otp"] != payload.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="OTP Expired")

    # 3. Hash new password
    hashed_password = pwd_context.hash(payload.new_password)

    # 4. Update User Password
    await user_collection.update_one(
        {"email": payload.email},
        {"$set": {"password": hashed_password}}
    )

    # 5. Cleanup OTP
    await otp_collection.delete_one({"_id": record["_id"]})

    return {"message": "Password updated successfully"}

# --- 5. GET CURRENT USER ---
@router.get("/me", dependencies=[Depends(JWTBearer())])
async def get_current_user(token: str = Depends(JWTBearer())):
    decoded = decodeJWT(token)
    user = await user_collection.find_one({"email": decoded["email"]})
    if user:
        return {
            "id": str(user["_id"]),
            "username": user.get("username"), 
            "email": user["email"],
            "last_login": user.get("last_login") 
        }
    raise HTTPException(status_code=404, detail="User not found")
