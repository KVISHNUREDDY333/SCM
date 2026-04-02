import time
import json
import random
import os
import sys
from dotenv import load_dotenv
from kafka import KafkaProducer

# 1. Setup path to find .env and backend modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# 2. Load .env explicitly
load_dotenv(os.path.join(parent_dir, ".env"))

BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "device_data")

def json_serializer(data):
    return json.dumps(data).encode("utf-8")

def main():
    print(f"Starting SCM Data Producer...")
    print(f"Connecting to Kafka: {BOOTSTRAP_SERVERS}")

    # Create Producer
    try:
        producer = KafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_serializer=json_serializer
        )
        print(f"Connected! Sending real-time data to '{KAFKA_TOPIC}'")
    except Exception as e:
        print(f"Connection Failed: {e}")
        return

    # Data generation logic from your server.py
    routes = ['Newyork,USA', 'Chennai, India', 'Bengaluru, India', 'London,UK']

    try:
        while True:
            # 1. Generate Data (Logic from your server.py)
            routefrom = random.choice(routes)
            routeto = random.choice(routes)

            # Ensure route from and to are different
            while routefrom == routeto:
                routeto = random.choice(routes)

            # 2. Map Server Logic to Frontend Requirements
            # Your frontend expects: Shipment_Number, Device, Temperature, timestamp
            data = {
                "Shipment_Number": f"SHP-{random.randint(1000, 9999)}", 
                "Device": f"IOT-{random.randint(1150, 1158)}", 
                "Temperature": round(random.uniform(10, 40.0), 1), # From server.py logic
                "Battery": f"{round(random.uniform(2.00, 5.00), 2)}V", # From server.py logic
                "Route_Details": f"{routefrom} ➝ {routeto}",
                "timestamp": time.time()
            }
            
            # 3. Send to Kafka
            producer.send(KAFKA_TOPIC, data)
            
            # Print for debugging
            print(f"Sent: {data['Shipment_Number']} | Dev: {data['Device']} | {data['Route_Details']}")
            
            # 4. Wait (Simulate real-time delay)
            time.sleep(3) 

    except KeyboardInterrupt:
        print("\n Producer stopped.")
        producer.close()

if __name__ == "__main__":
    main()
    #python SCM/kafka/producer.py