from fastapi import FastAPI
from routers import chat

app = FastAPI(title="UMMA AI", version="1.0")
app.include_router(chat.router)

@app.get("/")
def root():
    return {"status": "UMMA AI is running"}
