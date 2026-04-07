from datetime import datetime, timedelta
from fastapi import APIRouter, Body, HTTPException, Depends, Request, Header, Response
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
    VerifyOTPSchema,
    ResetPasswordSchema
)
from backend.config.database import user_collection, otp_collection, session_collection
from backend.auth.jwt_handler import signJWT, decodeJWT
from backend.middleware.security import JWTBearer
from backend.config.limiter import limiter

# Helpers
from backend.auth.recaptcha import verify_recaptcha 
from backend.auth.google_verify import verify_google_token

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN_EMAILS = ["vishnukamasani3@gmail.com"]

# ---------- EMAIL VALIDATION HELPER ----------
import re
def is_valid_email(email: str) -> bool:
    """Verifies that an email is a strictly formatted Gmail address."""
    # Enforce strict Gmail only policy
    if not email.lower().endswith("@gmail.com"):
        return False
    
    regex = r'^[a-zA-Z0-9+_.-]+@gmail\.com$'
    return re.match(regex, email.lower()) is not None

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

# ---------- CONCURRENT SESSION MANAGEMENT ----------
async def manage_user_sessions(user_id: str, email: str, access_token: str):
    """
    Enforces a strict limit of 5 concurrent active sessions per user account.
    If the threshold is exceeded, the oldest session is automatically purged (FIFO).
    """
    sessions = await session_collection.find({"user_id": user_id}).sort("created_at", 1).to_list(None)
    
    if len(sessions) >= 5:
        # Evict oldest session to maintain the 5-login cap
        await session_collection.delete_one({"_id": sessions[0]["_id"]})

    # Record the new session registry
    await session_collection.insert_one({
        "access_token": access_token,
        "email": email,
        "user_id": user_id,
        "created_at": datetime.now()
    })


