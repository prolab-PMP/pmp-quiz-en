# Railway deployment - pmp-quiz-en

## One-time setup
1. **Create new Railway project** -> https://railway.app -> Deploy from GitHub -> select `prolab-PMP/pmp-quiz-en`.
2. **Add PostgreSQL plugin** -> Railway auto-injects `DATABASE_URL`.
3. **Set env vars** (Service -> Variables):
   - `SECRET_KEY=<long-random>`
   - `FLASK_ENV=production`
   - `PAYMENT_ENABLED=False`
4. **Add custom domain** (Service -> Settings -> Networking) when ready.

## Auto-deploy
Railway redeploys every push to `main`.

## Seeding the questions DB
First deploy auto-creates empty tables. To copy questions from the Korean prod DB:
```bash
pg_dump --table=questions --data-only "<KO_DATABASE_URL>" > q.sql
psql "<EN_DATABASE_URL>" < q.sql
```

## CLI alternative
```bash
npm i -g @railway/cli
railway login
railway link        # link this folder to a Railway project
railway up          # deploy local code
```
