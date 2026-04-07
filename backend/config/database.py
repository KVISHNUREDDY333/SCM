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
direct_messages_collection = database.get_collection("direct_messages")
device_stream_collection = database.get_collection("device_stream")

# Index Initialization
import asyncio
async def init_db():
    # TTL Index for OTPs (expire after 5 minutes)
    # The 'expires_at' field in the document will trigger the deletion
    await otp_collection.create_index("expires_at", expireAfterSeconds=0)

# Run initialization
try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(init_db())
    else:
        loop.run_until_complete(init_db())
except Exception as e:
    print(f"Database index initialization warning: {e}")