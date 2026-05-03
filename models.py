from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))  # NEW: bcrypt hash (4+ chars plaintext). 기존 유저는 최초 Log in 시 설정.
    is_admin = db.Column(db.Boolean, default=False)
    is_premium = db.Column(db.Boolean, default=False)
    validity_start = db.Column(db.DateTime, default=datetime.utcnow)
    validity_end = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Relationships
    quiz_sessions = db.relationship('QuizSession', backref='user', lazy='dynamic')
    wrong_answers = db.relationship('WrongAnswer', backref='user', lazy='dynamic')
    answer_stats = db.relationship('UserAnswerStat', backref='user', lazy='dynamic')

    def is_valid(self):
        """Check if user subscription is valid"""
        if self.is_admin:
            return True
        if not self.is_premium:
            return False          # Free 등급이면 Valid until과 무관하게 차단
        if not self.validity_end:
            return False
        return datetime.utcnow() <= self.validity_end

    def set_validity(self, months=3):
        self.validity_start = datetime.utcnow()
        self.validity_end = datetime.utcnow() + timedelta(days=months * 30)

    def extend_validity(self, months=3):
        """현재 Valid until 종료day 기준으로 연장 (Expired된 경우 오늘부터 연장)"""
        base = self.validity_end if self.validity_end and self.validity_end > datetime.utcnow() else datetime.utcnow()
        if not self.validity_start:
            self.validity_start = datetime.utcnow()
        self.validity_end = base + timedelta(days=months * 30)

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    no = db.Column(db.Integer, unique=True, nullable=False, index=True)

    # English content
    question = db.Column(db.Text, nullable=False)
    opt_a = db.Column(db.Text)
    opt_b = db.Column(db.Text)
    opt_c = db.Column(db.Text)
    opt_d = db.Column(db.Text)
    opt_e = db.Column(db.Text)
    answer = db.Column(db.String(20), nullable=False)  # e.g., "A", "A, B", "A, B, C"
    explanation = db.Column(db.Text)

    # Korean content
    question_kr = db.Column(db.Text)
    opt_a_kr = db.Column(db.Text)
    opt_b_kr = db.Column(db.Text)
    opt_c_kr = db.Column(db.Text)
    opt_d_kr = db.Column(db.Text)
    opt_e_kr = db.Column(db.Text)
    explanation_kr = db.Column(db.Text)

    # 2021 ECO Classification (PMBOK 7)
    eco2021_domain = db.Column(db.String(100))
    eco2021_task = db.Column(db.String(200))

    # PMBOK 7th Edition Classification
    pmbok7_domain = db.Column(db.String(100))
    pmbok7_principle = db.Column(db.String(200))

    # Methodology
    methodology = db.Column(db.String(50))
    methodology_detail = db.Column(db.String(200))

    # 2026 ECO Classification (PMBOK 8)
    eco2026_domain = db.Column(db.String(100))
    eco2026_task = db.Column(db.String(200))

    # PMBOK 8th Edition Classification
    pmbok8_domain = db.Column(db.String(100))
    pmbok8_focus_area = db.Column(db.String(100))
    pmbok8_principle = db.Column(db.String(200))
    pmbok8_process = db.Column(db.String(200))
    pmbok8_new_topics = db.Column(db.String(100))

    def get_answer_list(self):
        """Return list of correct answers"""
        return [a.strip() for a in self.answer.split(',')]

    def get_answer_count(self):
        """Return number of correct answers"""
        return len(self.get_answer_list())

    # Multilingual content scaffolding (added by transform.py).
    # Original JSON-options columns are kept for backward compat but are unused —
    # the active per-language columns mirror KR structure (opt_a_xx ~ opt_e_xx).
    question_zh    = db.Column(db.Text)
    options_zh     = db.Column(db.JSON)   # deprecated: use opt_a_zh~opt_e_zh
    explanation_zh = db.Column(db.Text)
    question_es    = db.Column(db.Text)
    options_es     = db.Column(db.JSON)   # deprecated: use opt_a_es~opt_e_es
    explanation_es = db.Column(db.Text)
    question_ja    = db.Column(db.Text)
    options_ja     = db.Column(db.JSON)   # deprecated: use opt_a_ja~opt_e_ja
    explanation_ja = db.Column(db.Text)

    # Per-language individual option columns (KR-pattern, populated by translation pipeline)
    opt_a_zh = db.Column(db.Text)
    opt_b_zh = db.Column(db.Text)
    opt_c_zh = db.Column(db.Text)
    opt_d_zh = db.Column(db.Text)
    opt_e_zh = db.Column(db.Text)
    opt_a_es = db.Column(db.Text)
    opt_b_es = db.Column(db.Text)
    opt_c_es = db.Column(db.Text)
    opt_d_es = db.Column(db.Text)
    opt_e_es = db.Column(db.Text)
    opt_a_ja = db.Column(db.Text)
    opt_b_ja = db.Column(db.Text)
    opt_c_ja = db.Column(db.Text)
    opt_d_ja = db.Column(db.Text)
    opt_e_ja = db.Column(db.Text)

    def text_for(self, lang='en'):
        return getattr(self, 'question_' + lang, None) or self.question_en or ''
    def options_for(self, lang='en'):
        return getattr(self, 'options_' + lang, None) or self.options_en or {}
    def explanation_for(self, lang='en'):
        return getattr(self, 'explanation_' + lang, None) or self.explanation_en or ''

