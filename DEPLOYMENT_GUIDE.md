# PMP Quiz (English) — Railway Deployment Guide

## 1. Push to GitHub

```bash
cd PMP_Quiz_EN

# Create a new GitHub repo (private recommended)
gh repo create pmp-quiz-en --private --source=. --push

# Or manually:
git remote add origin https://github.com/YOUR_USERNAME/pmp-quiz-en.git
git branch -M main
git push -u origin main
```

## 2. Deploy to Railway

1. Go to https://railway.app and log in (or sign up)
2. Click **"New Project"** > **"Deploy from GitHub Repo"**
3. Select your `pmp-quiz-en` repository
4. Railway will auto-detect the Dockerfile and start building

### Set Environment Variables

In Railway project dashboard > **Variables** tab, add:

| Variable | Value |
|----------|-------|
| `SECRET_KEY` | (generate a random string — `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `ADMIN_USERNAME` | Your admin email (e.g., `admin@pmpquiz.com`) |
| `PURCHASE_URL` | Your Gumroad or Payhip product link |
| `PORT` | `5000` |

### Load Question Data

After first deploy, open Railway's **shell** (or use `railway run`):

```bash
python load_data.py PMP_Raw.xlsx
```

This loads all 2,174+ questions into the SQLite database.

## 3. Custom Domain Setup

### Get Railway Domain First

1. In Railway dashboard > **Settings** > **Networking**
2. Click **"Generate Domain"** to get a `*.up.railway.app` URL
3. Verify the app works at this URL

### Connect Your Custom Domain

1. In Railway > **Settings** > **Networking** > **Custom Domain**
2. Enter your domain (e.g., `pmpquiz.com` or `quiz.pmpquiz.com`)
3. Railway will show DNS records to add

### DNS Configuration

At your domain registrar (Namecheap, GoDaddy, Cloudflare, etc.):

**For root domain (pmpquiz.com):**
- Type: `CNAME` (or `ALIAS`/`ANAME` if supported)
- Name: `@`
- Value: `YOUR_APP.up.railway.app`

**For subdomain (quiz.pmpquiz.com):**
- Type: `CNAME`
- Name: `quiz`
- Value: `YOUR_APP.up.railway.app`

SSL certificate is automatically provisioned by Railway.

## 4. Gumroad / Payhip Setup

### Option A: Gumroad
1. Create product at https://gumroad.com
2. Set your price and product details
3. Copy the product URL
4. Set `PURCHASE_URL` env var in Railway to this URL

### Option B: Payhip
1. Create product at https://payhip.com
2. Set your price and product details
3. Copy the product URL
4. Set `PURCHASE_URL` env var in Railway to this URL

### After Purchase Flow
When a customer purchases, you manually upgrade their account:
1. Log in as admin
2. Go to Admin dashboard
3. Find the user by email
4. Change plan from "Free" to "Paid"
5. Set expiration date (or leave blank for lifetime)

## 5. File Structure

```
PMP_Quiz_EN/
├── app.py              # Main Flask application
├── load_data.py        # Excel to SQLite loader
├── requirements.txt    # Python dependencies
├── Dockerfile          # Railway deployment config
├── .gitignore
├── PMP_Raw.xlsx        # Question data (2,174+ questions)
├── data/               # SQLite DB (auto-created)
└── templates/
    ├── base.html           # Layout + navbar + dark mode
    ├── landing.html        # Public landing page
    ├── login.html
    ├── register.html
    ├── dashboard.html      # User dashboard
    ├── quiz_start.html     # Quiz settings
    ├── quiz_question.html  # Question display
    ├── quiz_answer_review.html
    ├── quiz_result.html
    ├── wrong_answers.html
    ├── bookmarks.html
    ├── stats.html          # Personal statistics
    ├── global_stats.html   # Global leaderboard
    └── admin.html          # Admin panel
```

## Key Changes from Korean Version

- All UI text translated to English
- Korean translation toggle (한국어 보기) removed
- Korean DB columns (question_kr, opt_a_kr, etc.) removed from schema
- Naver Smart Store links replaced with `PURCHASE_URL` env variable
- Payment buttons styled generically (orange/gold) instead of Naver green
- `load_data.py` no longer imports Korean translation columns
