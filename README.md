# Bragi Health Portal

A secure, multi-role clinical records portal for patients, doctors, administrators, and emergency responders. Bragi lets patients own and share their medical history, enables doctors to review lab results and notes, and provides emergency access under strict audit controls.

---

## Roles

| Role | Access |
|---|---|
| **Patient** | Upload documents, manage medications, control record sharing, emergency consent |
| **Doctor** | View approved patient records, add clinical notes, manage access requests |
| **PCP / Family doctor** | Same as doctor + dedicated PCP workspace with multi-patient tab system |
| **Admin** | User management, document verification, access approval |
| **Care partner** | View shared structured lab pages for linked patient |
| **Emergency** | Read-only time-limited access to consented patients; full audit trail |

---

## Tech stack

- **Backend**: FastAPI + SQLAlchemy (PostgreSQL), JWT auth, Google Document AI for document parsing
- **Frontend**: Next.js (App Router), localStorage auth
- **Deployment**: Render (backend), Vercel / static hosting (frontend)

---

## Local development setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL database

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in values
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local  # fill in values
npm run dev
```

---

## Environment variables

See `backend/.env.example` for the full list. The minimum required for local dev:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | JWT signing key (32+ chars, random) |
| `ENVIRONMENT` | Set to `development` to allow weak `SECRET_KEY` locally |
| `NEXT_PUBLIC_API_URL` | Frontend → backend base URL |

> **Security note**: Never commit real credentials. The server will refuse to start in production if `SECRET_KEY` is missing, uses the default value, or is shorter than 32 characters.

---

## Medical disclaimer

Bragi Health Portal is a **records management tool**, not a diagnostic or clinical decision system. It does not diagnose conditions, recommend treatments, or prescribe medications. All information displayed is patient-entered or extracted from uploaded source documents and must be reviewed by a qualified healthcare professional.
