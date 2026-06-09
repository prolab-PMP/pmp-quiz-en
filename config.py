import os, secrets
from dotenv import load_dotenv

load_dotenv()

# ── Security: fail-fast in production if SECRET_KEY missing (#7) ──
_env_secret = os.environ.get('SECRET_KEY')
_is_production = os.environ.get('FLASK_ENV') == 'production' or os.environ.get('RAILWAY_ENVIRONMENT')
if not _env_secret and _is_production:
    raise RuntimeError(
        'SECURITY: SECRET_KEY environment variable is required in production. '
        'Set it in Railway env vars (use a 32+ char random string).'
    )
SECRET_KEY_VALUE = _env_secret or secrets.token_hex(32)

class Config:
    SECRET_KEY = SECRET_KEY_VALUE
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///pmp_quiz.db')
    # Railway uses postgres:// but SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMIN_EMAILS = [e.strip() for e in os.environ.get('ADMIN_EMAILS', 'songdoinfo@naver.com').split(',')]
    # Legacy password login path — disabled when env var unset (None)
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or None
    FREE_QUESTION_LIMIT = 50
    PAYMENT_ENABLED = False  # Payment 비활성화 (Admin가 나중에 활성화)
    DEFAULT_VALIDITY_MONTHS = 3

    # ── Secure cookie settings (#6) ──
    SESSION_COOKIE_SECURE = bool(_is_production)   # HTTPS-only in production
    SESSION_COOKIE_HTTPONLY = True                  # Block JS access (XSS defense)
    SESSION_COOKIE_SAMESITE = 'Lax'                 # Partial CSRF defense
    REMEMBER_COOKIE_SECURE = bool(_is_production)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 days

    # ── Custom domain (used for canonical URL + redirect target) ──
    PRIMARY_HOST = os.environ.get('PRIMARY_HOST', 'wayexam.com')
    PUBLIC_HOSTS = os.environ.get('PUBLIC_HOSTS', 'wayexam.com,www.wayexam.com,pmp.wayexam.com')

    # ── Google AdSense (set in Railway env vars when ready) ──
    # ADSENSE_PUBLISHER_ID: 'ca-pub-1234567890' (account-wide)
    # ADSENSE_SLOT_INLINE: ad slot shown every 10 questions during quiz
    # ADSENSE_SLOT_RESULT: ad slot at top of grading-result page
    # If empty, no ads render anywhere on the site (graceful).
    ADSENSE_PUBLISHER_ID = os.environ.get('ADSENSE_PUBLISHER_ID', '')
    ADSENSE_SLOT_INLINE = os.environ.get('ADSENSE_SLOT_INLINE', '')
    ADSENSE_SLOT_RESULT = os.environ.get('ADSENSE_SLOT_RESULT', '')
