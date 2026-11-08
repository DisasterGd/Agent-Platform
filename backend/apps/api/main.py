from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agent_platform.api.routes import chat, conversations, health
from agent_platform.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(conversations.router, prefix=settings.api_v1_prefix)
app.include_router(chat.router, prefix=settings.api_v1_prefix)

@app.get("/")
def root():
    return {"message": "Agent Platform API is running", "docs": "/docs"}
