import os
import smtplib
import hmac
import hashlib
from html import escape
from datetime import date
import httpx

from dotenv import load_dotenv
from supabase import create_client

from langchain.tools import tool
from langchain.chat_models import init_chat_model

from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver


# =========================================================
# 1. LOAD ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")

APPROVAL_SECRET = os.getenv("APPROVAL_SECRET")
BASE_URL = (os.getenv("BASE_URL") or "http://127.0.0.1:8000").rstrip("/")


# =========================================================
# 2. CONNECT TO SUPABASE
# =========================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


PROJECT_ID = SUPABASE_URL.split("//")[1].split(".")[0]

TABLE_EDITOR_LINK = (
    f"https://supabase.com/dashboard/project/{PROJECT_ID}/editor"
)


# =========================================================
# HELPER - SECRET CODE FOR APPROVE / REJECT LINKS
# =========================================================

def make_token(request_id, action):

    if not APPROVAL_SECRET:

        raise ValueError("APPROVAL_SECRET is not set")

    message = f"{int(request_id)}:{action}".encode()

    return hmac.new(
        APPROVAL_SECRET.encode(),
        message,
        hashlib.sha256
    ).hexdigest()


# =========================================================
# 3. TOOL 1 - CHECK LEAVE BALANCE
# =========================================================

@tool
def check_leave_balance(
    employee_id: str,
    total_days: int = 0
) -> str:

    """
    Check that the Employee ID exists and show leave balance.
    If total_days is provided, check whether the employee has
    enough leave.
    """

    rows = (
        supabase
        .table("employees")
        .select("annual_leave_balance")
        .eq("employee_id", employee_id)
        .execute()
        .data
    )

    if len(rows) == 0:

        return f"No employee found with ID {employee_id}."

    elif total_days < 0:

        return "End date cannot be before start date."

    elif total_days == 0:

        return (
            f"Employee {employee_id} has "
            f"{rows[0]['annual_leave_balance']} annual leave day(s) left."
        )

    elif total_days > rows[0]["annual_leave_balance"]:

        return (
            f"Not enough leave balance. Employee has "
            f"{rows[0]['annual_leave_balance']} day(s), "
            f"but asked for {total_days} day(s)."
        )

    else:

        return (
            f"Enough leave balance. Employee has "
            f"{rows[0]['annual_leave_balance']} day(s), "
            f"asked for {total_days} day(s). "
            f"You can create the request."
        )


# =========================================================
# 4. TOOL 2 - CREATE LEAVE REQUEST
# =========================================================


@tool
def create_leave_request(
    employee_id: str,
    start_date: str,
    end_date: str,
    total_days: int,
    reason: str
) -> str:

    """
    Save a new leave request as Pending.
    The database automatically takes these days off the balance.
    Dates must be real dates in YYYY-MM-DD format.
    """

    # --- 1. Check that the dates are real dates ---
    try:

        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

    except ValueError:

        return (
            "Invalid date. Dates must be real dates in YYYY-MM-DD "
            "format. Ask the employee to check the dates."
        )

    # --- 2. Check the order and the past ---
    if end < start:

        return (
            "End date cannot be before start date. "
            "Ask the employee for correct dates."
        )

    if start < date.today():

        return (
            "The start date is in the past. "
            "Ask the employee for a future date."
        )

    # --- 3. Work out the days in code (do not trust the AI's number) ---
    real_days = (end - start).days + 1

    # --- 4. Save, and never let a database error crash the request ---
    try:

        result = (
            supabase
            .table("leave_requests")
            .insert({
                "employee_id": employee_id,
                "start_date": start_date,
                "end_date": end_date,
                "total_days": real_days,
                "reason": reason,
            })
            .execute()
        )

    except Exception as e:

        # Shows the real reason in the Render Logs
        print("CREATE REQUEST ERROR:", repr(e))

        return (
            "The request could not be saved. Ask the employee to "
            "check the details and try again."
        )

    return (
        f"Request created. "
        f"request_id = {result.data[0]['request_id']}, "
        f"status = Pending."
    )


