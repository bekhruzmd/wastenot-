from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import firebase_admin
from firebase_admin import credentials, firestore, auth
import vertexai
from vertexai.preview.generative_models import GenerativeModel
from datetime import datetime
import os
from dotenv import load_dotenv
from google.oauth2 import service_account


# Load environment variables
load_dotenv()

# Get configuration from .env
FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("VERTEX_AI_LOCATION")
MODEL_NAME = os.getenv("VERTEX_AI_MODEL")
FRONTEND_URL = os.getenv("FRONTEND_URL")
BACKEND_PORT = int(os.getenv("BACKEND_PORT"))

# Initialize FastAPI
app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Firebase
cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Initialize Vertex AI with explicit credentials
vertex_credentials = service_account.Credentials.from_service_account_file(
    FIREBASE_CREDENTIALS_PATH
)
vertexai.init(
    project=PROJECT_ID, 
    location=LOCATION,
    credentials=vertex_credentials
)
model = GenerativeModel(MODEL_NAME)

# Models
class AuthRequest(BaseModel):
    email: str
    password: str

class InventoryItem(BaseModel):
    user_id: str
    name: str
    quantity: int
    expiration_date: Optional[str] = None

class ChatRequest(BaseModel):
    user_id: str
    message: str

# Auth Endpoints
@app.post("/auth/signup")
async def signup(req: AuthRequest):
    try:
        user = auth.create_user(email=req.email, password=req.password)
        return {"user": {"uid": user.uid, "email": user.email}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
@app.post("/auth/login")
async def login(req: AuthRequest):
    try:
        user = auth.get_user_by_email(req.email)
        return {"user": {"uid": user.uid, "email": user.email}}
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    
# Inventory Endpoints
@app.get("/inventory/{user_id}")
async def get_inventory(user_id: str):
    items = []
    docs = db.collection("inventory").where("user_id", "==", user_id).stream()
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        items.append(data)
    return items    

@app.post("/inventory")
async def add_inventory(item: InventoryItem):
    doc_ref = db.collection("inventory").document()
    doc_ref.set({
        "user_id": item.user_id,
        "name": item.name,
        "quantity": item.quantity,
        "expiration_date": item.expiration_date,
        "created_at": datetime.now()
    })
    return {"id": doc_ref.id, "message": "Item added"}

@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        # Get user's inventory
        inventory = []
        docs = db.collection("inventory").where("user_id", "==", req.user_id).stream()
        for doc in docs:
            data = doc.to_dict()
            inventory.append(f"{data['name']} (qty: {data['quantity']}, expires: {data.get('expiration_date', 'N/A')})")
        
        # Build prompt
        inventory_text = "\n".join(inventory) if inventory else "No items in inventory"
        prompt = f"""You are a helpful cooking assistant. 
        
Current inventory:
{inventory_text}

User question: {req.message}

Provide helpful recipe suggestions based on their available ingredients. Prioritize items that are expiring soon."""
        
        # Call Vertex AI with error handling
        print(f"Sending prompt to Vertex AI: {prompt[:100]}...")  # Debug log
        response = model.generate_content(prompt)
        
        # Try different ways to access the response
        if hasattr(response, 'text'):
            response_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            response_text = response.candidates[0].content.parts[0].text
        else:
            print(f"Response object: {response}")  # Debug log
            response_text = str(response)
        
        return {"response": response_text}
    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")  # Debug log
        print(f"Error type: {type(e)}")  # Debug log
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=BACKEND_PORT)