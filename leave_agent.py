import os
import smtplib
from email.message import EmailMessage

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
    """

    result = (
        supabase
        .table("leave_requests")
        .insert({
            "employee_id": employee_id,
            "start_date": start_date,
            "end_date": end_date,
            "total_days": total_days,
            "reason": reason,
        })
        .execute()
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

    email = EmailMessage()

    email["From"] = GMAIL_ADDRESS
    email["To"] = GMAIL_ADDRESS

    email["Subject"] = (
        f"Leave Approval Needed - Request #{request_id}"
    )

    email.set_content(
        f"Employee {r['employee_id']} has requested leave.\n"
        f"From {r['start_date']} to {r['end_date']} "
        f"({r['total_days']} day(s)).\n"
        f"Reason: {r['reason']}\n\n"
        f"Open the Supabase leave_requests table and "
        f"set request #{request_id} to Approved or Rejected:\n"
        f"{TABLE_EDITOR_LINK}"
    )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465
    ) as server:

        server.login(
            GMAIL_ADDRESS,
            GMAIL_APP_PASSWORD
        )

        server.send_message(email)

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
# TOOL 6 - UPDATE LEAVE BALANCE
# =========================================================

@tool
def update_leave_balance(employee_id: str) -> str:
    """
    Update an employee's leave balance after approved leave.
    The balance is calculated from all Approved leave requests.
    """

    # Get employee's current/base leave allocation
    employee = (
        supabase
        .table("employees")
        .select("annual_leave_balance")
        .eq("employee_id", employee_id)
        .execute()
        .data
    )

    if len(employee) == 0:
        return f"No employee found with ID {employee_id}."

    # Get all approved leave requests for this employee
    approved_requests = (
        supabase
        .table("leave_requests")
        .select("total_days")
        .eq("employee_id", employee_id)
        .eq("status", "Approved")
        .execute()
        .data
    )

    # Calculate total approved leave
    total_used = sum(
        request["total_days"]
        for request in approved_requests
    )

    # IMPORTANT:
    # This assumes 14 is the employee's original leave allocation.
    total_leave = 14

    new_balance = total_leave - total_used

    if new_balance < 0:
        new_balance = 0

    # Update employee balance
    (
        supabase
        .table("employees")
        .update({
            "annual_leave_balance": new_balance
        })
        .eq("employee_id", employee_id)
        .execute()
    )

    return (
        f"Leave balance updated for employee {employee_id}. "
        f"Approved leave used: {total_used} day(s). "
        f"Remaining leave: {new_balance} day(s)."
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
    update_leave_balance,
]


# =========================================================
# 9. SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are the "Leave Approval Agent". You only talk about ONE topic:
employee leave requests. If someone asks about anything else, say you can
only help with leave requests.

=====================================================
YOUR WORKFLOW
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

Example:

15 Oct to 17 Oct = 3 days.

c. Call check_leave_balance again with employee_id AND total_days.

d. If it says "Not enough leave balance", tell the employee:

"You only have X day(s) left, but you asked for Y day(s)."

Do not create a request.

e. If it says "End date cannot be before start date" or
"No employee found", tell the employee what is wrong.

Stop here.

f. If it says "Enough leave balance", call create_leave_request.

g. It gives you a request_id.

Immediately call notify_manager with that request_id.

=====================================================

STEP 3 - EXISTING REQUEST

If the employee asks about an existing request:

a. If you do not have the request_id, ask for it.

b. Call check_request_status.

c. If Pending:

Tell the employee it is still waiting for the manager's decision.

d. If Approved:

"Your leave request #X was Approved."

e. If Rejected:

"Your leave request #X was Rejected."

=====================================================
TOOLS
=====================================================

1. check_leave_balance

Always call this first when you receive an Employee ID.

2. create_leave_request

Only call this after check_leave_balance confirms
there is enough leave.

3. notify_manager

Call immediately after create_leave_request.

Call it only ONE time for each request.

4. check_request_status

Use when the employee asks about an existing request.

5. get_employee_details

Use only when the employee asks about their own details.

First confirm their Employee ID exists.

=====================================================
RULES
=====================================================

- Always convert dates to YYYY-MM-DD before calling a tool.
- Never create a request without checking the leave balance.
- Never guess a balance.
- Never guess a request_id.
- Never guess a status.
- Never expose another employee's information.
- Keep answers short.
- Use simple English.
- Only talk about employee leave requests.
"""


# =========================================================
# 10. MISTRAL MODEL
# =========================================================

llm = init_chat_model(
    "open-mistral-nemo",
    model_provider="mistralai",
    temperature=0.5,
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