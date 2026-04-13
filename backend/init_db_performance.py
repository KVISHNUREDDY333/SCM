from backend.config.database import (
    user_collection, 
    shipment_collection, 
    device_stream_collection,
    audit_collection,
    broadcast_collection
)
import asyncio

async def create_indexes():
    print("Initializing Database Performance Tuning...")
    
    # 1. Users
    await user_collection.create_index("email", unique=True)
    
    # 2. Shipments
    await shipment_collection.create_index("Shipment_Number", unique=True)
    await shipment_collection.create_index("created_by")
    await shipment_collection.create_index("is_kafka")
    
    # 3. Telemetry Stream (High volume indices)
    await device_stream_collection.create_index([("timestamp", -1)])
    await device_stream_collection.create_index("Shipment_Number")
    
    # 4. Global Broadcasts
    await broadcast_collection.create_index([("expires_at", 1)])
    
    print("Database Optimization Complete: All indices deployed.")

if __name__ == "__main__":
    asyncio.run(create_indexes())
