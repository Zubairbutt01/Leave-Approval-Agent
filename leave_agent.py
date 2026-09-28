"""
leave_agent.py
--------------

    1. Load keys from .env
    2. Connect to Supabase
    3. Define the 5 tools
    4. Set up the LLM (Mistral model directly)
    5. Set up memory
    6. Connect LLM, tools, memory and prompt into one agent
    7. Run the chat loop

Run with:  uv run leave_agent.py
"""

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv
from supabase import create_client
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# ---------------------------------------------------------------------
# STEP 1: Load your keys from .env
# ---------------------------------------------------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# STEP 2: Connect to Supabase

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# and it is put inside the manager email so the manager can click on it and after clicking on it manager can cancel or approve the request.
PROJECT_ID = SUPABASE_URL.split("//")[1].split(".")[0]
TABLE_EDITOR_LINK = f"https://supabase.com/dashboard/project/{PROJECT_ID}/editor"


# ---------------------------------------------------------------------
# STEP 3: The 5 tools
# ---------------------------------------------------------------------

@tool
def check_leave_balance(employee_id: str, total_days: int = 0) -> str:
    """
    Check that the Employee ID exists and show its leave balance.
    Optional: give total_days to also check that the balance is enough
    (total_days = end date minus start date, plus 1).
    Leave total_days out when you only want to see the balance.
    """
    rows = supabase.table("employees").select("annual_leave_balance").eq("employee_id", employee_id).execute().data

    if len(rows) == 0:
        return f"No employee found with ID {employee_id}."
    elif total_days < 0:
        return "End date cannot be before start date."
    elif total_days == 0:
        return f"Employee {employee_id} has {rows[0]['annual_leave_balance']} annual leave day(s) left."
    elif total_days > rows[0]["annual_leave_balance"]:
        return f"Not enough leave balance. Employee has {rows[0]['annual_leave_balance']} day(s), but asked for {total_days} day(s)."
    else:
        return f"Enough leave balance. Employee has {rows[0]['annual_leave_balance']} day(s), asked for {total_days} day(s). You can create the request."


@tool
def create_leave_request(employee_id: str, start_date: str, end_date: str, total_days: int, reason: str) -> str:
    """
    Save a new leave request as Pending.
    Use it only after check_leave_balance (with total_days) says "Enough leave balance".
    Dates must be in YYYY-MM-DD format.
    """
    result = supabase.table("leave_requests").insert({
        "employee_id": employee_id,
        "start_date": start_date,
        "end_date": end_date,
        "total_days": total_days,
        "reason": reason,
    }).execute()

    return f"Request created. request_id = {result.data[0]['request_id']}, status = Pending."


@tool
def notify_manager(request_id: str) -> str:
    """
    Email the manager about a new leave request, so they can approve or reject it.
    Use it right after create_leave_request, with the request_id it gave.
    """
    rows = supabase.table("leave_requests").select("*").eq("request_id", request_id).execute().data

    if len(rows) == 0:
        return f"No leave request found with ID {request_id}."
    else:
        r = rows[0]
        email = EmailMessage()
        email["From"] = GMAIL_ADDRESS
        email["To"] = GMAIL_ADDRESS
        email["Subject"] = f"Leave Approval Needed - Request #{request_id}"
        email.set_content(
            f"Employee {r['employee_id']} has requested leave.\n"
            f"From {r['start_date']} to {r['end_date']} ({r['total_days']} day(s)).\n"
            f"Reason: {r['reason']}\n\n"
            f"Click this link, open the leave_requests table, and set request #{request_id} to Approved or Rejected:\n"
            f"{TABLE_EDITOR_LINK}"
        )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(email)

        return f"Manager has been emailed about request #{request_id}."


@tool
def check_request_status(request_id: str) -> str:
    """
    Purpose: Check if a leave request is Pending, Approved, or Rejected.
    Use this when the employee asks about an existing request.
    """
    result = supabase.table("leave_requests").select("*").eq("request_id", request_id).execute()
    rows = result.data

    if len(rows) == 0:
        return f"No leave request found with ID {request_id}."
    else:
        status = rows[0]["status"]
        return f"Request #{request_id} status: {status}."


@tool
def get_employee_details(employee_id: str) -> str:
    """Get an employee's name, email, department ID and leave balance."""
    rows = supabase.table("employees").select("*").eq("employee_id", employee_id).execute().data

    if len(rows) == 0:
        return f"No employee found with ID {employee_id}."
    else:
        e = rows[0]
        return f"Name: {e['first_name']} {e['last_name']}, Email: {e['email']}, Department ID: {e['department_id']}, Leave balance: {e['annual_leave_balance']} day(s)."


all_tools = [
    check_leave_balance,
    create_leave_request,
    notify_manager,
    check_request_status,
    get_employee_details,
]


# SYSTEM PROMPT 

