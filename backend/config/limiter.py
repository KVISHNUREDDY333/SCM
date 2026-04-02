from slowapi import Limiter
from slowapi.util import get_remote_address
import os
from dotenv import load_dotenv

load_dotenv()

global_limit = os.getenv("GLOBAL_RATE_LIMIT", "100/minute")

# Initialize the Limiter using the client's IP address
limiter = Limiter(key_func=get_remote_address, default_limits=[global_limit])