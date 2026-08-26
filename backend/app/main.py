from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError
from pydantic import BaseModel
import pytesseract

from . import db


BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "data.db"


def load_local_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
db.init_db(DB_PATH)

ALLOWED_CLIENT_TYPES = {"individual", "entity"}
FILE_KEYS = {"license_front", "license_back", "articles"}
VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "")
TYPEFORM_WEBHOOK_SECRET = os.getenv("TYPEFORM_WEBHOOK_SECRET", "")
TYPEFORM_FORM1_URL = os.getenv("TYPEFORM_FORM1_URL", "")
TYPEFORM_FORM1_ID = os.getenv("TYPEFORM_FORM1_ID", "")
TYPEFORM_FORM2_ID = os.getenv("TYPEFORM_FORM2_ID", "")

DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}[-/]\d{2}[-/]\d{2}\b")
POSTAL_PATTERN = re.compile(r"\b(?:[A-Z]\d[A-Z][ -]?\d[A-Z]\d|\d{6})\b", re.I)
PROVINCE_PATTERN = re.compile(
    r"\b(?:AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b", re.I
)
STREET_PATTERN = re.compile(
    r"\b(?:STREET|ST\.?|AVENUE|AVE\.?|ROAD|RD\.?|DRIVE|DR\.?|COURT|CT\.?|"
    r"LANE|LN\.?|BOULEVARD|BLVD\.?|CRESCENT|CRES\.?|WAY|PLACE|PL\.?)\b",
    re.I,
)
LICENSE_PATTERN = re.compile(
    r"\b(?:[A-Z0-9]{1,5}-[A-Z0-9]{4,6}-[A-Z0-9]{4,6}|"
    r"[A-Z]\d{4}-\d{5}-\d{5}|\d{4}-\d{5}-\d{5}|[A-Z0-9]{12,17})\b",
    re.I,
)


