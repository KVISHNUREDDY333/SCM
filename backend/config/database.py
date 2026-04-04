from motor.motor_asyncio import AsyncIOMotorClient
import os
import certifi
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

# Added tlsCAFile to resolve SSL/TLS connection issues on Windows
client = AsyncIOMotorClient(MONGO_URI, tlsCAFile=certifi.where())
database = client[DB_NAME]

# Collections
user_collection = database.get_collection("users")
shipment_collection = database.get_collection("shipments")
otp_collection = database.get_collection("otps")
audit_collection = database.get_collection("audit_logs")
session_collection = database.get_collection("sessions")
broadcast_collection = database.get_collection("broadcasts")
settings_collection = database.get_collection("app_settings")