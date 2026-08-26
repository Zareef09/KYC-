from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402

UPLOAD_DIR = BACKEND_DIR / "uploads"
DB_PATH = BACKEND_DIR / "data.db"


def migrate_record(record: dict) -> None:
    intake_id = record["intake_id"]
    db.upsert_client(
        intake_id,
        client_type=record.get("client_type"),
        status="ready_for_review",
        created_at=record.get("created_at"),
    )

    ocr = record.get("ocr") or {}
    front = ocr.get("front") or {}
    back = ocr.get("back") or {}
    files = record.get("files") or {}

    if files.get("license_front"):
        db.upsert_file(
            intake_id,
            "license_front",
            files["license_front"],
            raw_ocr_text=front.get("raw_text"),
        )
    if files.get("license_back"):
        db.upsert_file(
            intake_id,
            "license_back",
            files["license_back"],
            raw_ocr_text=back.get("raw_text"),
            crop_ocr_text=back.get("crop_text"),
        )
    if files.get("articles"):
        db.upsert_file(intake_id, "articles", files["articles"])

    db.upsert_ocr_fields(intake_id, "front", front.get("fields") or {})
    db.upsert_ocr_fields(intake_id, "back", back.get("fields") or {})

    db.insert_submission(
        intake_id, "kyc_app", intake_id, {"client_type": record.get("client_type")}
    )

    voice_intake = record.get("voice_intake")
    if isinstance(voice_intake, dict):
        db.get_or_init_voice_intake(intake_id)
        db.update_voice_intake(intake_id, voice_intake)


def main() -> None:
    db.init_db(DB_PATH)
    record_paths = sorted(UPLOAD_DIR.glob("*/record.json"))
    if not record_paths:
        print(f"No existing record.json files found under {UPLOAD_DIR}")
        return

    migrated = 0
    for path in record_paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            migrate_record(record)
            migrated += 1
        except Exception as exc:
            print(f"Failed to migrate {path}: {exc}")

    print(f"Migrated {migrated}/{len(record_paths)} record(s) into {DB_PATH}")


if __name__ == "__main__":
    main()
