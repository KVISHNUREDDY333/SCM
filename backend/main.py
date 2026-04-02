from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
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
from backend.routes import users, shipments, stream
# Recaptcha ConfigS
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY") # Load from .env
load_dotenv()

app = FastAPI()

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

# --- Frontend Page Routes ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
@app.get("/")
async def serve_index(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request, 
        "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
        "RECAPTCHA_SITE_KEY": RECAPTCHA_SITE_KEY # <--- Pass this!
    })

@app.get("/")
async def serve_index(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/signup")
async def serve_signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/dashboard")
async def serve_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/create-shipment")
async def serve_create_shipment(request: Request):
    return templates.TemplateResponse("create_shipment.html", {"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

# ... existing imports ...

@app.get("/my-shipments")
async def serve_my_shipments(request: Request):
    return templates.TemplateResponse("my_shipments.html", {
        "request": request, 
        "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID")
    })

@app.get("/data-stream")
async def serve_data_stream(request: Request):
    return templates.TemplateResponse("data_stream.html", {"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/account")
async def serve_account(request: Request):
    return templates.TemplateResponse("account.html", {"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.get("/forgot-password")
async def serve_forgot_password(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request, "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID})

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    return templates.TemplateResponse("error.html", {
        "request": request, 
        "error_code": "404", 
        "error_message": "Page Not Found",
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID
    })

@app.get("/")
async def serve_index(request: Request):
    # Ensure env variable is loaded
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    return templates.TemplateResponse("login.html", {
        "request": request, 
        "GOOGLE_CLIENT_ID": client_id
    })