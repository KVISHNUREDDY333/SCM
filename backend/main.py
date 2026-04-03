from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from fastapi.responses import RedirectResponse
from backend.config.database import settings_collection
import os
import datetime

# Rate Limit Imports
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from backend.config.limiter import limiter

# Security Middleware
from backend.middleware.security import IPAccessMiddleware

# Import Routes
from backend.routes import users, shipments, stream, admin
# Recaptcha ConfigS
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY") # Load from .env
load_dotenv()

app = FastAPI()

# --- 0. Maintenance Middleware ---
@app.middleware("http")
async def maintenance_check(request: Request, call_next):
    # Skip for static, login, and admin actions (so we can turn it off)
    bypass_paths = ["/static", "/maintenance", "/api/v1/token", "/api/v1/admin", "/admin", "/api/v1/auth"]
    if any(request.url.path.startswith(p) for p in bypass_paths) or request.url.path == "/":
        return await call_next(request)

    config = await settings_collection.find_one({"key": "maintenance_config"})
    if config and config.get("value", {}).get("is_active"):
        return RedirectResponse(url="/maintenance")
        
    return await call_next(request)

# --- 1. Rate Limiter Configuration ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# --- 2. Security Middleware (IP Access) ---
# Note: Middleware runs in reverse order of addition. 
# We want IP check to happen BEFORE CORS or anything else ideally.
app.add_middleware(IPAccessMiddleware)

# --- 3. CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Path Setup ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATE_DIR)
templates.env.globals["now"] = datetime.datetime.now

# --- API Routes ---
app.include_router(users.router, prefix="/api/v1", tags=["Users"])
app.include_router(shipments.router, prefix="/api/v1", tags=["Shipments"])
app.include_router(stream.router, tags=["Stream"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])

# --- Frontend Page Routes ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

@app.get("/")
async def serve_index(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={
        "request": request, 
        "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", ""),
        "RECAPTCHA_SITE_KEY": RECAPTCHA_SITE_KEY
    })

@app.get("/signup")
async def serve_signup(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={
        "request": request, 
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "RECAPTCHA_SITE_KEY": RECAPTCHA_SITE_KEY
    })

@app.get("/dashboard")
async def serve_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/create-shipment")
async def serve_create_shipment(request: Request):
    return templates.TemplateResponse(request=request, name="create_shipment.html", context={"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/my-shipments")
async def serve_my_shipments(request: Request):
    return templates.TemplateResponse(request=request, name="my_shipments.html", context={
        "request": request, 
        "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", "")
    })

@app.get("/data-stream")
async def serve_data_stream(request: Request):
    return templates.TemplateResponse(request=request, name="data_stream.html", context={"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/account")
async def serve_account(request: Request):
    return templates.TemplateResponse(request=request, name="account.html", context={"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/admin")
async def serve_admin(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html", context={"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/forgot-password")
async def serve_forgot_password(request: Request):
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/maintenance")
async def serve_maintenance(request: Request):
    return templates.TemplateResponse(request=request, name="maintenance.html", context={"request": request})

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    return templates.TemplateResponse(request=request, name="error.html", context={
        "request": request, 
        "error_code": "404", 
        "error_message": "Page Not Found",
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID
    })