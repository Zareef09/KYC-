from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
import pytesseract


BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
ALLOWED_CLIENT_TYPES = {"individual", "entity"}


app = FastAPI(
    title="KYC Intake API",
    description="Hackathon prototype API for license image collection and local OCR.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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


def extract_text(image_path: Path) -> dict[str, object]:
    try:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            text = pytesseract.image_to_string(image)
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

    return {
        "raw_text": text.strip(),
        "hints": parse_license_hints(text),
    }


def parse_license_hints(text: str) -> dict[str, list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_pattern = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
    license_pattern = re.compile(
        r"\b(?:licen[sc]e|lic|dl|id|document|customer)\b", re.IGNORECASE
    )
    address_pattern = re.compile(
        r"\b(?:street|st\.?|avenue|ave\.?|road|rd\.?|drive|dr\.?|court|ct\.?|"
        r"lane|ln\.?|blvd|boulevard|unit|apt|suite|postal|zip)\b",
        re.IGNORECASE,
    )
    name_pattern = re.compile(
        r"\b(?:name|surname|given|first|last|family)\b", re.IGNORECASE
    )

    return {
        "possible_names": [line for line in lines if name_pattern.search(line)][:5],
        "possible_addresses": [
            line for line in lines if address_pattern.search(line)
        ][:5],
        "possible_license_numbers": [
            line for line in lines if license_pattern.search(line)
        ][:5],
        "possible_dates": [line for line in lines if date_pattern.search(line)][:8],
    }


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "tesseract_available": tesseract_available(),
        "upload_dir": str(UPLOAD_DIR),
    }


@app.post("/api/intakes")
async def create_intake(
    client_type: Annotated[str, Form()],
    license_front: Annotated[UploadFile, File()],
    license_back: Annotated[UploadFile, File()],
    articles: Annotated[UploadFile | None, File()] = None,
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

    intake_id = str(uuid.uuid4())
    intake_dir = UPLOAD_DIR / intake_id

    try:
        front_path = await save_upload(license_front, intake_dir, "license-front.jpg")
        back_path = await save_upload(license_back, intake_dir, "license-back.jpg")
        articles_path = None

        if articles is not None:
            articles_path = await save_upload(articles, intake_dir, "articles")

        front_ocr = extract_text(front_path)
        back_ocr = extract_text(back_path)
    except HTTPException:
        if intake_dir.exists():
            shutil.rmtree(intake_dir, ignore_errors=True)
        raise
    except Exception as exc:
        if intake_dir.exists():
            shutil.rmtree(intake_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "intake_id": intake_id,
        "client_type": normalized_client_type,
        "files": {
            "license_front": front_path.name,
            "license_back": back_path.name,
            "articles": articles_path.name if articles_path else None,
        },
        "ocr": {
            "front": front_ocr,
            "back": back_ocr,
        },
    }