# --- 1. SIGNUP ROUTE ---
@router.post("/signup")
@limiter.limit("5/minute") 
async def create_user(request: Request, response: Response, users: UserSchema = Body(...)):
    # 1. Strict Format Validation (Google Protocol)
    if not is_valid_email(users.email):
        raise HTTPException(status_code=400, detail="Only verified Google accounts (@gmail.com) are accepted for registration.")

    # 2. Duplicate Check
    if await user_collection.find_one({"email": users.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = pwd_context.hash(users.password)
    
    # Create User Dictionary
    user_dict = {
        "first_name": users.first_name,
        "last_name": users.last_name,
        "username": f"{users.first_name} {users.last_name}", # Combined name
        "email": users.email,
        "password": hashed_password,
        "auth_provider": "local",
        "last_login": datetime.now().isoformat(),
        "is_admin": users.email in ADMIN_EMAILS,
        "role": "admin" if users.email in ADMIN_EMAILS else "user"
    }
    
    # Save to DB
    new_user = await user_collection.insert_one(user_dict)
    resp = signJWT(str(new_user.inserted_id), users.email)
    
    # Register and Manage Concurrent Sessions (Limit: 5)
    await manage_user_sessions(str(new_user.inserted_id), users.email, resp["access_token"])
    
    # Set Cookie for SSE
    response.set_cookie(key="scm_token", value=resp["access_token"], httponly=True, samesite="lax")
    
    return resp

# --- 2. LOGIN ROUTE ---
@router.post("/token")
@limiter.limit("10/minute")
async def login(
    request: Request, 
    response: Response,
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
        
        resp = signJWT(str(user["_id"]), user["email"])
        
        # Register and Manage Concurrent Sessions (Limit: 5)
        await manage_user_sessions(str(user["_id"]), user["email"], resp["access_token"])
        
        # Set Cookie for SSE
        response.set_cookie(key="scm_token", value=resp["access_token"], httponly=True, samesite="lax")
        
        return resp
    
    raise HTTPException(status_code=401, detail="Invalid login details")

# --- 3. GOOGLE AUTH ROUTE ---
@router.post("/auth/google")
@limiter.limit("20/minute")
async def google_login(request: Request, response: Response, payload: GoogleAuthSchema):
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
            "last_login": current_time,
            "is_admin": email in ADMIN_EMAILS,
            "role": "admin" if email in ADMIN_EMAILS else "user"
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

    resp = signJWT(user_id, email)
    
    # Register and Manage Concurrent Sessions (Limit: 5)
    await manage_user_sessions(user_id, email, resp["access_token"])
    
    # Set Cookie for SSE
    response.set_cookie(key="scm_token", value=resp["access_token"], httponly=True, samesite="lax")
    
    return resp

# --- 3.5 VERIFY GOOGLE EMAIL ROUTE (DEEP IDENTITY PROBE) ---
import smtplib
import socket

@router.get("/auth/verify-google-email")
async def verify_google_email(email: str):
    """Deep inspection: Performs an SMTP handshake with Google's database to verify existence."""
    if not is_valid_email(email):
         raise HTTPException(status_code=400, detail="Invalid format. Only @gmail.com accounts are accepted.")
    
    # Deep Verification: RCPT Handshake with Google's MX cluster
    try:
        # Use a timeout to ensure real-time responsiveness
        server = smtplib.SMTP(timeout=5) 
        server.connect('gmail-smtp-in.l.google.com')
        server.helo()
        server.mail('verify@scmxpertlite.com')
        code, _ = server.rcpt(email)
        server.quit()
        
        # 250 = Active Google Identity confirmed in database
        if code == 250:
            return {"message": "Google Identity Verified", "verified": True}
        else:
            raise HTTPException(status_code=400, detail="This email is not a registered Google account. Please use a valid, active Gmail.")
    except (smtplib.SMTPConnectError, socket.error):
        # Fallback for isolated environments where Port 25 is restricted by ISP/Firewall
        # If we can't reach the server, we respect the format but log the link failure
        print(f"CRITICAL: Link failure to Google MX cluster for {email} verification.")
        return {"message": "Identity format verified (Offline link to Google)", "verified": True}
    except Exception as e:
        print(f"Deep verify error: {e}")
        raise HTTPException(status_code=400, detail="System link failed. Please retry verification.")

# --- 4. PASSWORD RESET LOGIC ---
def generate_otp():
    return str(random.randint(100000, 999999))

@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordSchema):
    # 1. Check if user exists
    user = await user_collection.find_one({"email": payload.email})
    if not user:
        raise HTTPException(status_code=404, detail="Please enter a registered email.")

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
    

@router.post("/validate-otp")
async def validate_otp(payload: VerifyOTPSchema):
    # 1. Find OTP record
    record = await otp_collection.find_one({"email": payload.email})
    
    if not record:
        raise HTTPException(status_code=400, detail="Invalid request or OTP expired")
    
    # 2. Verify OTP and Expiration
    if record["otp"] != payload.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    now_utc = datetime.utcnow().replace(tzinfo=None)
    db_expires_at = record["expires_at"].replace(tzinfo=None)

    if now_utc > db_expires_at:
        raise HTTPException(status_code=400, detail="OTP Expired")

    return {"message": "OTP Verified Successfully", "valid": True}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordSchema):
    # 1. Find OTP record
    record = await otp_collection.find_one({"email": payload.email})
    
    if not record:
        raise HTTPException(status_code=400, detail="Invalid request or OTP expired")
    
    # 2. Verify OTP and Expiration
    if record["otp"] != payload.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    # Strip timezone info to safely support both offset-naive and aware PyMongo dates
    now_utc = datetime.utcnow().replace(tzinfo=None)
    db_expires_at = record["expires_at"].replace(tzinfo=None)

    if now_utc > db_expires_at:
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
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "email": user["email"],
            "last_login": user.get("last_login"),
            "is_admin": user.get("is_admin", False),
            "role": user.get("role", "user")
        }
    raise HTTPException(status_code=404, detail="User not found")
# --- 6. UPDATE PROFILE ---
@router.put("/me", dependencies=[Depends(JWTBearer())])
async def update_profile(
    payload: dict = Body(...),
    token: str = Depends(JWTBearer())
):
    decoded = decodeJWT(token)
    email = decoded["email"]
    
    # Allowed fields
    update_data = {}
    if "first_name" in payload: update_data["first_name"] = payload["first_name"]
    if "last_name" in payload: update_data["last_name"] = payload["last_name"]
    
    # Auto-update username if first/last name changed
    if "first_name" in payload or "last_name" in payload:
        user = await user_collection.find_one({"email": email})
        fname = payload.get("first_name", user.get("first_name", ""))
        lname = payload.get("last_name", user.get("last_name", ""))
        update_data["username"] = f"{fname} {lname}".strip()

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    result = await user_collection.update_one(
        {"email": email},
        {"$set": update_data}
    )
    
    if result.modified_count > 0:
        return {"message": "Profile updated successfully", "username": update_data.get("username")}
    
    return {"message": "No changes made."}

# --- 7. LOGOUT ROUTE ---
@router.post("/logout", dependencies=[Depends(JWTBearer())])
async def logout(token: str = Depends(JWTBearer())):
    # Delete session from DB
    await session_collection.delete_one({"access_token": token})
    return {"message": "Logged out successfully"}
