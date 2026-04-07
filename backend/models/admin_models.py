from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
import datetime
import uuid

class UserUpdateSchema(BaseModel):
    first_name: Optional[str] = Field(None, min_length=2)
    last_name: Optional[str] = Field(None, min_length=2)
    username: Optional[str] = Field(None, min_length=3)
    is_admin: Optional[bool] = None
    role: Optional[str] = None

class AuditLogSchema(BaseModel):
    admin_email: str
    action: str
    details: str
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)

class BroadcastSchema(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str
    admin_email: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    expires_at: datetime.datetime

class MaintenanceSchema(BaseModel):
    is_active: bool = False
    message: Optional[str] = "System is currently under maintenance. Please check back later."
    bypass_ips: Optional[list[str]] = []

class DirectMessageSchema(BaseModel):
    recipient_email: str
    title: str
    message: str
    sender_email: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    is_read: bool = False