class QuizSession(db.Model):
    __tablename__ = 'quiz_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    mode = db.Column(db.String(50))  # random, pmbok7_exam, pmbok8_exam, wrong_answers, category
    filter_type = db.Column(db.String(50))  # min류기준
    filter_value = db.Column(db.String(200))  # Select한 카테고리
    total_questions = db.Column(db.Integer, default=0)
    correct_count = db.Column(db.Integer, default=0)
    accuracy = db.Column(db.Float, default=0.0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    is_completed = db.Column(db.Boolean, default=False)

    answers = db.relationship('QuizAnswer', backref='session', lazy='dynamic',
                             cascade='all, delete-orphan')

class QuizAnswer(db.Model):
    __tablename__ = 'quiz_answers'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('quiz_sessions.id'), nullable=False, index=True)
    question_no = db.Column(db.Integer, db.ForeignKey('questions.no'), nullable=False)
    user_answer = db.Column(db.String(20))  # e.g., "A", "A, B"
    correct_answer = db.Column(db.String(20))
    is_correct = db.Column(db.Boolean, default=False)
    answered_at = db.Column(db.DateTime, default=datetime.utcnow)

class WrongAnswer(db.Model):
    __tablename__ = 'wrong_answers'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_no = db.Column(db.Integer, db.ForeignKey('questions.no'), nullable=False)
    wrong_count = db.Column(db.Integer, default=1)
    last_wrong_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'question_no', name='uix_user_question_wrong'),
    )

class UserAnswerStat(db.Model):
    """유저별 Accuracy 통계"""
    __tablename__ = 'user_answer_stats'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_no = db.Column(db.Integer, db.ForeignKey('questions.no'), nullable=False)
    total_attempts = db.Column(db.Integer, default=0)
    correct_attempts = db.Column(db.Integer, default=0)
    last_attempted = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'question_no', name='uix_user_question_stat'),
    )

class QuestionGlobalStat(db.Model):
    """Question별 All Accuracy (Admin용)"""
    __tablename__ = 'question_global_stats'
    id = db.Column(db.Integer, primary_key=True)
    question_no = db.Column(db.Integer, db.ForeignKey('questions.no'), unique=True, nullable=False)
    total_attempts = db.Column(db.Integer, default=0)
    correct_attempts = db.Column(db.Integer, default=0)
    accuracy = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class Bookmark(db.Model):
    """유저별 Bookmarks Question"""
    __tablename__ = 'bookmarks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_no = db.Column(db.Integer, db.ForeignKey('questions.no'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    question = db.relationship('Question', backref='bookmarks')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'question_no', name='uix_user_question_bookmark'),
    )

class QuestionReport(db.Model):
    """Report a question issue"""
    __tablename__ = 'question_reports'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_no = db.Column(db.Integer, db.ForeignKey('questions.no'), nullable=False)
    reason = db.Column(db.String(50), nullable=False)   # typo / wrong_answer / translation / other
    detail = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending / resolved / dismissed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='reports')
    question = db.relationship('Question', backref='reports')
