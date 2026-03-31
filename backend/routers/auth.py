"""Auth Router — /api/auth  (JWT + Supabase-ready)"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import jwt, os

router  = APIRouter()
bearer  = HTTPBearer()
SECRET  = os.getenv("JWT_SECRET", "takshvi-trade-secret-change-in-prod")
ALGO    = "HS256"

# ── Plans ────────────────────────────────────────────────────
PLANS = {
    "free":  {"signals_per_day": 3,  "delay_min": 15, "whatsapp": False},
    "basic": {"signals_per_day": -1, "delay_min": 0,  "whatsapp": True},
    "pro":   {"signals_per_day": -1, "delay_min": 0,  "whatsapp": True, "fno": True},
    "elite": {"signals_per_day": -1, "delay_min": 0,  "whatsapp": True, "fno": True, "api": True},
}

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class RegisterRequest(BaseModel):
    email:    EmailStr
    password: str
    name:     str

def create_token(user_id: str, plan: str = "free") -> str:
    payload = {
        "sub":  user_id,
        "plan": plan,
        "exp":  datetime.utcnow() + timedelta(days=30),
        "iat":  datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=[ALGO])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/register")
def register(body: RegisterRequest):
    # In production: save to Supabase
    token = create_token(body.email, plan="free")
    return {
        "token":   token,
        "user":    {"email": body.email, "name": body.name, "plan": "free"},
        "message": "Registration successful",
    }

@router.post("/login")
def login(body: LoginRequest):
    # In production: verify against Supabase
    token = create_token(body.email, plan="free")
    return {
        "token": token,
        "user":  {"email": body.email, "plan": "free"},
    }

@router.get("/me")
def me(user = Depends(verify_token)):
    plan_info = PLANS.get(user.get("plan", "free"), PLANS["free"])
    return {
        "user_id":  user["sub"],
        "plan":     user.get("plan", "free"),
        "features": plan_info,
    }

@router.get("/plans")
def get_plans():
    return {
        "free":  {"price": 0,    "currency": "INR", "period": "month", **PLANS["free"]},
        "basic": {"price": 299,  "currency": "INR", "period": "month", **PLANS["basic"]},
        "pro":   {"price": 799,  "currency": "INR", "period": "month", **PLANS["pro"]},
        "elite": {"price": 1999, "currency": "INR", "period": "month", **PLANS["elite"]},
    }
