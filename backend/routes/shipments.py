from fastapi import APIRouter, Body, Depends, HTTPException
from typing import List
from backend.models.shipment import ShipmentSchema
from backend.config.database import shipment_collection
from backend.middleware.security import JWTBearer
from fastapi import HTTPException

router = APIRouter()

@router.post("/shipments", dependencies=[Depends(JWTBearer())])
async def create_shipment(shipment: ShipmentSchema = Body(...)):
    shipment_dict = shipment.dict()
    if shipment_dict.get("Expected_Delivery_Date"):
        shipment_dict["Expected_Delivery_Date"] = shipment_dict["Expected_Delivery_Date"].isoformat()
        
    await shipment_collection.insert_one(shipment_dict)
    return {"message": "Shipment created successfully"}

@router.get("/shipments", dependencies=[Depends(JWTBearer())])
async def get_shipments():
    shipments = []
    # Fetch all shipments
    async for shipment in shipment_collection.find():
        # IMPORTANT: Convert ObjectId to string to prevent JSON errors
        shipment["_id"] = str(shipment["_id"])
        shipments.append(shipment)
    return shipments

@router.delete("/shipments/{shipment_number}", dependencies=[Depends(JWTBearer())])
async def delete_shipment(shipment_number: str):
    # Find and delete the shipment by its Shipment_Number
    result = await shipment_collection.delete_one({"Shipment_Number": shipment_number})
    
    if result.deleted_count == 1:
        return {"message": f"Shipment {shipment_number} deleted successfully"}
    
    raise HTTPException(status_code=404, detail="Shipment not found")

@router.put("/shipments/{shipment_number}", dependencies=[Depends(JWTBearer())])
async def update_shipment(shipment_number: str, shipment: ShipmentSchema = Body(...)):
    # Convert Pydantic model to dict
    update_data = shipment.dict()
    
    # Ensure date is formatted correctly if present
    if update_data.get("Expected_Delivery_Date"):
        update_data["Expected_Delivery_Date"] = update_data["Expected_Delivery_Date"].isoformat()

    # Update in MongoDB
    result = await shipment_collection.update_one(
        {"Shipment_Number": shipment_number},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Shipment not found")

    return {"message": "Shipment updated successfully"}