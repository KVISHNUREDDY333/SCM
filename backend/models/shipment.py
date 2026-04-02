from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ShipmentSchema(BaseModel):
    Shipment_Number: str
    Route_Details: str
    Device: str
    Po_Number: str
    NDC_Number: str
    Serial_Number_of_Goods: str
    Container_number: str
    Goods_Type: str
    Expected_Delivery_Date: datetime
    Batch_ID: Optional[str] = None
    Shipment_Description: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "Shipment_Number": "SHP-1001",
                "Route_Details": "New York -> London",
                "Device": "IOT-SENSOR-X9",
                "Po_Number": "PO-9988",
                "NDC_Number": "NDC-1122",
                "Serial_Number_of_Goods": "SN-555444",
                "Container_number": "CONT-A1",
                "Goods_Type": "Pharmaceuticals",
                "Expected_Delivery_Date": "2023-12-31T12:00:00"
            }
        }