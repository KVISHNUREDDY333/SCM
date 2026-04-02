import os
import requests
from dotenv import load_dotenv

load_dotenv()

# We use the Secret Key for standard/checkbox verification
RECAPTCHA_SECRET = os.getenv("RECAPTCHA_SECRET_KEY")

def verify_recaptcha(token: str) -> bool:
    """Verifies the token using standard Google reCAPTCHA endpoint"""
    if not token:
        return False
        
    try:
        # Standard siteverify URL (Works for both v2 and Enterprise keys with legacy secret)
        url = "https://www.google.com/recaptcha/api/siteverify"
        
        payload = {
            "secret": RECAPTCHA_SECRET,
            "response": token
        }
        
        # Send POST request
        response = requests.post(url, data=payload)
        result = response.json()
        
        # Check success
        return result.get("success", False)

    except Exception as e:
        print(f"ReCAPTCHA Connection Error: {e}")
        return False