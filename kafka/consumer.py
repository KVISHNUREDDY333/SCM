import json
import os
import sys
import certifi
from dotenv import load_dotenv
from kafka import KafkaConsumer
from pymongo import MongoClient

# 1. Setup path to find .env
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# 2. Load .env explicitly
load_dotenv(os.path.join(parent_dir, ".env"))

# Config
BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "mongo") # Default to 'mongo' per your .env
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "device_data")

def main():
    print(f"Starting SCM Archiver Consumer...")
    
    # 1. Connect to MongoDB
    try:
        # tlsCAFile is crucial for the cloud URI in your .env
        mongo_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
        db = mongo_client[DB_NAME]
        collection = db["device_stream"]
        # collection.delete_many({}) # Consider if you really want to clear history every restart

        # Quick ping to check connection
        mongo_client.admin.command('ping')
        print(f"MongoDB Connected: {DB_NAME}")
    except Exception as e:
        print(f" MongoDB Failed: {e}")
        return

    # 2. Connect to Kafka
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            auto_offset_reset='latest',
            enable_auto_commit=True,
            group_id='scm_archiver_group',
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000,
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        print(f"Kafka Listening on topic: {KAFKA_TOPIC}")
    except Exception as e:
        print(f"Kafka Connection Failed: {e}")
        return

    # 3. Process Messages
    try:
        for message in consumer:
            data = message.value
            
            # Save to MongoDB
            collection.insert_one(data)
            
            # Check DB count
            count = collection.count_documents({})
            
            print(f"Saved to DB: {data.get('Shipment_Number')} | {data.get('Route_Details')} | Total: {count}")
            
            # Wipe if it reaches 555
            if count >= 555:
                print("Capacity reached (555). Deleting all records to feed freshly generated shipments...")
                collection.delete_many({})
            
    except KeyboardInterrupt:
        print("\n Consumer stopped.")
    finally:
        consumer.close()
        mongo_client.close()

if __name__ == "__main__":
    main()
    #python SCM/kafka/consumer.py