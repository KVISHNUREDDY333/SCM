from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

client = AsyncIOMotorClient(MONGO_URI)
database = client[DB_NAME]

# Collections
user_collection = database.get_collection("users")
shipment_collection = database.get_collection("shipments")
otp_collection = database.get_collection("otps")