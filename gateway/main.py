from fastapi import FastAPI
from gateway.api.chat import router as chat_router
from gateway.api.admin import router as admin_router
app = FastAPI()
app.include_router(chat_router, prefix="/api")
app.include_router(admin_router, prefix="/admin")
