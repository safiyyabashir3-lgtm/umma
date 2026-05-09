from fastapi import APIRouter
from pydantic import BaseModel
from services.intent import classify_intent
from services.reasoning import reason_symptom, respond_general

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    user_id: str = "anonymous"

class ChatResponse(BaseModel):
    intent: str
    response: str

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    intent = classify_intent(request.message)
    rag_context = ""  # RAG will plug in here in next phase

    if intent in ["pregnancy_symptom", "child_symptom", "emergency"]:
        result = reason_symptom(request.message, rag_context, intent)
        return ChatResponse(intent=intent, response=result["advice"])
    else:
        response = respond_general(request.message, rag_context, intent)
        return ChatResponse(intent=intent, response=response)