app = FastAPI(
    title="KYC Intake API",
    description="Hackathon prototype API for license collection, OCR, and admin review.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def safe_filename(filename: str | None, fallback: str) -> str:
    raw_name = filename or fallback
    name = Path(raw_name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    return cleaned or fallback


async def save_upload(upload: UploadFile, folder: Path, fallback: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / safe_filename(upload.filename, fallback)

    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            output.write(chunk)

    await upload.close()
    return destination


def prepare_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    if image.width < 1800:
        scale = 1800 / image.width
        image = image.resize((1800, int(image.height * scale)))

    grayscale = ImageOps.grayscale(image)
    grayscale = ImageOps.autocontrast(grayscale)
    grayscale = ImageEnhance.Contrast(grayscale).enhance(1.8)
    grayscale = grayscale.filter(ImageFilter.SHARPEN)
    return grayscale


def run_ocr(image: Image.Image, psm: int = 6) -> str:
    return pytesseract.image_to_string(
        image,
        config=f"--oem 3 --psm {psm} -l eng",
    )


def extract_license(image_path: Path, side: str) -> dict[str, object]:
    try:
        with Image.open(image_path) as source:
            prepared = prepare_image(source)
            raw_text = run_ocr(prepared)

            crop_text = ""
            if side == "back":
                width, height = prepared.size
                crop = prepared.crop(
                    (int(width * 0.45), int(height * 0.08), width, int(height * 0.55))
                )
                crop_text = run_ocr(crop, psm=6)
    except UnidentifiedImageError:
        raise HTTPException(
            status_code=400,
            detail=f"{image_path.name} is not a readable image file.",
        ) from None
    except pytesseract.TesseractNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Tesseract is not installed or is not available on PATH.",
        ) from None

    normalized_text = normalize_text(raw_text)
    if side == "back":
        crop_normalized = normalize_text(crop_text)
        return {
            "raw_text": raw_text.strip(),
            "crop_text": crop_text.strip(),
            "fields": {
                "license_number": extract_license_number(
                    crop_normalized, fallback_text=normalized_text
                )
            },
        }

    return {
        "raw_text": raw_text.strip(),
        "fields": parse_front_fields(normalized_text),
    }


def normalize_text(text: str) -> str:
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "|": "I",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return "\n".join(line.strip() for line in text.upper().splitlines() if line.strip())


def clean_value(value: str) -> str:
    value = re.sub(r"^[^A-Z0-9]+", "", value.strip().upper())
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip(" :-#")


def lines_from(text: str) -> list[str]:
    return [clean_value(line) for line in text.splitlines() if clean_value(line)]


def value_after_label(line: str, labels: tuple[str, ...]) -> str | None:
    label_expr = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"\b(?:{label_expr})\b\s*[:#-]?\s*(.+)$", line, re.I)
    if match:
        return clean_value(match.group(1))

    compact_line = re.sub(r"[^A-Z0-9]", "", line.upper())
    compact_labels = [re.sub(r"[^A-Z0-9]", "", label.upper()) for label in labels]
    if compact_line in compact_labels:
        return None

    for label in sorted(labels, key=len, reverse=True):
        compact_label = re.sub(r"[^A-Z0-9]", "", label.upper())
        if compact_label == "CL" and compact_line.startswith("CLASS"):
            continue
        if compact_line.startswith(compact_label) and len(compact_line) > len(compact_label):
            return clean_value(compact_line[len(compact_label) :])
    return None


def parse_front_fields(text: str) -> dict[str, str | None]:
    lines = lines_from(text)
    date_values = extract_labeled_dates(lines)
    address = extract_address(lines)
    first_name, last_name = extract_name(lines)

    return {
        "last_name": last_name,
        "first_name": first_name,
        "full_name": " ".join(part for part in [first_name, last_name] if part) or None,
        "address_line": address["address_line"],
        "city": address["city"],
        "province": address["province"],
        "postal_code": address["postal_code"],
        "license_number": extract_license_number(text),
        "issue_date": date_values["issue_date"],
        "expiry_date": date_values["expiry_date"],
        "date_of_birth": date_values["date_of_birth"],
        "reference_number": extract_labeled_value(
            lines, ("REF", "REFERENCE", "REFERENCE NO", "REFERENCE NUMBER")
        ),
        "height": extract_height(text),
        "sex": extract_sex(lines),
        "license_class": extract_labeled_value(lines, ("CLASS", "CL")),
        "conditions": extract_labeled_value(lines, ("CONDITIONS", "COND")),
    }


def extract_name(lines: list[str]) -> tuple[str | None, str | None]:
    ignored = {
        "DRIVER",
        "DRIVERS",
        "LICENCE",
        "LICENSE",
        "CANADA",
        "ONTARIO",
        "BRITISH",
        "COLUMBIA",
        "QUEBEC",
        "ALBERTA",
    }

    for line in lines:
        value = value_after_label(
            line, ("NAME", "NOM", "SURNAME", "LAST NAME", "GIVEN NAME")
        )
        candidate = value or line
        words = [
            word
            for word in re.findall(r"\b[A-Z]{2,}\b", candidate)
            if word not in ignored
        ]
        if len(words) >= 2 and not STREET_PATTERN.search(candidate):
            return words[1], words[0]

    return None, None


def extract_address(lines: list[str]) -> dict[str, str | None]:
    address_line = None
    city = None
    province = None
    postal_code = None

    for index, line in enumerate(lines):
        postal_match = POSTAL_PATTERN.search(line)
        if not postal_match:
            continue

        postal_code = postal_match.group(0).replace(" ", "").upper()
        province_match = PROVINCE_PATTERN.search(line)
        province = province_match.group(0).upper() if province_match else None

        before_postal = clean_value(line[: postal_match.start()])
        if province:
            before_postal = clean_value(
                re.sub(rf"\b{province}\b", "", before_postal, flags=re.I)
            )
        elif len(before_postal) > 2 and before_postal[-2:] in {
            "AB",
            "BC",
            "MB",
            "NB",
            "NL",
            "NS",
            "NT",
            "NU",
            "ON",
            "PE",
            "QC",
            "SK",
            "YT",
        }:
            province = before_postal[-2:]
            before_postal = clean_value(before_postal[:-2])

        if before_postal and not re.match(r"^\d+\b", before_postal):
            city = before_postal

        for previous in reversed(lines[max(0, index - 3) : index]):
            if re.match(r"^\d+\b", previous) or STREET_PATTERN.search(previous):
                address_line = previous
                break
        break

    if address_line is None:
        for line in lines:
            if re.match(r"^\d+\b", line) and STREET_PATTERN.search(line):
                address_line = line
                break

    return {
        "address_line": address_line,
        "city": city,
        "province": province,
        "postal_code": postal_code,
    }


def extract_license_number(text: str, fallback_text: str | None = None) -> str | None:
    combined = "\n".join(part for part in [text, fallback_text or ""] if part)
    lines = lines_from(combined)

    for line in lines:
        labeled = value_after_label(
            line,
            ("LICENSE", "LICENCE", "LIC", "DL", "DLN", "DRIVER NUMBER", "NUMBER"),
        )
        if labeled:
            candidate = best_license_candidate(labeled)
            if candidate:
                return candidate

    return best_license_candidate(combined)


def best_license_candidate(text: str) -> str | None:
    candidates = []
    for match in LICENSE_PATTERN.finditer(text):
        candidate = clean_value(match.group(0)).replace(" ", "")
        compact = candidate.replace("-", "")
        if DATE_PATTERN.fullmatch(candidate):
            continue
        if POSTAL_PATTERN.fullmatch(candidate):
            continue
        if 12 <= len(compact) <= 17:
            candidates.append(candidate)

    dashed = [candidate for candidate in candidates if "-" in candidate]
    if dashed:
        return sorted(dashed, key=len, reverse=True)[0]
    return sorted(candidates, key=len, reverse=True)[0] if candidates else None


def extract_labeled_dates(lines: list[str]) -> dict[str, str | None]:
    values = {
        "issue_date": None,
        "expiry_date": None,
        "date_of_birth": None,
    }
    label_map = {
        "issue_date": ("ISS", "ISSUE", "ISSUED", "ISSUE DATE"),
        "expiry_date": ("EXP", "EXPIRY", "EXPIRES", "EXPIRY DATE"),
        "date_of_birth": ("DOB", "BIRTH", "DATE OF BIRTH"),
    }

    for line in lines:
        for key, labels in label_map.items():
            if values[key]:
                continue
            if any(re.search(rf"\b{re.escape(label)}\b", line, re.I) for label in labels):
                values[key] = first_date(line)

    all_dates = []
    for line in lines:
        all_dates.extend(normalize_date(match.group(0)) for match in DATE_PATTERN.finditer(line))

    for key, date in zip(
        [key for key, value in values.items() if value is None],
        [date for date in all_dates if date not in values.values()],
    ):
        values[key] = date

    return values


def first_date(text: str) -> str | None:
    match = DATE_PATTERN.search(text)
    return normalize_date(match.group(0)) if match else None


def normalize_date(value: str) -> str:
    return value.replace("/", "-")


def extract_labeled_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    for line in lines:
        value = value_after_label(line, labels)
        if value:
            return value
    return None


def extract_height(text: str) -> str | None:
    match = re.search(r"\b(?:HT|HGT|HEIGHT)?\s*[:#]?\s*(\d{3})\s?(?:CM|M)\b", text, re.I)
    if match:
        return f"{match.group(1)}CM"

    match = re.search(r"\b(?:HT|HGT|HEIGHT)?\s*[:#]?\s*([4-7]['’]\s?\d{1,2})\b", text, re.I)
    return match.group(1).replace("’", "'") if match else None


def extract_sex(lines: list[str]) -> str | None:
    for line in lines:
        value = value_after_label(line, ("SEX", "SEXE"))
        if value:
            match = re.search(r"\b([MFUX])\b", value)
            if match:
                return match.group(1)
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def typeform_answer_value(answer: dict[str, Any]) -> Any:
    answer_type = answer.get("type")
    if answer_type == "choice":
        choice = answer.get("choice") or {}
        return choice.get("label") or choice.get("other")
    if answer_type == "choices":
        choices = answer.get("choices") or {}
        return choices.get("labels") or choices.get("other")
    if answer_type == "number":
        return answer.get("number")
    if answer_type == "boolean":
        return answer.get("boolean")
    if answer_type:
        return answer.get(answer_type)
    return None


def flatten_typeform_answers(form_response: dict[str, Any]) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for answer in form_response.get("answers") or []:
        ref = (answer.get("field") or {}).get("ref")
        if ref:
            answers[ref] = typeform_answer_value(answer)
    return answers


def humanize_typeform_submission(raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
    form_response = raw_payload.get("form_response") or {}
    definition_fields = (form_response.get("definition") or {}).get("fields") or []
    titles_by_ref = {
        field.get("ref"): field.get("title")
        for field in definition_fields
        if field.get("ref")
    }

    items = []
    for answer in form_response.get("answers") or []:
        ref = (answer.get("field") or {}).get("ref")
        value = typeform_answer_value(answer)
        if value in (None, "", []):
            continue
        items.append({"label": titles_by_ref.get(ref, ref or "Answer"), "value": value})
    return items


def intake_summary_from_client(client: dict[str, object]) -> dict[str, object]:
    client_id = str(client["id"])
    front_fields = db.get_ocr_fields(client_id, "front")
    voice_intake = db.get_or_init_voice_intake(client_id)
    return {
        "intake_id": client_id,
        "created_at": client["created_at"],
        "client_type": client["client_type"],
        "name": client.get("full_name") or front_fields.get("full_name"),
        "license_number": front_fields.get("license_number"),
        "date_of_birth": front_fields.get("date_of_birth"),
        "voice_status": voice_intake.get("status", "not_started"),
        "status": client.get("status") or "pending",
    }


def build_intake_response(intake_id: str) -> dict[str, object]:
    client = db.get_client(intake_id)
    files_map = db.get_files(intake_id)
    front_file = files_map.get("license_front")
    back_file = files_map.get("license_back")
    articles_file = files_map.get("articles")

    typeform_submissions = [
        {
            "source": submission["source"],
            "received_at": submission["received_at"],
            "answers": humanize_typeform_submission(submission["raw_payload"]),
        }
        for submission in db.list_typeform_submissions(intake_id)
    ]

    return {
        "intake_id": intake_id,
        "created_at": client["created_at"] if client else None,
        "client_type": client["client_type"] if client else None,
        "files": {
            "license_front": front_file["file_path"] if front_file else None,
            "license_back": back_file["file_path"] if back_file else None,
            "articles": articles_file["file_path"] if articles_file else None,
        },
        "ocr": {
            "front": {
                "raw_text": (front_file or {}).get("raw_ocr_text") or "",
                "fields": db.get_ocr_fields(intake_id, "front"),
            },
            "back": {
                "raw_text": (back_file or {}).get("raw_ocr_text") or "",
                "crop_text": (back_file or {}).get("crop_ocr_text") or "",
                "fields": db.get_ocr_fields(intake_id, "back"),
            },
        },
        "voice_intake": db.get_or_init_voice_intake(intake_id),
        "client": (
            {
                "full_name": client.get("full_name"),
                "email": client.get("email"),
                "phone": client.get("phone"),
                "client_type": client.get("client_type"),
                "status": client.get("status"),
                "created_at": client.get("created_at"),
                "updated_at": client.get("updated_at"),
            }
            if client
            else None
        ),
        "typeform_submissions": typeform_submissions,
    }


def compact_message(message: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "role",
        "message",
        "content",
        "transcript",
        "transcriptType",
        "time",
        "secondsFromStart",
        "createdAt",
        "endedAt",
    }
    return {key: value for key, value in message.items() if key in allowed}


def first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def find_nested_value(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item not in (None, ""):
                return item
        for item in value.values():
            found = find_nested_value(item, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_nested_value(item, keys)
            if found not in (None, ""):
                return found
    return None


def find_intake_id(payload: dict[str, Any]) -> str | None:
    value = find_nested_value(payload, {"intake_id", "intakeId", "intakeID"})
    return str(value) if value else None


def extract_call_id(message: dict[str, Any]) -> str | None:
    call = message.get("call")
    if isinstance(call, dict):
        call_id = first_string(call.get("id"), call.get("callId"))
        if call_id:
            return call_id
    return first_string(message.get("callId"), message.get("id"))


def extract_analysis(message: dict[str, Any]) -> dict[str, Any]:
    analysis = message.get("analysis")
    if isinstance(analysis, dict):
        return analysis

    call = message.get("call")
    if isinstance(call, dict) and isinstance(call.get("analysis"), dict):
        return call["analysis"]
    return {}


def extract_artifact(message: dict[str, Any]) -> dict[str, Any]:
    artifact = message.get("artifact")
    if isinstance(artifact, dict):
        return artifact

    call = message.get("call")
    if isinstance(call, dict) and isinstance(call.get("artifact"), dict):
        return call["artifact"]
    return {}


def normalize_message_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    messages = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = first_string(item.get("message"), item.get("content"), item.get("transcript"))
        if role and text:
            messages.append({**compact_message(item), "role": role, "message": text})
    return messages


def structured_answers_from(analysis: dict[str, Any]) -> dict[str, Any]:
    structured = analysis.get("structuredData")
    if isinstance(structured, dict):
        return structured
    return {}


def list_from_structured(structured: dict[str, Any], key: str) -> list[Any]:
    value = structured.get(key)
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def apply_vapi_message(voice_intake: dict[str, object], message: dict[str, Any]) -> None:
    message_type = str(message.get("type") or "unknown")
    call_id = extract_call_id(message)
    if call_id:
        voice_intake["call_id"] = call_id

    voice_intake["last_event_at"] = utc_now()

    if message_type == "status-update":
        status = first_string(message.get("status"))
        if status:
            voice_intake["status"] = status
        if status in {"in-progress", "started"} and not voice_intake.get("started_at"):
            voice_intake["started_at"] = utc_now()
        if status == "ended" and not voice_intake.get("ended_at"):
            voice_intake["ended_at"] = utc_now()

    elif message_type in {"transcript", 'transcript[transcriptType="final"]'}:
        transcript = first_string(message.get("transcript"), message.get("originalTranscript"))
        if transcript:
            event = compact_message(message)
            event["transcript"] = transcript
            voice_intake["transcript_events"].append(event)
            if message.get("transcriptType") == "final":
                voice_intake["messages"].append(
                    {
                        "role": message.get("role", "user"),
                        "message": transcript,
                    }
                )

    elif message_type == "conversation-update":
        messages = normalize_message_list(message.get("messages"))
        if messages:
            voice_intake["messages"] = messages

    elif message_type == "end-of-call-report":
        voice_intake["status"] = "ended"
        voice_intake["ended_at"] = first_string(message.get("endedAt")) or utc_now()
        voice_intake["ended_reason"] = first_string(
            message.get("endedReason"), message.get("ended_reason")
        )

        artifact = extract_artifact(message)
        artifact_messages = normalize_message_list(artifact.get("messages"))
        if artifact_messages:
            voice_intake["messages"] = artifact_messages

        transcript = artifact.get("transcript")
        if isinstance(transcript, str) and transcript.strip():
            voice_intake["transcript"] = transcript.strip()
        elif isinstance(message.get("transcript"), str) and message["transcript"].strip():
            voice_intake["transcript"] = message["transcript"].strip()

        analysis = extract_analysis(message)
        voice_intake["summary"] = first_string(analysis.get("summary"), message.get("summary"))
        structured = structured_answers_from(analysis)
        voice_intake["structured_answers"] = structured
        voice_intake["success_evaluation"] = analysis.get("successEvaluation")
        voice_intake["missing_information"] = list_from_structured(
            structured, "missing_information"
        )
        voice_intake["urgent_deadline_flags"] = list_from_structured(
            structured, "urgent_deadline_flags"
        )
        voice_intake["attorney_review_notes"] = list_from_structured(
            structured, "attorney_review_notes"
        )


def apply_client_voice_event(
    voice_intake: dict[str, object], event_type: str, payload: dict[str, Any]
) -> None:
    call_id = first_string(payload.get("call_id"), payload.get("callId"))
    if call_id:
        voice_intake["call_id"] = call_id

    if event_type == "call-start":
        voice_intake["status"] = "in-progress"
        voice_intake["started_at"] = voice_intake.get("started_at") or utc_now()
    elif event_type == "call-end":
        voice_intake["status"] = "ended"
        voice_intake["ended_at"] = voice_intake.get("ended_at") or utc_now()
    elif event_type == "error":
        voice_intake["status"] = "error"
    elif event_type == "vapi-message":
        message = payload.get("message")
        if isinstance(message, dict):
            apply_vapi_message(voice_intake, message)
            return

    event = {
        "type": event_type,
        "received_at": utc_now(),
        "call_id": call_id,
    }
    if isinstance(payload.get("message"), str):
        event["message"] = payload["message"]
    voice_intake["client_events"].append(event)
    voice_intake["last_event_at"] = utc_now()


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "tesseract_available": tesseract_available(),
        "upload_dir": str(UPLOAD_DIR),
        "vapi": {
            "assistant_configured": bool(VAPI_ASSISTANT_ID),
            "webhook_secret_configured": bool(VAPI_WEBHOOK_SECRET),
        },
        "typeform": {
            "form1_configured": bool(TYPEFORM_FORM1_URL and TYPEFORM_FORM1_ID),
            "form2_configured": bool(TYPEFORM_FORM2_ID),
            "webhook_secret_configured": bool(TYPEFORM_WEBHOOK_SECRET),
        },
    }


@app.get("/api/clients/new")
def start_client() -> RedirectResponse:
    if not TYPEFORM_FORM1_URL:
        raise HTTPException(status_code=503, detail="Typeform Form 1 URL is not configured.")

    client_id = uuid.uuid4().hex
    db.upsert_client(client_id, status="pending", created_at=utc_now())
    separator = "&" if "?" in TYPEFORM_FORM1_URL else "?"
    return RedirectResponse(f"{TYPEFORM_FORM1_URL}{separator}client_token={client_id}", status_code=302)


def typeform_webhook_authorized(raw_body: bytes, signature: str | None) -> bool:
    if not TYPEFORM_WEBHOOK_SECRET:
        return True
    if not signature or not signature.startswith("sha256="):
        return False

    expected = hmac.new(TYPEFORM_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected_header = "sha256=" + base64.b64encode(expected).decode("utf-8")
    return hmac.compare_digest(expected_header, signature)


@app.post("/api/webhooks/typeform")
async def receive_typeform_webhook(
    request: Request,
    typeform_signature: Annotated[str | None, Header(alias="Typeform-Signature")] = None,
) -> dict[str, object]:
    raw_body = await request.body()
    if not typeform_webhook_authorized(raw_body, typeform_signature):
        raise HTTPException(status_code=401, detail="Invalid Typeform signature.")

    payload = json.loads(raw_body)
    form_response = payload.get("form_response") or {}
    form_id = form_response.get("form_id")
    response_token = form_response.get("token")
    hidden = form_response.get("hidden") or {}
    client_id = first_string(hidden.get("client_token")) or response_token

    if not client_id or not response_token:
        return {"status": "ignored", "reason": "missing client_token or response token"}

    if form_id == TYPEFORM_FORM1_ID:
        source = "typeform_1"
    elif form_id == TYPEFORM_FORM2_ID:
        source = "typeform_2"
    else:
        source = "typeform_unknown"

    db.upsert_client(client_id, created_at=utc_now())
    inserted = db.insert_submission(client_id, source, response_token, payload)
    if not inserted:
        return {"status": "ok", "reason": "duplicate", "client_id": client_id}

    answers = flatten_typeform_answers(form_response)
    db.upsert_client_from_typeform(client_id, source, answers)
    return {"status": "ok", "client_id": client_id, "source": source}


class StatusUpdate(BaseModel):
    status: Literal["pending", "in_progress", "ready_for_review", "approved", "rejected"]


@app.post("/api/intakes/{intake_id}/status")
def update_status(intake_id: str, body: StatusUpdate) -> dict[str, object]:
    if db.get_client(intake_id) is None:
        raise HTTPException(status_code=404, detail="Intake not found.")
    db.set_client_status(intake_id, body.status)
    return {"status": "ok", "client_status": body.status}


@app.get("/api/intakes")
def list_intakes() -> dict[str, object]:
    clients = db.list_clients()
    return {"intakes": [intake_summary_from_client(client) for client in clients]}


@app.get("/api/intakes/{intake_id}")
def get_intake(intake_id: str) -> dict[str, object]:
    if db.get_client(intake_id) is None:
        raise HTTPException(status_code=404, detail="Intake not found.")
    return build_intake_response(intake_id)


@app.get("/api/intakes/{intake_id}/files/{file_key}")
def get_intake_file(intake_id: str, file_key: str) -> FileResponse:
    if file_key not in FILE_KEYS:
        raise HTTPException(status_code=404, detail="File not found.")

    file_row = db.get_files(intake_id).get(file_key)
    if not file_row:
        raise HTTPException(status_code=404, detail="File not found.")

    path = UPLOAD_DIR / intake_id / file_row["file_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(path)


@app.post("/api/intakes/{intake_id}/voice-events")
async def update_voice_event(intake_id: str, request: Request) -> dict[str, object]:
    if db.get_client(intake_id) is None:
        raise HTTPException(status_code=404, detail="Intake not found.")

    payload = await request.json()
    event_type = first_string(payload.get("type"), payload.get("event")) or "unknown"
    voice_intake = db.get_or_init_voice_intake(intake_id)
    apply_client_voice_event(voice_intake, event_type, payload)
    db.update_voice_intake(intake_id, voice_intake)
    return {"status": "ok", "voice_intake": voice_intake}


def webhook_authorized(
    request: Request,
    x_vapi_secret: str | None,
    authorization: str | None,
) -> bool:
    if not VAPI_WEBHOOK_SECRET:
        return True

    query_secret = request.query_params.get("secret")
    bearer_token = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:].strip()

    return any(
        secrets.compare_digest(candidate, VAPI_WEBHOOK_SECRET)
        for candidate in [x_vapi_secret or "", query_secret or "", bearer_token]
    )


@app.post("/api/webhooks/vapi")
async def receive_vapi_webhook(
    request: Request,
    x_vapi_secret: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if not webhook_authorized(request, x_vapi_secret, authorization):
        raise HTTPException(status_code=401, detail="Invalid Vapi webhook secret.")

    payload = await request.json()
    message = payload.get("message", payload)
    if not isinstance(message, dict):
        return {"status": "ignored", "reason": "missing message"}

    intake_id = find_intake_id(payload)
    if not intake_id:
        return {"status": "ignored", "reason": "missing intake_id"}

    if db.get_client(intake_id) is None:
        return {"status": "ignored", "reason": "unknown intake_id"}

    voice_intake = db.get_or_init_voice_intake(intake_id)
    apply_vapi_message(voice_intake, message)
    db.update_voice_intake(intake_id, voice_intake)
    return {
        "status": "ok",
        "intake_id": intake_id,
        "message_type": message.get("type"),
    }


@app.post("/api/intakes")
async def create_intake(
    client_type: Annotated[str, Form()],
    license_front: Annotated[UploadFile, File()],
    license_back: Annotated[UploadFile, File()],
    articles: Annotated[UploadFile | None, File()] = None,
    client_token: Annotated[str | None, Form()] = None,
) -> dict[str, object]:
    normalized_client_type = client_type.strip().lower()

    if normalized_client_type not in ALLOWED_CLIENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail="client_type must be either 'individual' or 'entity'.",
        )

    if normalized_client_type == "entity" and articles is None:
        raise HTTPException(
            status_code=422,
            detail="articles file is required when client_type is 'entity'.",
        )

    intake_id = (client_token or "").strip() or str(uuid.uuid4())
    intake_dir = UPLOAD_DIR / intake_id

    try:
        front_path = await save_upload(license_front, intake_dir, "license-front.jpg")
        back_path = await save_upload(license_back, intake_dir, "license-back.jpg")
        articles_path = None

        if articles is not None:
            articles_path = await save_upload(articles, intake_dir, "articles")

        front_ocr = extract_license(front_path, "front")
        back_ocr = extract_license(back_path, "back")
    except HTTPException:
        if intake_dir.exists():
            shutil.rmtree(intake_dir, ignore_errors=True)
        raise
    except Exception as exc:
        if intake_dir.exists():
            shutil.rmtree(intake_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    db.upsert_client(
        intake_id,
        client_type=normalized_client_type,
        status="ready_for_review",
        created_at=utc_now(),
    )
    db.upsert_file(
        intake_id, "license_front", front_path.name, raw_ocr_text=front_ocr["raw_text"]
    )
    db.upsert_file(
        intake_id,
        "license_back",
        back_path.name,
        raw_ocr_text=back_ocr["raw_text"],
        crop_ocr_text=back_ocr.get("crop_text"),
    )
    if articles_path is not None:
        db.upsert_file(intake_id, "articles", articles_path.name)

    db.upsert_ocr_fields(intake_id, "front", front_ocr["fields"])
    db.upsert_ocr_fields(intake_id, "back", back_ocr["fields"])
    db.insert_submission(intake_id, "kyc_app", intake_id, {"client_type": normalized_client_type})
    db.get_or_init_voice_intake(intake_id)

    return build_intake_response(intake_id)
