from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from routers import chat

app = FastAPI(title="UMMA AI", version="1.0")
app.include_router(chat.router)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/test_ui.html")
