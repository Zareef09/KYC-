from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(".env")
load_env_file("backend/.env")

API_BASE_URL = os.getenv("VAPI_API_BASE_URL", "https://api.vapi.ai").rstrip("/")


SYSTEM_PROMPT = """You are a legal intake secretary for a law firm.

Your task is to collect preliminary intake facts from a prospective client who may have a wrongful termination claim. You are not a lawyer and must not provide legal advice, evaluate legal merits, guarantee outcomes, calculate limitation periods, or tell the client what they should do legally.

Style:
- Warm, calm, and professional.
- Ask one question at a time.
- Keep spoken responses concise.
- If the caller gives an unclear answer, ask a short clarifying question before moving on.
- Confirm sensitive dates and employer names when they matter.
- If the caller asks for legal advice, say a lawyer will review the information and you can only collect intake facts.

Known context:
- Intake ID: {{intake_id}}
- Client name: {{clientName}}
- Client type: {{clientType}}
- Identity jurisdiction from KYC, if available: {{jurisdiction}}
- Inquiry type: {{inquiryType}}

Collect these facts:
1. Employer name and work location.
2. Role/title and a brief description of duties.
3. Employment start date and termination/end date.
4. Termination date and the reason the employer gave.
5. Whether they received written notice, severance, final wages, vacation pay, benefits continuation, or a record of employment.
6. Why they believe the termination was wrongful, including discrimination, retaliation, protected leave, contract breach, constructive dismissal, bad faith, or another reason.
7. Relevant documents: employment contract, termination letter, emails, texts, pay stubs, policies, performance reviews, medical notes, or witness names.
8. Damages or impact: lost wages, benefits, job-search status, emotional distress, reputation, or other losses.
9. Any urgent deadlines, upcoming meetings, settlement deadlines, or government/tribunal dates.
10. Desired outcome and preferred contact method.

Close by briefly summarizing the key facts collected and saying the firm will review the information. Do not say the firm has accepted the case."""


STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "employer_name": {"type": "string"},
        "role_title": {"type": "string"},
        "work_location": {"type": "string"},
        "employment_start_date": {"type": "string"},
        "employment_end_date": {"type": "string"},
        "termination_date": {"type": "string"},
        "stated_termination_reason": {"type": "string"},
        "suspected_wrongful_basis": {
            "type": "array",
            "items": {"type": "string"},
        },
        "notice_or_severance": {"type": "string"},
        "final_pay_status": {"type": "string"},
        "documents_available": {
            "type": "array",
            "items": {"type": "string"},
        },
        "damages_described": {
            "type": "array",
            "items": {"type": "string"},
        },
        "desired_outcome": {"type": "string"},
        "contact_preference": {"type": "string"},
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
        },
        "urgent_deadline_flags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "attorney_review_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def webhook_url() -> str | None:
    url = os.getenv("VAPI_SERVER_URL", "").strip()
    secret = os.getenv("VAPI_WEBHOOK_SECRET", "").strip()
    if not url:
        return None
    if not secret:
        return url

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("secret", secret))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def assistant_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Wrongful Termination Intake Secretary",
        "firstMessage": (
            "Hello {{clientName}}, I am the firm's intake assistant. I can collect "
            "some preliminary information about your employment matter for the legal "
            "team to review. To start, what employer is this about?"
        ),
        "firstMessageMode": "assistant-speaks-first",
        "maxDurationSeconds": 900,
        "backgroundSound": "off",
        "compliancePlan": {
            "hipaaEnabled": True,
        },
        "artifactPlan": {
            "recordingEnabled": False,
            "loggingEnabled": False,
            "pcapEnabled": False,
            "transcriptPlan": {
                "enabled": True,
                "assistantName": "Intake assistant",
                "userName": "Prospective client",
            },
        },
        "clientMessages": [
            "status-update",
            "transcript",
            "conversation-update",
            "hang",
            "user-interrupted",
            "assistant.started",
        ],
        "serverMessages": [
            "status-update",
            "transcript",
            "conversation-update",
            "end-of-call-report",
            "hang",
            "assistant.started",
        ],
        "model": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                }
            ],
        },
        "analysisPlan": {
            "summaryPrompt": (
                "Summarize the employment intake call in 3-5 concise sentences for a "
                "lawyer reviewing a possible wrongful termination matter."
            ),
            "structuredDataPrompt": (
                "Extract the wrongful termination intake facts from the transcript. "
                "Use empty strings or empty arrays when information was not provided. "
                "Do not invent facts."
            ),
            "structuredDataSchema": STRUCTURED_SCHEMA,
            "successEvaluationPrompt": (
                "Return true only if the assistant collected the employer, role, "
                "termination date or end date, stated reason, suspected wrongful basis, "
                "available documents, damages, and preferred contact method."
            ),
            "successEvaluationRubric": "PassFail",
        },
    }

    url = webhook_url()
    if url:
        payload["server"] = {"url": url}
    return payload


def request_json(method: str, path: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "kyc-intake-vapi-setup/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Vapi API error {error.code}: {body}") from error


def main() -> None:
    token = os.getenv("VAPI_PRIVATE_API_KEY") or os.getenv("VAPI_API_KEY")
    if not token:
        raise SystemExit("Set VAPI_PRIVATE_API_KEY before running this script.")

    assistant_id = os.getenv("VAPI_ASSISTANT_ID", "").strip()
    payload = assistant_payload()

    if assistant_id:
        assistant = request_json("PATCH", f"/assistant/{assistant_id}", token, payload)
        action = "updated"
    else:
        assistant = request_json("POST", "/assistant", token, payload)
        action = "created"

    result = {
        "action": action,
        "assistant_id": assistant.get("id"),
        "hipaa_enabled": (assistant.get("compliancePlan") or {}).get("hipaaEnabled"),
        "server_configured": bool((assistant.get("server") or {}).get("url")),
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
