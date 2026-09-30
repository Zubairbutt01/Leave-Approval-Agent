import hmac

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from leave_agent import agent, supabase, make_token


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

    try:

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

    except Exception as e:

        # This line shows the real error in the Render Logs
        print("CHAT ERROR:", repr(e))

        return JSONResponse(
            status_code=500,
            content={
                "detail": "The assistant is busy. Please try again in a moment."
            }
        )

    last_message = result["messages"][-1]

    return {
        "response": last_message.content
    }


# =========================================================
# RESULT PAGE (shown after the manager clicks a button)
# =========================================================

def result_page(title, message, color):

    return HTMLResponse(f"""
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{title}</title>
    </head>
    <body style="font-family:Arial,sans-serif;background:#f3f4f6;
                 display:flex;align-items:center;justify-content:center;
                 min-height:100vh;margin:0">
      <div style="background:#fff;padding:36px;border-radius:14px;
                  max-width:420px;text-align:center;
                  box-shadow:0 4px 20px rgba(0,0,0,.1)">
        <h1 style="color:{color};margin-top:0">{title}</h1>
        <p style="color:#374151;line-height:1.6">{message}</p>
      </div>
    </body>
    </html>
    """)


# =========================================================
# DECISION API (the Approve / Reject buttons in the email)
# =========================================================

@app.get("/decision")
def decision(request_id: int, action: str, token: str):

    if action not in ("approve", "reject"):

        return result_page("Invalid link", "Unknown action.", "#dc2626")

    # The secret code must match, so nobody can fake a link
    if not hmac.compare_digest(token, make_token(request_id, action)):

        return result_page(
            "Invalid link",
            "This link is not valid.",
            "#dc2626"
        )

    rows = (
        supabase
        .table("leave_requests")
        .select("status")
        .eq("request_id", request_id)
        .execute()
        .data
    )

    if len(rows) == 0:

        return result_page(
            "Not found",
            f"Request #{request_id} does not exist.",
            "#dc2626"
        )

    # A decision can only be made once
    if rows[0]["status"] != "Pending":

        return result_page(
            "Already decided",
            f"Request #{request_id} is already "
            f"{rows[0]['status']}.",
            "#6b7280"
        )

    new_status = "Approved" if action == "approve" else "Rejected"

    updated = (
        supabase
        .table("leave_requests")
        .update({"status": new_status})
        .eq("request_id", request_id)
        .eq("status", "Pending")
        .execute()
        .data
    )

    if not updated:

        return result_page(
            "Update failed",
            "The database did not accept the change. "
            "Please try again.",
            "#dc2626"
        )

    color = "#16a34a" if new_status == "Approved" else "#dc2626"

    return result_page(
        f"Request {new_status}",
        f"Leave request #{request_id} has been {new_status.lower()}. "
        f"You can close this page.",
        color
    )