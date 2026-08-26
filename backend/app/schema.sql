CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    client_type TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    full_name TEXT,
    email TEXT,
    phone TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL REFERENCES clients(id),
    source TEXT NOT NULL,
    external_id TEXT,
    raw_payload TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS ocr_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL REFERENCES clients(id),
    side TEXT NOT NULL,
    field_name TEXT NOT NULL,
    value TEXT,
    confidence REAL,
    created_at TEXT NOT NULL,
    UNIQUE(client_id, side, field_name)
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL REFERENCES clients(id),
    file_key TEXT NOT NULL,
    file_path TEXT NOT NULL,
    raw_ocr_text TEXT,
    crop_ocr_text TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(client_id, file_key)
);

CREATE TABLE IF NOT EXISTS voice_intake (
    client_id TEXT PRIMARY KEY REFERENCES clients(id),
    call_id TEXT,
    status TEXT NOT NULL DEFAULT 'not_started',
    started_at TEXT,
    ended_at TEXT,
    ended_reason TEXT,
    transcript TEXT,
    transcript_events TEXT NOT NULL DEFAULT '[]',
    messages TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    structured_answers TEXT NOT NULL DEFAULT '{}',
    success_evaluation TEXT,
    missing_information TEXT NOT NULL DEFAULT '[]',
    urgent_deadline_flags TEXT NOT NULL DEFAULT '[]',
    attorney_review_notes TEXT NOT NULL DEFAULT '[]',
    client_events TEXT NOT NULL DEFAULT '[]',
    last_event_at TEXT,
    updated_at TEXT NOT NULL
);
