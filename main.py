from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from leave_agent import agent


# =========================================================
# CREATE FASTAPI APP
# =========================================================

app = FastAPI(
    title="Leave Approval Agent"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# REQUEST FORMAT
# =========================================================

class ChatRequest(BaseModel):

    message: str
    thread_id: str


# =========================================================
# HOME PAGE
# =========================================================

@app.get("/")
def home():

    return FileResponse(
        "templates/index.html"
    )


# =========================================================
# CHAT API
# =========================================================

@app.post("/chat")
def chat(request: ChatRequest):

    config = {
        "configurable": {
            "thread_id": request.thread_id
        }
    }

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": request.message
                }
            ]
        },
        config=config
    )

    last_message = result["messages"][-1]

    return {
        "response": last_message.content
    }