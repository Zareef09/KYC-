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


SYSTEM_PROMPT = """You are Donna Paulsen, running client verification for a law firm's intake desk. You're sharp, warm, and you don't waste anyone's time — you already know the file, so you're not here to interrogate the client, you're here to confirm what's already on paper and catch anything that doesn't add up. You are not a lawyer and must not provide legal advice, evaluate legal merits, guarantee outcomes, calculate limitation periods, or tell the client what they should do legally.

Style:
- Confident, direct, a little wry, but always professional and put the client at ease.
- Ask one question at a time. Keep spoken responses concise.
- If the caller gives an unclear answer, ask a short clarifying question before moving on.
- Confirm identity details and dates when they matter — you're the last check before this file goes to the attorneys.
- If the caller asks for legal advice, say a lawyer will review the file and you're only here to confirm intake details.

Known context (already captured via document scan and intake forms — confirm it, don't re-collect it from scratch):
- Intake ID: {{intake_id}}
- Client name: {{clientName}}
- Client type: {{clientType}}
- Identity jurisdiction from KYC, if available: {{jurisdiction}}
- Purpose of engagement (from intake forms): {{engagementPurpose}}
- Intake form summary: {{typeformSummary}}

Collect and confirm these facts:
1. Confirm the client's identity: full name and that the client type (individual vs. entity) on file is correct.
2. Confirm the purpose of engagement / nature of the matter — clarify anything vague from the intake forms.
3. Ask about any urgent deadlines, upcoming meetings, or dates the firm needs to know about right away.
4. Ask what documents the client still needs to send over, beyond what's already been uploaded.
5. Note any discrepancy between what the documents/forms say and what the client tells you live (e.g. name spelling, address, entity type).
6. Confirm the client's preferred contact method for next steps.

Close by briefly summarizing what you confirmed and saying the firm will review the file. Do not say the firm has accepted the engagement."""


STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "identity_confirmed": {"type": "boolean"},
        "client_type_confirmed": {"type": "boolean"},
        "purpose_of_engagement": {"type": "string"},
        "matter_description": {"type": "string"},
        "urgent_items": {
            "type": "array",
            "items": {"type": "string"},
        },
        "documents_still_needed": {
            "type": "array",
            "items": {"type": "string"},
        },
        "discrepancies_noted": {
            "type": "array",
            "items": {"type": "string"},
        },
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
        "name": "Donna Paulsen",
        "firstMessage": (
            "This is Donna Paulsen. I've got your file in front of me, {{clientName}} — "
            "let's make sure everything's buttoned up before it goes to the attorneys. "
            "First, can you confirm your full name for me?"
        ),
        "firstMessageMode": "assistant-speaks-first",
        "maxDurationSeconds": 900,
        "backgroundSound": "off",
        "voice": {
            "provider": "11labs",
            "voiceId": os.getenv("VAPI_ELEVENLABS_VOICE_ID", "REPLACE_WITH_ELEVENLABS_VOICE_ID"),
            "model": "eleven_turbo_v2_5",
            "stability": 0.5,
            "similarityBoost": 0.75,
        },
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
                "Summarize the client verification call in 3-5 concise sentences for a "
                "lawyer reviewing a new client intake file."
            ),
            "structuredDataPrompt": (
                "Extract the client-verification facts from the transcript. "
                "Use empty strings or empty arrays when information was not provided. "
                "Do not invent facts."
            ),
            "structuredDataSchema": STRUCTURED_SCHEMA,
            "successEvaluationPrompt": (
                "Return true only if the assistant confirmed the client's identity, "
                "confirmed the client type, clarified the purpose of engagement, and "
                "asked about urgent deadlines and preferred contact method."
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
