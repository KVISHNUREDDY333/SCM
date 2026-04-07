from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import re
class UserSchema(BaseModel):
    first_name: str = Field(..., min_length=2)
    last_name: str = Field(..., min_length=2)
    username: Optional[str] = Field(None, min_length=3)
    email: EmailStr = Field(...)
    # This definition allows any string as long as it is 3+ chars
    password: str = Field(..., min_length=3) 

    class Config:
        json_schema_extra = {
            "example": {
                "first_name": "SCM",
                "last_name": "Admin",
                "username": "scm_admin", 
                "email": "admin@scm.com",
                "password": "strongpassword"
            }
        }

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v):
        """
        Enforces password policy:
        - Min 8 characters
        - At least 1 Uppercase
        - At least 1 Digit
        - At least 1 Special Character (@$!%*?&)
        """
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')
        if not re.search(r'[@$!%*?&]', v):
            raise ValueError('Password must contain at least one special character (@$!%*?&)')
        return v
    
class UserLoginSchema(BaseModel):
    email: EmailStr = Field(...)
    password: str = Field(...)

class GoogleAuthSchema(BaseModel):
    id_token: str

class ForgotPasswordSchema(BaseModel):
    email: EmailStr

class VerifyOTPSchema(BaseModel):
    email: EmailStr
    otp: str

class ResetPasswordSchema(BaseModel):
    email: EmailStr
    otp: str
    new_password: str = Field(..., min_length=8)