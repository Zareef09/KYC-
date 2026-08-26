<img width="1920" height="960" alt="Screenshot 2026-08-26 at 3 02 39 PM" src="https://github.com/user-attachments/assets/07c06841-8aeb-4646-879d-95e9bb92c202" />
# KYC Intake Prototype

A hackathon-friendly client onboarding prototype with a React camera flow and a FastAPI backend that stores uploaded files temporarily and runs local Tesseract OCR on driver's license photos.

## What's changed

- Added Vapi-powered wrongful termination voice intake after KYC submission.
- Added backend webhook handling for Vapi status, transcript, conversation, and end-of-call analysis events.
- Stored voice intake status, call IDs, transcript messages, summaries, structured answers, missing information, urgent deadline flags, and attorney review notes in each local intake record.
- Added a browser-side Vapi call flow that passes intake context into the assistant and syncs local call events back to FastAPI.
- Expanded the admin dashboard with voice-intake status, call details, structured legal-intake answers, transcript review, and OCR/file review in one place.
- Added local environment examples and a `scripts/setup_vapi_assistant.py` helper for creating or updating the Vapi assistant with privacy-oriented artifact settings.\

## Requirements

- Node.js 22+
- Python 3.14+
- Tesseract OCR

On macOS, install Tesseract with:

```sh
brew install tesseract
```

## Backend

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`.

Useful endpoints:

- `GET /api/health`
- `GET /api/intakes`
- `GET /api/intakes/{intake_id}`
- `GET /api/intakes/{intake_id}/files/{file_key}`
- `POST /api/intakes`
- `POST /api/intakes/{intake_id}/voice-events`
- `POST /api/webhooks/vapi`

Uploads are written to `backend/uploads/{intake_id}/`, which is ignored by git.

### Vapi voice intake

Private Vapi credentials belong in local environment files only. Copy the examples and
fill them in locally:

```sh
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Backend variables:

- `VAPI_PRIVATE_API_KEY`: private Vapi API key used only by the setup script.
- `VAPI_ASSISTANT_ID`: existing assistant ID to update; omit to create a new assistant.
- `VAPI_WEBHOOK_SECRET`: shared secret accepted by the webhook through the `secret` query parameter, `X-Vapi-Secret`, or bearer token.
- `VAPI_SERVER_URL`: public HTTPS webhook URL used by the setup script.

Frontend variables:

- `VITE_API_BASE_URL`: FastAPI base URL.
- `VITE_VAPI_PUBLIC_API_KEY`: public browser key for `@vapi-ai/web`.
- `VITE_VAPI_ASSISTANT_ID`: assistant ID used by the browser call flow.

Create or update the wrongful termination intake assistant with:

```sh
VAPI_PRIVATE_API_KEY=... \
VAPI_SERVER_URL=https://your-public-url.example.com/api/webhooks/vapi \
VAPI_WEBHOOK_SECRET=... \
python scripts/setup_vapi_assistant.py
```

The script enables assistant-level `compliancePlan.hipaaEnabled`, disables Vapi
recording/logging artifacts, and configures webhook events so transcripts and
structured answers can be stored locally in each intake record.

For local webhook testing, expose FastAPI through a tunnel or use Vapi CLI forwarding
to `http://localhost:8000/api/webhooks/vapi`.

When `VAPI_WEBHOOK_SECRET` is set, the setup script appends it as `?secret=...` to
the configured server URL. The FastAPI webhook also accepts the same value through
`X-Vapi-Secret` or `Authorization: Bearer ...`.

## Frontend

```sh
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173`.

Camera capture works from `localhost` in modern browsers. If the browser blocks camera access, allow camera permission and refresh the page.

The admin dashboard is available at `http://localhost:5173/admin`.

## Intake Flow

1. Capture the front of the license.
2. Capture the back of the license.
3. Choose individual or entity.
4. If entity, upload articles of incorporation.
5. Submit to FastAPI and review OCR output.
6. Start the Vapi web voice call for wrongful termination intake.
7. Review OCR and locally stored voice-intake answers in `/admin`.

<img width="1920" height="960" alt="Screenshot 2026-08-26 at 3 02 39 PM" src="https://github.com/user-attachments/assets/e9acedd8-384e-4474-8ac8-711a8a420d02" />

<img width="1920" height="958" alt="Screenshot 2026-08-26 at 3 03 03 PM" src="https://github.com/user-attachments/assets/221376e5-ed08-4465-a224-e81a098e58a9" />


