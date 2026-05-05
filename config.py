import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'pmp-quiz-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///pmp_quiz.db')
    # Railway uses postgres:// but SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMIN_EMAILS = [e.strip() for e in os.environ.get('ADMIN_EMAILS', 'songdoinfo@naver.com').split(',')]
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'pmp-admin-2024!')
    FREE_QUESTION_LIMIT = 50
    PAYMENT_ENABLED = False  # Payment 비활성화 (Admin가 나중에 활성화)
    DEFAULT_VALIDITY_MONTHS = 3

    # ── Custom domain (used for canonical URL + redirect target) ──
    PRIMARY_HOST = os.environ.get('PRIMARY_HOST', 'pmp.wayexam.com')

    # ── Google AdSense (set in Railway env vars when ready) ──
    # ADSENSE_PUBLISHER_ID: 'ca-pub-1234567890' (account-wide)
    # ADSENSE_SLOT_INLINE: ad slot shown every 10 questions during quiz
    # ADSENSE_SLOT_RESULT: ad slot at top of grading-result page
    # If empty, no ads render anywhere on the site (graceful).
    ADSENSE_PUBLISHER_ID = os.environ.get('ADSENSE_PUBLISHER_ID', '')
    ADSENSE_SLOT_INLINE = os.environ.get('ADSENSE_SLOT_INLINE', '')
    ADSENSE_SLOT_RESULT = os.environ.get('ADSENSE_SLOT_RESULT', '')
