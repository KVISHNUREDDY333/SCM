from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from backend.auth.jwt_handler import decodeJWT
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
            if not decodeJWT(credentials.credentials):
                raise HTTPException(status_code=403, detail="Invalid or expired token.")
            return credentials.credentials
        else:
            raise HTTPException(status_code=403, detail="Invalid authorization code.")

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