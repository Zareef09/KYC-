# KYC Intake Prototype

A hackathon-friendly client onboarding prototype with a React camera flow and a FastAPI backend that stores uploaded files temporarily and runs local Tesseract OCR on driver's license photos.

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
- `POST /api/intakes`

Uploads are written to `backend/uploads/{intake_id}/`, which is ignored by git.

## Frontend

```sh
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173`.

Camera capture works from `localhost` in modern browsers. If the browser blocks camera access, allow camera permission and refresh the page.

## Intake Flow

1. Capture the front of the license.
2. Capture the back of the license.
3. Choose individual or entity.
4. If entity, upload articles of incorporation.
5. Submit to FastAPI and review OCR output.
