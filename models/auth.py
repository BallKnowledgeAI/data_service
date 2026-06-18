from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from .enums import LicenseTier, LicenseStatus, UserRole


class Organization(BaseModel):
    org_id: str
    org_name: str
    license_tier: LicenseTier
    license_status: LicenseStatus
    license_expiry: datetime
    created_at: datetime


class User(BaseModel):
    user_id: str
    org_id: str
    username: str
    email: str
    password_hash: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None


class RefreshToken(BaseModel):
    token_id: str
    user_id: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool
