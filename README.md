# PMP Quiz - English Edition

PMP Practice Question platform - English UI with multilingual question scaffolding (EN now; ZH / ES / JA stubs ready).

## Quick start (local dev)
```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
export SECRET_KEY="dev-secret"
python app.py
```

## Adding a new language
1. Populate `question_zh`, `options_zh`, `explanation_zh` (or `_es` / `_ja`) in the `questions` table.
2. Users pick a language from the navbar dropdown (cookie `lang`).
3. `Question.text_for(lang)` falls back to English if the locale field is NULL.

## Deploying to Railway
See RAILWAY_DEPLOY.md.
