from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_lock = threading.Lock()
_connection: sqlite3.Connection | None = None

_JSON_LIST_COLUMNS = (
    "transcript_events",
    "messages",
    "missing_information",
    "urgent_deadline_flags",
    "attorney_review_notes",
    "client_events",
)
_JSON_DICT_COLUMNS = ("structured_answers",)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Database not initialized; call init_db() first.")
    return _connection


def init_db(db_path: Path) -> None:
    global _connection
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    connection.commit()
    _connection = connection


def upsert_client(
    client_id: str,
    *,
    client_type: str | None = None,
    status: str | None = None,
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    created_at: str | None = None,
) -> None:
    connection = get_connection()
    now = _utc_now()
    with _lock:
        existing = connection.execute(
            "SELECT id FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO clients
                    (id, client_type, status, full_name, email, phone, created_at, updated_at)
                VALUES (?, ?, COALESCE(?, 'pending'), ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    client_type,
                    status,
                    full_name,
                    email,
                    phone,
                    created_at or now,
                    now,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE clients
                SET client_type = COALESCE(?, client_type),
                    status = COALESCE(?, status),
                    full_name = COALESCE(?, full_name),
                    email = COALESCE(?, email),
                    phone = COALESCE(?, phone),
                    updated_at = ?
                WHERE id = ?
                """,
                (client_type, status, full_name, email, phone, now, client_id),
            )
        connection.commit()


def set_client_status(client_id: str, status: str) -> None:
    upsert_client(client_id, status=status)


def get_client(client_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    row = connection.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def list_clients() -> list[dict[str, Any]]:
    connection = get_connection()
    rows = connection.execute("SELECT * FROM clients ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def insert_submission(
    client_id: str, source: str, external_id: str | None, raw_payload: dict[str, Any]
) -> bool:
    connection = get_connection()
    now = _utc_now()
    with _lock:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO submissions
                (client_id, source, external_id, raw_payload, received_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (client_id, source, external_id, json.dumps(raw_payload), now),
        )
        connection.commit()
        return cursor.rowcount > 0


def list_submissions(client_id: str) -> list[dict[str, Any]]:
    connection = get_connection()
    rows = connection.execute(
        "SELECT * FROM submissions WHERE client_id = ? ORDER BY received_at", (client_id,)
    ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["raw_payload"] = json.loads(item["raw_payload"])
        results.append(item)
    return results


def list_typeform_submissions(client_id: str) -> list[dict[str, Any]]:
    return [item for item in list_submissions(client_id) if item["source"].startswith("typeform_")]


def upsert_client_from_typeform(client_id: str, source: str, answers: dict[str, Any]) -> None:
    if source != "typeform_1":
        return
    upsert_client(
        client_id,
        full_name=answers.get("full_name"),
        email=answers.get("email"),
        phone=answers.get("phone"),
        client_type=answers.get("client_type"),
        status="in_progress",
    )


def upsert_ocr_fields(client_id: str, side: str, fields: dict[str, Any]) -> None:
    connection = get_connection()
    now = _utc_now()
    with _lock:
        for field_name, value in fields.items():
            connection.execute(
                """
                INSERT INTO ocr_fields (client_id, side, field_name, value, confidence, created_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                ON CONFLICT(client_id, side, field_name) DO UPDATE SET value = excluded.value
                """,
                (client_id, side, field_name, None if value is None else str(value), now),
            )
        connection.commit()


def get_ocr_fields(client_id: str, side: str) -> dict[str, str | None]:
    connection = get_connection()
    rows = connection.execute(
        "SELECT field_name, value FROM ocr_fields WHERE client_id = ? AND side = ?",
        (client_id, side),
    ).fetchall()
    return {row["field_name"]: row["value"] for row in rows}


def upsert_file(
    client_id: str,
    file_key: str,
    file_path: str,
    *,
    raw_ocr_text: str | None = None,
    crop_ocr_text: str | None = None,
) -> None:
    connection = get_connection()
    now = _utc_now()
    with _lock:
        connection.execute(
            """
            INSERT INTO files (client_id, file_key, file_path, raw_ocr_text, crop_ocr_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id, file_key) DO UPDATE SET
                file_path = excluded.file_path,
                raw_ocr_text = excluded.raw_ocr_text,
                crop_ocr_text = excluded.crop_ocr_text
            """,
            (client_id, file_key, file_path, raw_ocr_text, crop_ocr_text, now),
        )
        connection.commit()


def get_files(client_id: str) -> dict[str, dict[str, Any]]:
    connection = get_connection()
    rows = connection.execute("SELECT * FROM files WHERE client_id = ?", (client_id,)).fetchall()
    return {row["file_key"]: dict(row) for row in rows}


def _voice_intake_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in _JSON_LIST_COLUMNS:
        data[key] = json.loads(data[key]) if data[key] else []
    for key in _JSON_DICT_COLUMNS:
        data[key] = json.loads(data[key]) if data[key] else {}
    data.pop("updated_at", None)
    return data


def get_or_init_voice_intake(client_id: str) -> dict[str, Any]:
    connection = get_connection()
    row = connection.execute(
        "SELECT * FROM voice_intake WHERE client_id = ?", (client_id,)
    ).fetchone()
    if row is None:
        with _lock:
            connection.execute(
                "INSERT OR IGNORE INTO voice_intake (client_id, updated_at) VALUES (?, ?)",
                (client_id, _utc_now()),
            )
            connection.commit()
        row = connection.execute(
            "SELECT * FROM voice_intake WHERE client_id = ?", (client_id,)
        ).fetchone()
    return _voice_intake_row_to_dict(row)


def update_voice_intake(client_id: str, voice_intake: dict[str, Any]) -> None:
    connection = get_connection()
    now = _utc_now()
    with _lock:
        connection.execute(
            """
            UPDATE voice_intake SET
                call_id = ?, status = ?, started_at = ?, ended_at = ?, ended_reason = ?,
                transcript = ?, transcript_events = ?, messages = ?, summary = ?,
                structured_answers = ?, success_evaluation = ?,
                missing_information = ?, urgent_deadline_flags = ?, attorney_review_notes = ?,
                client_events = ?, last_event_at = ?, updated_at = ?
            WHERE client_id = ?
            """,
            (
                voice_intake.get("call_id"),
                voice_intake.get("status", "not_started"),
                voice_intake.get("started_at"),
                voice_intake.get("ended_at"),
                voice_intake.get("ended_reason"),
                voice_intake.get("transcript"),
                json.dumps(voice_intake.get("transcript_events", [])),
                json.dumps(voice_intake.get("messages", [])),
                voice_intake.get("summary"),
                json.dumps(voice_intake.get("structured_answers", {})),
                voice_intake.get("success_evaluation"),
                json.dumps(voice_intake.get("missing_information", [])),
                json.dumps(voice_intake.get("urgent_deadline_flags", [])),
                json.dumps(voice_intake.get("attorney_review_notes", [])),
                json.dumps(voice_intake.get("client_events", [])),
                voice_intake.get("last_event_at"),
                now,
                client_id,
            ),
        )
        connection.commit()
