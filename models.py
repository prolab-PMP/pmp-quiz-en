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

    # Refer-a-friend program. referrer_email = email of the user who referred
    # this account at signup. referrer_bonus_applied = True once the +1mo
    # bonus has been granted to both parties (1-time only, on first paid order).
    referrer_email = db.Column(db.String(255), nullable=True, index=True)
    referrer_bonus_applied = db.Column(db.Boolean, default=False)

    # Free 150-question English pack — issue / download tracking (2026-07)
    free_pdf_sent_at = db.Column(db.DateTime, nullable=True)
    free_pdf_downloaded_at = db.Column(db.DateTime, nullable=True)

    # Admin-only private memo per user (why premium was granted, promo code notes, VIP flag, etc.).
    # Never shown to end user. Only visible in /admin panel.
    admin_note = db.Column(db.Text, nullable=True, default='')

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
        """Extend current validity by N months. If expired, start from today."""
        base = self.validity_end if self.validity_end and self.validity_end > datetime.utcnow() else datetime.utcnow()
        if not self.validity_start:
            self.validity_start = datetime.utcnow()
        self.validity_end = base + timedelta(days=months * 30)

    def set_trial(self, days=7):
        """Grant N-day free Premium trial right after signup."""
        self.is_premium = True
        self.validity_start = datetime.utcnow()
        self.validity_end = datetime.utcnow() + timedelta(days=days)

    def is_trial(self):
        """True if user is on the post-signup free trial (validity duration <= 8 days)."""
        if not self.is_premium or not self.validity_end or not self.validity_start:
            return False
        if not self.is_valid():
            return False
        # set_trial(7) -> exactly 7 days. Allow up to 8 to absorb clock skew.
        duration = self.validity_end - self.validity_start
        return duration.days <= 8

    def is_paid_premium(self):
        """True only for paid (or admin). Trial/free/expired -> False.
        Single source of truth for who sees real /status analytics and
        who hides the Upgrade nav link."""
        if self.is_admin:
            return True
        if not self.is_valid():
            return False
        return not self.is_trial()

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
    answer = db.Column(db.Text, nullable=False)  # MCQ letters or D&D JSON
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

    # ── Drag & Drop item support (added 2026-07) ──────────────────
    # question_type: 'mcq' (default) | 'dnd_match' | 'dnd_order'
    #   dnd_match:   dnd_items ↔ dnd_targets pairing.
    #                answer JSON: {"1":"A","2":"B",...}
    #   dnd_order:   dnd_items into the correct sequence.
    #                answer JSON: ["C","A","D","B"]
    question_type = db.Column(db.String(20), default='mcq')
    dnd_items = db.Column(db.Text)       # JSON array
    dnd_targets = db.Column(db.Text)     # JSON array
    dnd_items_kr = db.Column(db.Text)    # JSON array (Korean labels)
    dnd_targets_kr = db.Column(db.Text)  # JSON array (Korean labels)

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

    def is_dnd(self):
        return self.question_type in ('dnd_match', 'dnd_order')

    def check_dnd_answer(self, user_answer_raw):
        """Compare a JSON-encoded user answer with self.answer (also JSON)."""
        import json
        try:
            u = json.loads(user_answer_raw) if user_answer_raw else None
            c = json.loads(self.answer)
        except Exception:
            return False
        if self.question_type == 'dnd_match':
            if not isinstance(u, dict) or not isinstance(c, dict):
                return False
            return {str(k): str(v) for k, v in u.items()} == {str(k): str(v) for k, v in c.items()}
        elif self.question_type == 'dnd_order':
            if not isinstance(u, list) or not isinstance(c, list):
                return False
            return [str(x) for x in u] == [str(x) for x in c]
        return False

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

    # Multilingual helpers — English is the canonical column (`question`/`opt_a`/`explanation`).
    # Other langs use `<field>_<code>` (e.g. `question_kr`, `opt_a_zh`, `explanation_ja`).
    # 'ko' is treated as alias for 'kr' since DB columns use the legacy `_kr` suffix.
    @staticmethod
    def _lang_suffix(lang):
        return 'kr' if lang == 'ko' else lang

    def text_for(self, lang='en'):
        if lang == 'en':
            return self.question or ''
        return getattr(self, 'question_' + self._lang_suffix(lang), None) or self.question or ''

    def opt_for(self, letter, lang='en'):
        """letter: 'a'|'b'|'c'|'d'|'e' — returns option in the given language."""
        base = 'opt_' + letter
        if lang == 'en':
            return getattr(self, base, None) or ''
        return getattr(self, base + '_' + self._lang_suffix(lang), None) or getattr(self, base, None) or ''

    def options_for(self, lang='en'):
        return {l.upper(): self.opt_for(l, lang) for l in ('a', 'b', 'c', 'd', 'e')}

    def explanation_for(self, lang='en'):
        if lang == 'en':
            return self.explanation or ''
        return getattr(self, 'explanation_' + self._lang_suffix(lang), None) or self.explanation or ''

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
    user_answer = db.Column(db.Text)     # MCQ letters or D&D JSON
    correct_answer = db.Column(db.Text)  # MCQ letters or D&D JSON
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


class QuestionComment(db.Model):
    """Per-question discussion comment.
    - Visible only after grading (prevents answer spoilers)
    - Premium-only write
    - upvote / report / 1-level reply (parent_id)
    """
    __tablename__ = 'question_comments'
    id = db.Column(db.Integer, primary_key=True)
    question_no = db.Column(db.Integer, db.ForeignKey('questions.no'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('question_comments.id'), nullable=True, index=True)
    body = db.Column(db.Text, nullable=False)  # max 1500 chars
    upvotes = db.Column(db.Integer, default=0)
    report_count = db.Column(db.Integer, default=0)
    is_hidden = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='question_comments')
    question = db.relationship('Question', backref='question_comments')


class QuestionCommentVote(db.Model):
    """1 upvote per user per comment"""
    __tablename__ = 'question_comment_votes'
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('question_comments.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('comment_id', 'user_id', name='uix_comment_user_vote'),
    )


class QuestionCommentReport(db.Model):
    """Comment report (spam/offensive) — moderation queue"""
    __tablename__ = 'question_comment_reports'
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('question_comments.id'), nullable=False, index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.String(50), nullable=False)  # spam / offensive / spoiler / other
    detail = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending / actioned / dismissed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('comment_id', 'reporter_id', name='uix_comment_reporter'),
    )
