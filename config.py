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
