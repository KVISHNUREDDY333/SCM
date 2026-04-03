import time
from typing import Dict
from jose import jwt
from dotenv import load_dotenv
import os

load_dotenv()

import secrets
# Use a dynamically generated secret key so that restarting the backend invalidates all existing sessions.
JWT_SECRET = secrets.token_hex(32)
JWT_ALGORITHM = os.getenv("ALGORITHM", "HS256")

def token_response(token: str):
    return {"access_token": token,
        "token_type": "bearer"}

def signJWT(user_id: str, email: str) -> Dict[str, str]:
    payload = {
        "user_id": user_id,
        "email": email,
        "expires": time.time() + 6000 # 100 minutes
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token_response(token)

def decodeJWT(token: str) -> dict:
    try:
        decoded_token = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return decoded_token if decoded_token["expires"] >= time.time() else None
    except:
        return None