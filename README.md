# Swaya

A self-directed learning platform for courses, lessons, assessments, assignments, and certificates.

## Run locally

```powershell
docker compose up --build
```

The app is available at `http://localhost:8000`. For a fresh local database, set `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD` in a local `.env` file before starting Compose. Never use a development password on a public deployment.

## Free cloud deployment

Swaya is configured for a free Render web service with Supabase Postgres and private Supabase Storage. The Render blueprint is in `render.yaml`.

1. Create a private or public GitHub repository and upload the application source, `Dockerfile`, `requirements.txt`, `render.yaml`, and `.dockerignore`. Do not upload `.env`, SQL dumps, ZIP backups, certificates, or local uploads.
2. In Render, create a Web Service from the repository (or deploy the Blueprint). Use the free plan.
3. Add these values to the Render service environment, using Render's secret fields:
   - `DATABASE_URL`: Supabase Session Pooler URL using the `postgresql+psycopg://` driver prefix and `sslmode=require`.
   - `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD`: the first Swaya administrator account.
   - `SUPABASE_SERVICE_ROLE_KEY`: Supabase's server-only secret key. Never use this key in browser code or commit it to GitHub.
4. Keep `SUPABASE_URL` and `SUPABASE_STORAGE_BUCKET` as defined in `render.yaml`. The bucket `swaya-uploads` must remain private.

Uploaded lesson media, assignment files, and certificate PDFs are stored in Supabase Storage. The free tier allows up to 50 MB per object and 1 GB total file storage. Render's free service can sleep when idle, and Supabase free projects may pause after a week of low activity; this setup is for a small pilot rather than a high-availability production service.

The cloud database starts fresh with the 30-day course seed and the administrator configured above. Local user accounts, progress, and uploaded files are not copied automatically.
