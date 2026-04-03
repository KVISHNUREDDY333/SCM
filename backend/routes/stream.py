from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from backend.auth.jwt_handler import decodeJWT
from aiokafka import AIOKafkaConsumer
import asyncio
import json
import random
import uuid
import datetime
import os
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

KAFKA_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "device_data")

async def event_generator():
    """
    Generator that yields Server-Sent Events (SSE).
    If Kafka is offline, it falls back to generating mock data.
    """
    kafka_available = False
    consumer = None

    # 1. Try connecting to Kafka
    try:
        client_id = str(uuid.uuid4())[:8]
        consumer = AIOKafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_SERVER,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            auto_offset_reset='latest',
            enable_auto_commit=False,  # No need to commit since it's a transient stream
            group_id=f"scm_dashboard_group_{client_id}",
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000
        )
        await consumer.start()
        kafka_available = True
        print(f"Connected to Kafka topic: {KAFKA_TOPIC}")
    except Exception as e:
        print(f"Kafka Connection Failed ({e}). Switching to SIMULATION MODE.")
        kafka_available = False

    try:
        if kafka_available:
            # --- REAL KAFKA MODE ---
            async for msg in consumer:
                data = msg.value  # Already deserialized by value_deserializer
                # Ensure data has the expected fields for frontend
                formatted_data = {
                    "Shipment_Number": data.get("Shipment_Number", "Unknown"),
                    "Device": data.get("Device", "Unknown"),
                    "Temperature": data.get("Temperature", 0.0),
                    "Location": data.get("Route_Details", "Unknown"),  # Map Route_Details to Location for frontend
                    "Battery": data.get("Battery", "0%"),
                    "timestamp": data.get("timestamp", datetime.datetime.now().timestamp())
                }
                yield f"data: {json.dumps(formatted_data)}\n\n"
        else:
            # --- SIMULATION MODE ---
            routes = ['Newyork,USA', 'Chennai, India', 'Bengaluru, India', 'London,UK']
            
            while True:
                await asyncio.sleep(3)  # Match producer delay
                
                # Generate fake sensor data matching your producer format
                routefrom = random.choice(routes)
                routeto = random.choice(routes)
                while routefrom == routeto:
                    routeto = random.choice(routes)
                
                mock_data = {
                    "Shipment_Number": f"SHP-{random.randint(1000, 9999)}",
                    "Device": f"IOT-{random.randint(1150, 1158)}",
                    "Temperature": round(random.uniform(10, 40.0), 1),
                    "Location": f"{routefrom} ➝ {routeto}",  # Use Route_Details format
                    "Battery": f"{random.randint(20, 100)}%",  # Convert to percentage for frontend
                    "timestamp": datetime.datetime.now().timestamp()
                }
                
                yield f"data: {json.dumps(mock_data)}\n\n"

    except asyncio.CancelledError:
        print("Client disconnected from stream.")
    except Exception as e:
        print(f"Stream error: {e}")
    finally:
        # Ensure proper cleanup
        if consumer is not None:
            try:
                await consumer.stop()
            except Exception as cleanup_err:
                print(f"Error while stopping consumer: {cleanup_err}")

@router.get("/events")
async def message_stream(token: str = Query(None)):
    """Endpoint that frontend EventSource connects to."""
    if not token or not decodeJWT(token):
        raise HTTPException(status_code=403, detail="Unauthenticated Stream Request")
        
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )