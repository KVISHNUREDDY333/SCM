from backend.config.database import (
    connect_to_mongo, 
    close_mongo_connection, 
    get_database, 
    get_client
)

# Re-export the functions for easier imports
__all__ = [
    'connect_to_mongo',
    'close_mongo_connection', 
    'get_database',
    'get_client'
]