# =========================================================
# 5. TOOL 3 - NOTIFY MANAGER
# =========================================================

@tool
def notify_manager(request_id: str) -> str:

    """
    Email the manager about a new leave request.
    The email has Approve and Reject buttons.
    """

    rows = (
        supabase
        .table("leave_requests")
        .select("*")
        .eq("request_id", request_id)
        .execute()
        .data
    )

    if len(rows) == 0:

        return (
            f"No leave request found with ID {request_id}."
        )

    r = rows[0]

    try:

        base = f"{BASE_URL}/decision?request_id={request_id}"

        approve_url = (
            f"{base}&action=approve"
            f"&token={make_token(request_id, 'approve')}"
        )

        reject_url = (
            f"{base}&action=reject"
            f"&token={make_token(request_id, 'reject')}"
        )

        text = (
            f"Employee {r['employee_id']} requested leave "
            f"from {r['start_date']} to {r['end_date']} "
            f"({r['total_days']} day(s)).\n"
            f"Reason: {r['reason']}\n\n"
            f"Approve: {approve_url}\n"
            f"Reject: {reject_url}"
        )

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;
                    margin:auto;border:1px solid #e5e7eb;
                    border-radius:10px;overflow:hidden">
          <div style="background:#1e3a8a;color:#fff;padding:16px 20px">
            <h2 style="margin:0">Leave Approval Needed</h2>
            <div style="opacity:.8">Request #{request_id}</div>
          </div>
          <div style="padding:20px;color:#111827;line-height:1.7">
            <b>Employee:</b> {escape(str(r['employee_id']))}<br>
            <b>From:</b> {r['start_date']} &nbsp; <b>To:</b> {r['end_date']}<br>
            <b>Days:</b> {r['total_days']}<br>
            <b>Reason:</b> {escape(str(r['reason']))}
            <div style="margin-top:22px">
              <a href="{approve_url}"
                 style="background:#16a34a;color:#fff;padding:12px 26px;
                        border-radius:8px;text-decoration:none;
                        font-weight:bold;margin-right:10px">Approve</a>
              <a href="{reject_url}"
                 style="background:#dc2626;color:#fff;padding:12px 26px;
                        border-radius:8px;text-decoration:none;
                        font-weight:bold">Reject</a>
            </div>
          </div>
        </div>
        """

        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}"
            },
            json={
                "from": "Leave Agent <onboarding@resend.dev>",
                "to": [GMAIL_ADDRESS],
                "subject": f"Leave Approval Needed - Request #{request_id}",
                "text": text,
                "html": html_body,
            },
            timeout=15,
        )

        response.raise_for_status()

    except Exception as e:

        return (
            f"Request #{request_id} was saved, but the email to the "
            f"manager failed: {e}"
        )

    return (
        f"Manager has been emailed about request #{request_id}."
    )


# =========================================================
# 6. TOOL 4 - CHECK REQUEST STATUS
# =========================================================

@tool
def check_request_status(request_id: str) -> str:

    """
    Check whether a leave request is Pending,
    Approved or Rejected.
    """

    result = (
        supabase
        .table("leave_requests")
        .select("*")
        .eq("request_id", request_id)
        .execute()
    )

    rows = result.data

    if len(rows) == 0:

        return (
            f"No leave request found with ID {request_id}."
        )

    status = rows[0]["status"]

    return (
        f"Request #{request_id} status: {status}."
    )


# =========================================================
# 7. TOOL 5 - EMPLOYEE DETAILS
# =========================================================

@tool
def get_employee_details(employee_id: str) -> str:

    """
    Get employee name, email, department and leave balance.
    """

    rows = (
        supabase
        .table("employees")
        .select("*")
        .eq("employee_id", employee_id)
        .execute()
        .data
    )

    if len(rows) == 0:

        return (
            f"No employee found with ID {employee_id}."
        )

    e = rows[0]

    return (
        f"Name: {e['first_name']} {e['last_name']}, "
        f"Email: {e['email']}, "
        f"Department ID: {e['department_id']}, "
        f"Leave balance: {e['annual_leave_balance']} day(s)."
    )


# =========================================================
# 8. ALL TOOLS
# =========================================================

all_tools = [
    check_leave_balance,
    create_leave_request,
    notify_manager,
    check_request_status,
    get_employee_details,
]


# =========================================================
# 9. SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are the "Leave Approval Agent". You only talk about ONE topic:
employee leave requests. If someone asks about anything else, say you can
only help with leave requests.

Today's date is {TODAY}. Use it to find the year when an employee gives
a date without a year.

=====================================================
LEAVE POLICY
=====================================================
- Each employee gets 14 days of annual leave per YEAR.
- The database keeps the balance up to date automatically.
  Pending and Approved requests are already taken off the balance.
- You do NOT approve or reject leave. ONLY the manager does that.
- Never say "approved" or "congratulations" when a request is submitted.

=====================================================
WORKFLOW
=====================================================

STEP 1 - The employee gives their Employee ID:

a. FIRST, call check_leave_balance with ONLY the employee_id.

b. If the tool says "No employee found", tell the employee:
   "This Employee ID was not found. Please enter a valid ID."
   Stop here.

c. If the balance is 0 days, tell the employee:
   "You have 0 leave day(s) left, so you cannot apply for leave
   right now."
   Stop here.

d. If the balance is more than 0 days, tell the employee their
   balance. Then ask for the start date, end date and reason, one
   by one. Skip anything the employee already told you.

=====================================================

STEP 2 - You now have the start date, end date and reason:

a. If the end date is before the start date, tell the employee
   the dates are wrong and ask again.

b. Work out total_days:
   (end date minus start date) + 1
   Example: 15 Oct to 17 Oct = 3 days.

c. Call check_leave_balance again with employee_id AND total_days.

d. If it says "Not enough leave balance", tell the employee:
   "You only have X day(s) left, but you asked for Y day(s)."
   Do not create a request. Stop here.

e. If it says "End date cannot be before start date" or
   "No employee found", tell the employee what is wrong. Stop here.

f. If it says "Enough leave balance", call create_leave_request.

g. It gives you a request_id. Immediately call notify_manager with
   that request_id.

h. Then tell the employee: "Your request #X for Y day(s) has been sent
   to your manager and is waiting for approval."

=====================================================

STEP 3 - EXISTING REQUEST

If the employee asks about an existing request:

a. If you do not have the request_id, ask for it.
b. Call check_request_status.
c. If Pending: "Your request is still waiting for the manager's decision."
d. If Approved: "Your leave request #X was Approved."
e. If Rejected: "Your leave request #X was Rejected."

=====================================================
TOOLS
=====================================================

1. check_leave_balance - Always call this first when you receive an
   Employee ID.
2. create_leave_request - Only call after check_leave_balance says
   "Enough leave balance".
3. notify_manager - Call immediately after create_leave_request.
   Call it only ONE time for each request.
4. check_request_status - Use when the employee asks about a request.
5. get_employee_details - Use only when the employee asks about their
   own details.

=====================================================
RULES
=====================================================

- The balance changes after every request. ALWAYS call
  check_leave_balance again for every new request. NEVER reuse a
  balance from earlier in the chat.
- Always convert dates to YYYY-MM-DD before calling a tool.
- Never create a request without checking the leave balance.
- Never guess a balance, a request_id or a status.
- Never share another employee's information.
- Keep answers short and use simple English.
"""

SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{TODAY}", date.today().isoformat())


# =========================================================
# 10. MISTRAL MODEL
# =========================================================

llm = init_chat_model(
    "open-mistral-nemo",
    model_provider="mistralai",
    temperature=0,
    max_tokens=500
)


# =========================================================
# 11. MEMORY
# =========================================================

memory = MemorySaver()


# =========================================================
# 12. CREATE AGENT
# =========================================================

agent = create_react_agent(
    llm,
    all_tools,
    prompt=SYSTEM_PROMPT,
    checkpointer=memory
)