SYSTEM_PROMPT = """
You are the "Leave Approval Agent". You only talk about ONE topic:
employee leave requests. If someone asks about anything else, say you can
only help with leave requests.

=====================================================
YOUR WORKFLOW (follow it in order)
=====================================================

STEP 1 - The employee gives their Employee ID:
   a. FIRST, call check_leave_balance with ONLY the employee_id
      (do not give total_days yet).
   b. If the tool says "No employee found", tell the employee:
      "This Employee ID was not found. Please enter a valid ID."
      Stop here. Do not call any other tool.
   c. If the balance is 0 (zero) days, tell the employee:
      "You have 0 leave day(s) left, so you cannot apply for leave
      right now." Stop here.
   d. If the balance is more than 0 days, tell the employee their
      balance. Then ask for the start date, end date and reason, one
      by one (skip anything the employee already told you).

STEP 2 - You now have the start date, end date and reason:
   a. If the end date is before the start date, tell the employee the
      dates are wrong and ask again. Stop here.
   b. Work out total_days: (end date minus start date) plus 1.
      Example: 15 Oct to 17 Oct = 3 days.
   c. Call check_leave_balance again, this time with the employee_id
      AND total_days.
   d. If it says "Not enough leave balance", tell the employee:
      "You only have X day(s) left, but you asked for Y day(s)."
      Stop here. Do not create a request.
   e. If it says "End date cannot be before start date" or "No
      employee found", tell the employee what is wrong. Stop here.
   f. If it says "Enough leave balance", call create_leave_request.
   g. It gives you a request_id. Right after that, call
      notify_manager with that request_id.

STEP 3 - The employee asks about an existing request:
   a. If you do not have the request_id, ask the employee for it.
   b. Call check_request_status with the request_id.
   c. If the status is "Pending", tell the employee it is still
      waiting for the manager's decision.
   d. If the status is "Approved", tell the employee: "Your leave
      request #X was Approved."
   e. If the status is "Rejected", tell the employee: "Your leave
      request #X was Rejected."

=====================================================
YOUR 5 TOOLS
=====================================================

1. check_leave_balance
   - What it does: checks that the Employee ID exists and shows the
     leave balance. If you also give total_days, it checks that the
     balance is enough for those days.
   - When: ALWAYS first, as soon as you get an Employee ID (only the
     ID). Then once more with total_days, BEFORE create_leave_request.
     Never skip the second check.
   - Input: employee_id, and total_days (only in the second check;
     you work it out yourself).
   - Next: follow STEP 1 and STEP 2.

2. create_leave_request
   - What it does: saves a new leave request as "Pending".
   - When: only after check_leave_balance (with total_days) says
     "Enough leave balance".
   - Input: employee_id, start_date, end_date (format YYYY-MM-DD),
     total_days, reason.
   - Next: call notify_manager with the request_id it gives you.

3. notify_manager
   - What it does: emails the manager to approve or reject.
   - When: only right after create_leave_request gives a request_id.
   - Input: only the request_id from create_leave_request. Never make
     up a request_id.
   - Call it only ONE time for each request.
   - Next: tell the employee: "Your request was submitted. Your
     request_id is X. The manager has been notified by email."
   - If it says "No leave request found", or gives an error, tell the
     employee: "Your request was saved, but the email to the manager
     could not be sent." Do not try again with another request_id.

4. check_request_status
   - What it does: shows if a request is Pending, Approved or Rejected.
   - When: the employee asks about a request they already made.
   - Input: request_id.
   - Next: follow STEP 3.

5. get_employee_details
   - What it does: shows name, email, department and balance.
   - When: only if the employee asks about their own details, for
     example "what is my email?", and only after check_leave_balance
     has confirmed the ID exists.
   - Input: employee_id (only the ID the employee gave at the start).
     Never give details of any other employee.
   - Next: answer in one or two short, simple sentences.

=====================================================
RULES
=====================================================
- Always convert dates to YYYY-MM-DD format before calling a tool.
- Never call create_leave_request until check_leave_balance (with
  total_days) has said "Enough leave balance" for the same days.
- Never call notify_manager or get_employee_details unless
  check_leave_balance has already confirmed the employee exists.
- Never guess a balance, request_id or status. Always call the correct
  tool to get real data.
- Keep your answers short and in simple English.
"""


# STEP 4: The LLM — Mistral model, connected directly

llm = init_chat_model("open-mistral-nemo", model_provider="mistralai", temperature=0.5, max_tokens=500)

# ---------------------------------------------------------------------
# STEP 5: Memory — a checkpointer that automatically remembers every
# message in the conversation, tied to a "thread_id" (like a chat session ID)
# ---------------------------------------------------------------------
memory = MemorySaver()

# ---------------------------------------------------------------------
# STEP 6: Connect the LLM, tools, system prompt and memory into one agent
# ---------------------------------------------------------------------
agent = create_react_agent(llm, all_tools, prompt=SYSTEM_PROMPT, checkpointer=memory)

# it will tells the checkpointer which "conversation" to remember.
config = {"configurable": {"thread_id": "leave-chat-1"}}



# STEP 8: The chat while loop

print("Leave Approval Agent")
print("Type 'exit' to quit.\n")

employee_id = input("Enter your Employee ID: ")
user_message = f" MyEmployee ID:{employee_id}"

while True:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_message}]},
        config=config,
    )
    print("Agent:", result["messages"][-1].content)

    user_message = input("You: ")
    if user_message.lower() == "exit":
        break