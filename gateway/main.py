from fastapi import FastAPI
from gateway.api.chat import router as chat_router

app = FastAPI()
app.include_router(chat_router, prefix="/api")
