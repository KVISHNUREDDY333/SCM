from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from backend.auth.jwt_handler import decodeJWT
from backend.config.database import user_collection, session_collection
import os
from dotenv import load_dotenv

load_dotenv()

# --- JWT Security ---
class JWTBearer(HTTPBearer):
    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super(JWTBearer, self).__call__(request)
        if credentials:
            if not credentials.scheme == "Bearer":
                raise HTTPException(status_code=403, detail="Invalid authentication scheme.")
            
            token = credentials.credentials
            
            # 1. Base JWT decoding and expiry check
            if not decodeJWT(token):
                raise HTTPException(status_code=403, detail="Invalid or expired token.")
            
            # 2. Stateful session check (Must exist in database)
            session = await session_collection.find_one({"access_token": token})
            if not session:
                raise HTTPException(status_code=403, detail="Session expired or logged out.")
            
            return token
        else:
            raise HTTPException(status_code=403, detail="Invalid authorization code.")

# --- Admin Security ---
class VerifyAdmin(JWTBearer):
    async def __call__(self, request: Request):
        token = await super(VerifyAdmin, self).__call__(request)
        decoded = decodeJWT(token)
        if not decoded:
             raise HTTPException(status_code=403, detail="Invalid or expired token.")
        
        user = await user_collection.find_one({"email": decoded["email"]})
        if not user or not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Access denied: Admin privileges required")
            
        return user

# --- IP Access Control Middleware ---
class IPAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.allowed_ips = os.getenv("ALLOWED_IPS", "*").split(",")

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        
        # Check if we should block
        if "*" not in self.allowed_ips:
            if client_ip not in self.allowed_ips:
                # You can log this unauthorized access attempt here
                print(f"Blocked connection attempt from IP: {client_ip}")
                raise HTTPException(status_code=403, detail="Access denied: IP not whitelisted")

        response = await call_next(request)
        return response