"""PMP Quiz Web Application"""
import os
import re
import json
import hmac
import random
import bcrypt
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from markupsafe import Markup, escape
from sqlalchemy import func, desc, and_, text

from config import Config
from models import (db, User, Question, QuizSession, QuizAnswer, WrongAnswer,
                    UserAnswerStat, QuestionGlobalStat, Bookmark, QuestionReport,
                    QuestionComment, QuestionCommentVote, QuestionCommentReport,
                    BlogPost)
from migrate import auto_migrate  # DB schema auto-sync (additive)

app = Flask(__name__)
app.config.from_object(Config)

# ══════════════════════════════════════════════════════
# 커스텀 도메인 redirect: *.up.railway.app → PRIMARY_HOST (301)
# ──────────────────────────────────────────────────────
# PRIMARY_HOST 환경변수가 비어있거나 미설정이면 redirect 자체를 끔.
# (여러 커스텀 도메인이 동시에 같은 서비스에 attach 되어 있고,
#  각 도메인을 그대로 노출하고 싶을 때 — 예: AdSense 승인용 도메인 등)
# ══════════════════════════════════════════════════════
PRIMARY_HOST = (os.environ.get('PRIMARY_HOST') or 'wayexam.com').strip().lower()
PUBLIC_HOSTS = {
    h.strip().lower()
    for h in (os.environ.get('PUBLIC_HOSTS') or 'wayexam.com,www.wayexam.com,pmp.wayexam.com').split(',')
    if h.strip()
}
if PRIMARY_HOST:
    PUBLIC_HOSTS.add(PRIMARY_HOST)


@app.before_request
def _redirect_to_primary_host():
    # PRIMARY_HOST 미설정 시 redirect 안 함 (모든 도메인 그대로 서빙)
    if not PRIMARY_HOST:
        return None
    # Skip Railway healthcheck — it hits us on the internal hostname and
    # expects a 200, not a 301.
    if request.path == '/healthz':
        return None
    host = (request.host or '').lower()
    if (
        host
        and host not in PUBLIC_HOSTS
        and not host.startswith('localhost')
        and not host.startswith('127.')
        and not host.endswith('.railway.internal')   # internal Railway routing
    ):
        target = 'https://' + PRIMARY_HOST + request.full_path.rstrip('?')
        return redirect(target, code=301)

# ══════════════════════════════════════════════════════
# Jinja filter: render markdown tables in question/explanation text
# Used by table-style questions (Q90001~90015) where the body
# contains a Markdown-style "| col | col |" table.
# Non-table text is HTML-escaped and \n is converted to <br>.
# ══════════════════════════════════════════════════════
_MD_TABLE_BLOCK = re.compile(
    r'(^[ \t]*\|[^\n]+\|[ \t]*\n'                   # header row
    r'[ \t]*\|[ \t\-:|]+\|[ \t]*\n'                  # separator row
    r'(?:[ \t]*\|[^\n]+\|[ \t]*(?:\n|$))+)',         # one or more body rows
    re.MULTILINE
)


def _md_table_to_html(block: str) -> str:
    lines = [ln.strip() for ln in block.strip().split('\n') if ln.strip()]
    if len(lines) < 2:
        return escape(block)

    def split_row(row: str):
        return [c.strip() for c in row.strip().strip('|').split('|')]

    header_cells = split_row(lines[0])
    body_rows = [split_row(r) for r in lines[2:]]

    out = ['<div class="table-wrapper" style="margin:10px 0;"><table class="md-table">']
    out.append('<thead><tr>')
    out.extend(f'<th>{escape(c)}</th>' for c in header_cells)
    out.append('</tr></thead><tbody>')
    for row in body_rows:
        out.append('<tr>')
        out.extend(f'<td>{escape(c)}</td>' for c in row)
        out.append('</tr>')
    out.append('</tbody></table></div>')
    return ''.join(out)


@app.template_filter('render_md_tables')
def render_md_tables(text_input):
    """Convert markdown tables in text to HTML; preserve newlines elsewhere."""
    if not text_input:
        return ''
    s = str(text_input)
    parts = []
    last = 0
    for m in _MD_TABLE_BLOCK.finditer(s):
        before = s[last:m.start()]
        if before:
            parts.append(str(escape(before)).replace('\n', '<br>'))
        parts.append(_md_table_to_html(m.group(1)))
        last = m.end()
    tail = s[last:]
    if tail:
        parts.append(str(escape(tail)).replace('\n', '<br>'))
    return Markup(''.join(parts))


db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated

# ══════════════════════════════════════════════════════
# Slicer / Filter Maps (NameError fix)
# ══════════════════════════════════════════════════════
HIERARCHY_PAIRS = [
    ('eco2021_domain', 'eco2021_task'),
    ('eco2026_domain', 'eco2026_task'),
    ('methodology',    'methodology_detail'),
]

FILTER_MAP = {
    'eco2021_domain':    Question.eco2021_domain,
    'eco2021_task':      Question.eco2021_task,
    'pmbok7_domain':     Question.pmbok7_domain,
    'pmbok7_principle':  Question.pmbok7_principle,
    'eco2026_domain':    Question.eco2026_domain,
    'eco2026_task':      Question.eco2026_task,
    'pmbok8_domain':     Question.pmbok8_domain,
    'pmbok8_principle':  Question.pmbok8_principle,
    'pmbok8_focus_area': Question.pmbok8_focus_area,
    'pmbok8_process':    Question.pmbok8_process,
    'pmbok8_new_topics': Question.pmbok8_new_topics,
    'methodology':       Question.methodology,
    'methodology_detail': Question.methodology_detail,
}


# ══════════════════════════════════════════════════════
# Lazy DB initialization
# ──────────────────────────────────────────────────────
# Heavy DB work (create_all, auto_migrate, admin seed, table-question seed,
# auto-load) is deferred to the first incoming request so that the gunicorn
# worker can bind to $PORT immediately. This prevents Railway's healthcheck
# from timing out (502) on cold start when DATABASE_URL points to a slow
# proxy connection.
# ══════════════════════════════════════════════════════
_DB_INITIALIZED = False


def _initialize_db_once():
    """Run startup DB tasks exactly once. Safe to call from request context."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    try:
        db.create_all()
        auto_migrate(db)  # ALTER TABLE for columns added to models since last deploy
        # Create or promote admin users (idempotent)
        for email in Config.ADMIN_EMAILS:
            existing = User.query.filter_by(email=email).first()
            if not existing:
                admin = User(email=email, is_admin=True, is_premium=True)
                admin.set_validity(months=120)
                db.session.add(admin)
                print(f'[INIT] admin created: {email}')
            elif not existing.is_admin:
                existing.is_admin = True
                existing.is_premium = True
                if not existing.validity_end or existing.validity_end < datetime.utcnow():
                    existing.set_validity(months=120)
                print(f'[INIT] admin auto-promoted: {email}')
        db.session.commit()

        # Table Question 15 items seed (idempotent)
        try:
            from seed_table_questions import seed_table_questions
            seed_table_questions(db, Question)
        except Exception as _e:
            print(f'[INIT] Table Question seed failed: {_e}')

        # Drag & Drop (match + order) 10 items seed (idempotent)
        try:
            from seed_dnd_questions import seed_dnd_questions
            seed_dnd_questions(db, Question)
        except Exception as _e:
            print(f'[INIT] D&D question seed failed: {_e}')

        # Auto-load questions if DB is empty
        if Question.query.count() == 0:
            filepath = 'data/PMP_Raw.xlsx'
            if os.path.exists(filepath):
                from load_data import load_questions
                count = load_questions(filepath)
                print(f"[STARTUP] Auto-loaded {count} questions from {filepath}")
            else:
                print(f"[STARTUP] No data file found at {filepath}")
        _DB_INITIALIZED = True
        print('[INIT] DB initialization complete.')
    except Exception as e:
        # Don't latch the flag on failure so a future request can retry.
        print(f'[INIT] DB initialization FAILED: {e}')
        raise


@app.before_request
def _ensure_db_initialized():
    """Lazy hook: initialize DB on first real request (not /healthz)."""
    if _DB_INITIALIZED:
        return
    # Skip init for the healthcheck endpoint so Railway can probe instantly.
    if request.path == '/healthz':
        return
    _initialize_db_once()


@app.route('/healthz')
def healthz():
    """Railway healthcheck — must respond instantly without touching DB."""
    return 'OK', 200

# ══════════════════════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════════════════════

@app.route('/')
def index():
    """Home: top banner + cover visual + practice hub (50%) + status preview + blog."""
    _blog_refresh_if_stale()
    total_questions = Question.query.count()
    total_sessions, avg_accuracy, wrong_count, bookmark_count = 0, 0, 0, 0
    if current_user.is_authenticated:
        total_sessions = QuizSession.query.filter_by(user_id=current_user.id, is_completed=True).count()
        avg_accuracy = db.session.query(func.avg(QuizSession.accuracy))\
            .filter_by(user_id=current_user.id, is_completed=True).scalar() or 0
        wrong_count = WrongAnswer.query.filter_by(user_id=current_user.id).count()
        bookmark_count = Bookmark.query.filter_by(user_id=current_user.id).count()

    # 2026 ECO domains for one-click domain practice
    eco_domains = [
        {'name': r[0], 'count': int(r[1])}
        for r in db.session.query(Question.eco2026_domain, func.count(Question.id))
            .filter(Question.eco2026_domain.isnot(None))
            .group_by(Question.eco2026_domain).order_by(func.count(Question.id).desc()).all()
    ]

    methodologies = [
        {'name': r[0], 'count': int(r[1])}
        for r in db.session.query(Question.methodology, func.count(Question.id))
            .filter(Question.methodology.isnot(None))
            .group_by(Question.methodology).order_by(func.count(Question.id).desc()).all()
    ]

    # Status preview: real data for premium/admin users who have practised,
    # otherwise the same sample data /status shows to free users.
    status = None
    if current_user.is_authenticated:
        is_free_preview = (not current_user.is_admin) and (not current_user.is_premium or not current_user.is_valid())
        if not is_free_preview:
            uid = current_user.id
            attempted = db.session.query(func.sum(UserAnswerStat.total_attempts)).filter_by(user_id=uid).scalar() or 0
            if attempted:
                correct = db.session.query(func.sum(UserAnswerStat.correct_attempts)).filter_by(user_id=uid).scalar() or 0
                daily = db.session.query(
                    func.date(QuizSession.completed_at).label('date'),
                    func.avg(QuizSession.accuracy).label('acc'),
                ).filter_by(user_id=uid, is_completed=True)\
                 .group_by(func.date(QuizSession.completed_at))\
                 .order_by(func.date(QuizSession.completed_at)).all()
                status = {
                    'sample': False,
                    'overall_accuracy': round(correct / attempted * 100, 1),
                    'total_attempted': int(attempted),
                    'wrong_count': wrong_count,
                    'streak_days': _calc_streak(uid),
                    'daily': [round(float(d.acc or 0), 1) for d in daily][-14:],
                    'domains': _cat_stats(Question.eco2026_domain, uid, 'eco2026_domain'),
                }
    if status is None:
        sm = _sample_my_status_data()
        status = {
            'sample': True,
            'overall_accuracy': sm['overall_accuracy'],
            'total_attempted': sm['total_attempted'],
            'wrong_count': sm['wrong_count'],
            'streak_days': sm['streak_days'],
            'daily': [d['avg_accuracy'] for d in sm['daily_stats']],
            'domains': sm['cat_stats']['pmbok8']['eco2026_domain'],
        }
    # Sparkline points (viewBox 0 0 300 70, accuracy 40..100 %)
    vals = status['daily'] or [0]
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = 0 if n == 1 else round(i * 300 / (n - 1), 1)
        y = round(70 - (max(40, min(100, v)) - 40) / 60 * 64 - 3, 1)
        pts.append(f"{x},{y}")
    status['spark'] = ' '.join(pts)

    return render_template('home.html',
                           total_questions=total_questions,
                           total_sessions=total_sessions,
                           avg_accuracy=avg_accuracy,
                           wrong_count=wrong_count,
                           bookmark_count=bookmark_count,
                           eco_domains=eco_domains,
                           methodologies=methodologies,
                           status=status,
                           recent_posts=_BLOG_INDEX_CACHE[:3])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not email or '@' not in email:
            flash('Please enter a valid email address.', 'error')
            return render_template('login.html')
        if len(password) < 4:
            flash('Please enter your password (4+ chars).', 'error')
            return render_template('login.html', email=email)

        user = User.query.filter_by(email=email).first()
        if not user:
            flash('No account found for that email address. Please sign up first.', 'error')
            return redirect(url_for('signup', email=email))

        # Admin Email은 ADMIN_PASSWORD 로도 Log in 가능 (레거시 호환)
        is_admin_email = email in Config.ADMIN_EMAILS
        password_ok = False
        if user.password_hash:
            try:
                password_ok = bcrypt.checkpw(password.encode(), user.password_hash.encode())
            except Exception:
                password_ok = False
        if not password_ok and is_admin_email and password == Config.ADMIN_PASSWORD:
            # 첫 Admin Log in 시 Password 해시 Save
            user.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            db.session.commit()
            password_ok = True
        if not password_ok:
            flash('Email or password is incorrect.', 'error')
            return render_template('login.html', email=email)

        user.last_login = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=True)
        return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        abuse_reason = _signup_abuse_reason()
        if abuse_reason:
            # One line per rejection so the block rate is measurable in the
            # Railway logs the same way WAYEXAM_STATS is.
            print('[signup][blocked] reason={} ip={} ua={}'.format(
                abuse_reason,
                request.headers.get('X-Forwarded-For') or request.remote_addr,
                (request.headers.get('User-Agent') or '')[:80]), flush=True)
            flash('We could not verify that submission. Please try again.', 'error')
            return render_template('signup.html',
                                   email=request.form.get('email', '').strip(),
                                   signup_form_token=_signup_form_token())
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        referrer_email_raw = request.form.get('referrer_email', '').strip().lower()
        if not email or '@' not in email:
            flash('Please enter a valid email address.', 'error')
            return render_template('signup.html', email=email,
                                   signup_form_token=_signup_form_token())
        if len(password) < 4:
            flash('Password must be at least 4 characters long.', 'error')
            return render_template('signup.html', email=email,
                                   signup_form_token=_signup_form_token())
        if password != password2:
            flash('Passwords do not match. Please try again.', 'error')
            return render_template('signup.html', email=email,
                                   signup_form_token=_signup_form_token())
        existing = User.query.filter_by(email=email).first()
        if existing and existing.password_hash:
            flash('That email address is already registered. Please log in.', 'error')
            return redirect(url_for('login', email=email))

        # Validate referrer (optional). Silently ignore if missing/invalid/self.
        valid_referrer_email = None
        if referrer_email_raw and '@' in referrer_email_raw and referrer_email_raw != email:
            ref = User.query.filter(func.lower(User.email) == referrer_email_raw).first()
            if ref:
                valid_referrer_email = ref.email

        if existing and not existing.password_hash:
            # #10 fix: webhook-created premium-pending account. Let the buyer
            # claim it by setting their password. Preserve premium / validity.
            user = existing
            user.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            print(f'[signup] claimed premium-pending account for {email}')
        else:
            user = User(email=email)
            user.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            # The signup CTA promises a "7-day Premium trial" and dashboard.html
            # has a Trial branch that says "auto-granted on signup" — but nothing
            # ever called set_trial(), so every new account landed on Free and the
            # advertised trial silently did not exist. Grant it here.
            user.set_trial(days=7)
        if valid_referrer_email and not user.referrer_email:
            user.referrer_email = valid_referrer_email
        is_admin_email = email in Config.ADMIN_EMAILS
        if is_admin_email:
            user.is_admin = True
            user.is_premium = True
            user.set_validity(months=120)
        user.last_login = datetime.utcnow()
        user.free_pdf_sent_at = datetime.utcnow()
        if user not in db.session:
            db.session.add(user)
        db.session.commit()
        # Signup notification — background thread (SMTP delay must not block redirect)
        _async_mail(_notify_signup, email)
        login_user(user, remember=True)
        flash('Welcome! Your free 150-question PDF is ready to download on the dashboard.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('signup.html',
                           email=request.args.get('email', ''),
                           signup_form_token=_signup_form_token())

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

def _async_mail(fn, *args):
    """Run a mail-sending function in a background thread so SMTP latency
    never blocks the HTTP response."""
    import threading
    def _runner():
        try:
            fn(*args)
        except Exception as e:
            try:
                app.logger.warning(f'[MAIL][async] {fn.__name__} failed: {e}')
            except Exception:
                print(f'[MAIL][async] {fn.__name__} failed: {e}')
    threading.Thread(target=_runner, daemon=True).start()


# ══════════════════════════════════════════════════════
# SIGNUP ABUSE GUARD (2026-09-26)
# ──────────────────────────────────────────────────────
# Measured, not guessed. 10 of the 16 accounts on this site were created by a
# script. Its signature, straight from the Railway HTTP logs:
#   * GET /signup -> POST /signup in 0.49-0.96 s (six samples). Nobody types an
#     address, a password and a confirmation that fast.
#   * Source addresses rotate inside 212.30.36.0/24 (7 hits) and
#     31.171.130.0/24 (2), with a different forged User-Agent each run.
#   * Not one question answered afterwards: quiz_sessions_total sat at 23
#     through every single one of them.
#
# The cost is not only a dirty user count. Each fake signup burns a 7-day
# trial and sets free_pdf_sent_at, so switching SMTP on would start mailing
# the lead magnet to these addresses.
#
# Two stateless checks. No new dependency, no new DB column, no new table:
#   1. Minimum fill time. The GET embeds an HMAC-signed issue timestamp. The
#      POST is refused if the form returned faster than a person could fill it.
#      Signing it matters: an unsigned timestamp could simply be back-dated,
#      and a bare nonce would need server-side storage that two gunicorn
#      workers do not share. SECRET_KEY is a required env var in production,
#      so either worker can verify a token the other one issued.
#   2. Honeypot. A field people never see and never fill. Anything that fills
#      every input in the form announces itself.
#
# Neither is a wall. A patient scraper can sleep three seconds and skip the
# decoy field. Both are free, and they stop the script that is running today.
# If it adapts, the next step is per-/24 rate limiting, which does need state.
SIGNUP_MIN_FILL_SECONDS = 2.0
SIGNUP_FORM_MAX_AGE_SECONDS = 6 * 3600
SIGNUP_HONEYPOT_FIELD = 'website'


def _signup_form_token(issued_at=None):
    """'<issued_at>.<hmac>' — an issue time the client cannot rewrite."""
    import hashlib as _hashlib
    ts = '%.3f' % (issued_at if issued_at is not None
                   else datetime.utcnow().timestamp())
    sig = hmac.new(app.config['SECRET_KEY'].encode('utf-8'),
                   ts.encode('ascii'), _hashlib.sha256).hexdigest()[:32]
    return ts + '.' + sig


def _signup_form_age(token):
    """Seconds since we served the form, or None if the token is not ours."""
    import hashlib as _hashlib
    # rpartition, not partition: the timestamp is formatted '%.3f' and so
    # contains a dot of its own. Splitting at the FIRST dot would hand back
    # ts_part='1790406118' and sig='454.<hmac>', and the recomputed signature
    # over the truncated timestamp would never match the real one — every
    # token this app issued would be rejected, blocking real signups, not
    # just scripts. The signature boundary is the LAST dot.
    ts_part, _, sig = (token or '').rpartition('.')
    if not ts_part or not sig:
        return None
    expected = hmac.new(app.config['SECRET_KEY'].encode('utf-8'),
                        ts_part.encode('ascii'),
                        _hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        issued = float(ts_part)
    except ValueError:
        return None
    return datetime.utcnow().timestamp() - issued


def _signup_abuse_reason():
    """Why this POST looks automated, or None if it looks like a person."""
    if (request.form.get(SIGNUP_HONEYPOT_FIELD) or '').strip():
        return 'honeypot'
    age = _signup_form_age(request.form.get('form_token'))
    if age is None:
        return 'token_missing_or_invalid'
    if age < SIGNUP_MIN_FILL_SECONDS:
        return 'too_fast_%.2fs' % age
    if age > SIGNUP_FORM_MAX_AGE_SECONDS:
        return 'token_expired'
    return None



# ── Free 150-question English pack (lead magnet, 2026-07) ─────────────
FREE_PDF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'private_assets', 'pmp_free_150_en.pdf')
FREE_PDF_FILENAME = 'PMP_Free_Practice_Pack_150_EN.pdf'


@app.route('/download/free-150')
@login_required
def download_free_pdf():
    """Free 150-question English pack. Members only; logs first download."""
    from flask import send_file
    if not os.path.isfile(FREE_PDF_PATH):
        app.logger.error(f'[FREE-PDF] file missing: {FREE_PDF_PATH}')
        abort(404)
    try:
        if not current_user.free_pdf_downloaded_at:
            current_user.free_pdf_downloaded_at = datetime.utcnow()
            db.session.commit()
    except Exception as _e:
        app.logger.warning(f'[FREE-PDF] download log failed: {_e}')
    return send_file(FREE_PDF_PATH, as_attachment=True,
                     download_name=FREE_PDF_FILENAME,
                     mimetype='application/pdf')


def _notify_signup(email):
    """Signup notification email (SMTP_* env vars required)."""
    import os, smtplib
    from email.mime.text import MIMEText
    host = os.getenv('SMTP_HOST')
    user = os.getenv('SMTP_USER')
    pw = os.getenv('SMTP_PASS')
    if not (host and user and pw):
        now = datetime.utcnow()
        print(f'[MAIL][stub] PMP Quiz signup {email} {now.month}/{now.day}')
        return
    port = int(os.getenv('SMTP_PORT', '587'))
    to_addr = os.getenv('NOTIFY_EMAIL', 'songodinfo1@gmail.com')
    now = datetime.utcnow()
    body = f'PMP Quiz site signup {email} on {now.month}/{now.day}'
    msg = MIMEText(body)
    msg['Subject'] = f'[PMP Quiz] New signup: {email}'
    msg['From'] = os.getenv('SMTP_FROM', user)
    msg['To'] = to_addr
    # timeout=10s prevents unbounded blocking when SMTP is slow/refused
    with smtplib.SMTP(host, port, timeout=10) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    print(f'[MAIL] signup notify sent to {to_addr} for {email}')

# ══════════════════════════════════════════════════════
# FREE VERSION (no login required)
# ══════════════════════════════════════════════════════

@app.route('/free')
def free_mode():
    already_used = session.get('free_used', False)
    return render_template('free_mode.html', already_used=already_used)

@app.route('/free/upgrade')
def free_upgrade():
    return render_template('free_upgrade.html')


# ══════════════════════════════════════════════════════
# PAYPAL PAYMENT INTEGRATION
# ──────────────────────────────────────────────────────
# Flow:
#   1. User clicks "Buy Premium" -> /upgrade page (renders pricing).
#   2. PayPal JS SDK renders checkout buttons for each plan.
#   3. Browser calls /api/paypal/create-order to create an order server-side.
#   4. Buyer approves payment in PayPal.
#   5. Browser calls /api/paypal/capture-order/<order_id>.
#   6. Server verifies captured amount/plan and extends Premium validity.
#
# Required env vars (set in Railway Variables when ready):
#   - PAYPAL_CLIENT_ID
#   - PAYPAL_CLIENT_SECRET
#   - PAYPAL_MODE                   ('sandbox' default, 'live' for production)
#
# Until env vars are set, /upgrade renders a "checkout coming soon" notice.
# ══════════════════════════════════════════════════════
import hmac
import hashlib
import base64
import urllib.request
import urllib.error

PAYPAL_PLANS = [
    # (plan key, label, price USD, months of validity)
    ('3mo',  '3 Months Premium',  '19.00', 3),
    ('6mo',  '6 Months Premium',  '29.00', 6),
    ('12mo', '12 Months Premium', '49.00', 12),
]

LEMONSQUEEZY_PLANS = [
    # Legacy webhook compatibility only. New checkout uses PayPal.
    ('LEMONSQUEEZY_VARIANT_3MO',  '3 Months Premium',  19, 3),
    ('LEMONSQUEEZY_VARIANT_6MO',  '6 Months Premium',  29, 6),
    ('LEMONSQUEEZY_VARIANT_12MO', '12 Months Premium', 49, 12),
]


def _paypal_mode():
    return os.environ.get('PAYPAL_MODE', 'sandbox').strip().lower()


def _paypal_api_base():
    return 'https://api-m.paypal.com' if _paypal_mode() == 'live' else 'https://api-m.sandbox.paypal.com'


def _paypal_configured():
    return bool(os.environ.get('PAYPAL_CLIENT_ID') and os.environ.get('PAYPAL_CLIENT_SECRET'))


def _paypal_access_token():
    client_id = os.environ.get('PAYPAL_CLIENT_ID', '')
    client_secret = os.environ.get('PAYPAL_CLIENT_SECRET', '')
    auth = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8')).decode('ascii')
    req = urllib.request.Request(
        f'{_paypal_api_base()}/v1/oauth2/token',
        data=b'grant_type=client_credentials',
        method='POST',
        headers={
            'Authorization': f'Basic {auth}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    return payload['access_token']


def _paypal_request(method, path, payload=None):
    token = _paypal_access_token()
    body = json.dumps(payload or {}).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(
        f'{_paypal_api_base()}{path}',
        data=body,
        method=method,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            text = resp.read().decode('utf-8')
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        print(f'[paypal] HTTP {e.code}: {detail[:500]}')
        raise


def _paypal_plan(plan_key):
    for key, label, price, months in PAYPAL_PLANS:
        if key == plan_key:
            return {'key': key, 'label': label, 'price': price, 'months': months}
    return None


def _lemonsqueezy_configured():
    """True only if minimum env vars are set."""
    return bool(
        os.environ.get('LEMONSQUEEZY_STORE_SLUG')
        and os.environ.get('LEMONSQUEEZY_WEBHOOK_SECRET')
        and os.environ.get('LEMONSQUEEZY_VARIANT_3MO')
    )


def _build_checkout_url(variant_id, email):
    """Build a Lemon Squeezy hosted checkout URL with prefilled email.
    Pattern: https://{store_slug}.lemonsqueezy.com/buy/{variant_uuid}?checkout[email]=...
    """
    store_slug = os.environ.get('LEMONSQUEEZY_STORE_SLUG', '')
    base = f'https://{store_slug}.lemonsqueezy.com/buy/{variant_id}'
    # Tag the email so we can match the user on webhook
    from urllib.parse import quote
    return f'{base}?checkout[email]={quote(email)}'


# ══════════════════════════════════════════════════════
# Payment self-check (admin only)
#
# Why this exists: PayPal fails silently. The JS SDK loads from the same host
# for sandbox and live -- the environment is decided by PAYPAL_CLIENT_ID -- while
# the server creates orders against whichever base PAYPAL_MODE selects. If those
# two disagree, the OAuth token call fails, /api/paypal/create-order returns 500,
# and the buyer just sees a button that does not work. Nothing in the logs says
# "wrong environment".
#
# This route settles it without guessing: it asks BOTH PayPal hosts to
# authenticate the configured credentials. Exactly one will succeed, and that
# tells us which environment the credentials actually belong to. Comparing that
# against PAYPAL_MODE gives a definite verdict.
#
# Visit /admin/payment-check while logged in as an admin.
# ══════════════════════════════════════════════════════

def _paypal_probe(api_base):
    """Try a client_credentials grant against one PayPal host.

    Returns (ok, detail). Never raises -- this is a diagnostic.
    """
    client_id = os.environ.get('PAYPAL_CLIENT_ID', '')
    client_secret = os.environ.get('PAYPAL_CLIENT_SECRET', '')
    if not (client_id and client_secret):
        return False, 'PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET not set'
    auth = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8')).decode('ascii')
    req = urllib.request.Request(
        f'{api_base}/v1/oauth2/token',
        data=b'grant_type=client_credentials',
        method='POST',
        headers={
            'Authorization': f'Basic {auth}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        if payload.get('access_token'):
            return True, 'authenticated'
        return False, 'no access_token in response'
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def _lemonsqueezy_variants_present():
    """Which plan keys currently have a Lemon Squeezy variant id configured."""
    present = []
    for key, _label, _price, _months in PAYPAL_PLANS:
        if os.environ.get('LEMONSQUEEZY_VARIANT_' + key.upper(), '').strip():
            present.append(key)
    return present


def _payment_diagnosis():
    """Build a plain-language verdict about whether checkout can actually work."""
    mode = _paypal_mode()
    configured = _paypal_configured()

    sandbox_ok, sandbox_detail = (False, 'skipped')
    live_ok, live_detail = (False, 'skipped')
    if configured:
        sandbox_ok, sandbox_detail = _paypal_probe('https://api-m.sandbox.paypal.com')
        live_ok, live_detail = _paypal_probe('https://api-m.paypal.com')

    if live_ok and not sandbox_ok:
        credential_env = 'live'
    elif sandbox_ok and not live_ok:
        credential_env = 'sandbox'
    elif live_ok and sandbox_ok:
        credential_env = 'ambiguous'
    else:
        credential_env = 'unknown'

    server_env = 'live' if mode == 'live' else 'sandbox'

    if not configured:
        paypal_verdict = 'BROKEN'
        explanation = (
            'PayPal credentials are not set, so no PayPal button is rendered.'
        )
    elif credential_env == 'unknown':
        paypal_verdict = 'BROKEN'
        explanation = (
            'Neither PayPal host accepted these credentials. The client ID or '
            'secret is wrong, or the PayPal app was deleted or disabled. '
            f'Sandbox said: {sandbox_detail}. Live said: {live_detail}.'
        )
    elif credential_env != server_env:
        paypal_verdict = 'BROKEN'
        explanation = (
            f'Environment mismatch. The credentials belong to the {credential_env} '
            f'environment, but PAYPAL_MODE selects the {server_env} API. Order '
            'creation will fail and the PayPal button will not complete. '
            f'Fix: set PAYPAL_MODE to "{credential_env}" -- or, if you meant to '
            f'take real money, replace the credentials with {server_env} ones.'
        )
    elif credential_env == 'sandbox':
        paypal_verdict = 'TEST ONLY'
        explanation = (
            'Client and server agree, but both are on sandbox. PayPal checkout '
            'works only for PayPal sandbox test accounts -- a real customer '
            'cannot pay through it. Switch PAYPAL_CLIENT_ID / '
            'PAYPAL_CLIENT_SECRET to the live app credentials and set '
            'PAYPAL_MODE=live.'
        )
    else:
        paypal_verdict = 'OK'
        explanation = (
            'Live credentials authenticate against the live API and PAYPAL_MODE '
            'agrees. PayPal checkout should work. If a buyer still reports a '
            'failure, check the deploy log for "[paypal] HTTP" lines.'
        )

    # Lemon Squeezy: hosted checkout, no sandbox/live split on our side. The
    # /upgrade page renders a "Pay by Card" link for every plan that has a
    # variant id, so a configured store is a working payment route on its own.
    ls_configured = _lemonsqueezy_configured()
    ls_variants = _lemonsqueezy_variants_present()
    ls_live = bool(ls_configured and ls_variants)
    if ls_live:
        card_verdict = 'OK'
        card_note = (
            'Card checkout is wired for plan(s): ' + ', '.join(ls_variants) + '. '
            'This path does not depend on PAYPAL_MODE. Open /upgrade and click '
            '"Pay by Card" once: a Lemon Squeezy checkout page with the email '
            'prefilled means it works; a 404 means the store or the product is '
            'not published yet, or a variant id is wrong.'
        )
    elif ls_configured:
        card_verdict = 'BROKEN'
        card_note = (
            'Lemon Squeezy is configured but no LEMONSQUEEZY_VARIANT_<PLAN> is '
            'set, so no card button can be rendered.'
        )
    else:
        card_verdict = 'NOT CONFIGURED'
        card_note = (
            'Lemon Squeezy is not configured. Set LEMONSQUEEZY_STORE_SLUG, '
            'LEMONSQUEEZY_WEBHOOK_SECRET and LEMONSQUEEZY_VARIANT_3MO at minimum.'
        )

    # The only question that matters: can a real customer pay right now?
    if paypal_verdict == 'OK' or card_verdict == 'OK':
        verdict = 'OK'
    elif paypal_verdict == 'TEST ONLY':
        verdict = 'TEST ONLY'
    else:
        verdict = 'BROKEN'

    return {
        'verdict': verdict,
        'paypal_verdict': paypal_verdict,
        'card_verdict': card_verdict,
        'explanation': explanation,
        'card_note': card_note,
        'paypal_mode': mode,
        'paypal_configured': configured,
        'credential_environment': credential_env,
        'server_environment': server_env,
        'sandbox_probe': sandbox_detail,
        'live_probe': live_detail,
        'client_id_tail': (os.environ.get('PAYPAL_CLIENT_ID', '') or '')[-6:],
        'lemonsqueezy_configured': ls_configured,
        'lemonsqueezy_store': os.environ.get('LEMONSQUEEZY_STORE_SLUG', ''),
        'lemonsqueezy_variants_set': len(ls_variants),
        'lemonsqueezy_reachable_from_upgrade_page': ls_live,
    }


@app.route('/admin/payment-check')
@admin_required
def admin_payment_check():
    """One page that answers: can a real customer actually pay right now?"""
    return jsonify(_payment_diagnosis())


@app.route('/upgrade')
@login_required
def upgrade():
    """Render premium plans + checkout buttons."""
    paypal_ready = _paypal_configured()
    lemon_ready = _lemonsqueezy_configured()
    plans = []
    for key, label, price, months in PAYPAL_PLANS:
        checkout_url = ''
        if lemon_ready:
            variant_id = os.environ.get('LEMONSQUEEZY_VARIANT_' + key.upper(), '').strip()
            if variant_id:
                checkout_url = _build_checkout_url(variant_id, current_user.email)
        plans.append({
            'key': key,
            'label': label,
            'price': price,
            'months': months,
            'checkout_url': checkout_url,
        })
    card_ready = lemon_ready and any(p['checkout_url'] for p in plans)
    return render_template(
        'upgrade.html',
        plans=plans,
        configured=paypal_ready or card_ready,
        paypal_configured=paypal_ready,
        card_configured=card_ready,
        paypal_client_id=os.environ.get('PAYPAL_CLIENT_ID', ''),
        paypal_mode=_paypal_mode(),
    )


@app.route('/api/paypal/create-order', methods=['POST'])
@login_required
def paypal_create_order():
    if not _paypal_configured():
        return jsonify({'error': 'paypal not configured'}), 503

    data = request.get_json(silent=True) or {}
    plan = _paypal_plan(data.get('plan'))
    if not plan:
        return jsonify({'error': 'invalid plan'}), 400

    try:
        order = _paypal_request('POST', '/v2/checkout/orders', {
            'intent': 'CAPTURE',
            'purchase_units': [{
                'reference_id': plan['key'],
                'description': f"PMP Quiz {plan['label']} for {current_user.email}",
                'custom_id': f"{current_user.id}:{plan['key']}",
                'amount': {
                    'currency_code': 'USD',
                    'value': plan['price'],
                },
            }],
            'application_context': {
                'brand_name': 'PMP Quiz',
                'shipping_preference': 'NO_SHIPPING',
                'user_action': 'PAY_NOW',
                'return_url': url_for('payment_success', _external=True),
                'cancel_url': url_for('payment_cancel', _external=True),
            },
        })
    except Exception as exc:
        print(f'[paypal] create-order failed: {exc}')
        return jsonify({'error': 'could not create paypal order'}), 502

    if not order.get('id'):
        print(f'[paypal] create-order response missing id: {order}')
        return jsonify({'error': 'paypal order id missing'}), 502
    return jsonify({'id': order['id']})


@app.route('/api/paypal/capture-order/<order_id>', methods=['POST'])
@login_required
def paypal_capture_order(order_id):
    if not _paypal_configured():
        return jsonify({'error': 'paypal not configured'}), 503

    data = request.get_json(silent=True) or {}
    plan = _paypal_plan(data.get('plan'))
    if not plan:
        return jsonify({'error': 'invalid plan'}), 400

    try:
        capture = _paypal_request('POST', f'/v2/checkout/orders/{order_id}/capture', {})
    except Exception as exc:
        print(f'[paypal] capture failed order={order_id}: {exc}')
        return jsonify({'error': 'could not capture paypal payment'}), 502
    if capture.get('status') != 'COMPLETED':
        return jsonify({'error': 'payment not completed', 'status': capture.get('status')}), 400

    units = capture.get('purchase_units') or []
    first_unit = units[0] if units else {}
    payments = (first_unit.get('payments') or {}).get('captures') or []
    first_capture = payments[0] if payments else {}
    amount = first_capture.get('amount') or {}
    captured_value = amount.get('value')
    captured_currency = amount.get('currency_code')
    reference_id = first_unit.get('reference_id')

    if reference_id != plan['key'] or captured_currency != 'USD' or captured_value != plan['price']:
        print(f"[paypal] capture mismatch order={order_id} ref={reference_id} "
              f"amount={captured_value} {captured_currency} expected={plan}")
        return jsonify({'error': 'payment verification failed'}), 400

    current_user.is_premium = True
    current_user.extend_validity(months=plan['months'])
    db.session.commit()
    print(f'[paypal] extended {current_user.email} by {plan["months"]} months '
          f'(new end: {current_user.validity_end})')

    if current_user.referrer_email and not current_user.referrer_bonus_applied:
        ref = User.query.filter(func.lower(User.email) == current_user.referrer_email.lower()).first()
        if ref and ref.is_paid_premium():
            current_user.extend_validity(months=1)
            ref.extend_validity(months=1)
            current_user.referrer_bonus_applied = True
            db.session.commit()
            print(f'[referral] +1mo bonus granted to {current_user.email} and referrer {ref.email}')

    return jsonify({
        'status': 'COMPLETED',
        'redirect': url_for('payment_success'),
    })


@app.route('/webhook/lemonsqueezy', methods=['POST'])
def webhook_lemonsqueezy():
    """Receive order_created event from Lemon Squeezy and grant premium.

    Lemon Squeezy webhook docs: signature is HMAC-SHA256 of raw body using
    the webhook secret, sent in X-Signature header (hex).
    """
    secret = os.environ.get('LEMONSQUEEZY_WEBHOOK_SECRET')
    if not secret:
        return 'webhook not configured', 503

    raw_body = request.get_data()
    received_sig = request.headers.get('X-Signature', '')
    expected_sig = hmac.new(
        secret.encode('utf-8'), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_sig, received_sig):
        print(f'[lemonsqueezy] BAD signature. expected={expected_sig[:12]}... got={received_sig[:12]}...')
        return 'bad signature', 401

    try:
        payload = json.loads(raw_body)
    except Exception as e:
        return f'bad json: {e}', 400

    event_name = payload.get('meta', {}).get('event_name', '')
    print(f'[lemonsqueezy] event={event_name}')

    GRANT_EVENTS = ('order_created', 'subscription_created', 'subscription_payment_success')
    REVOKE_EVENTS = ('order_refunded', 'subscription_cancelled', 'subscription_expired')

    if event_name not in GRANT_EVENTS + REVOKE_EVENTS:
        return 'event ignored', 200

    data = payload.get('data', {}).get('attributes', {})
    customer_email = (data.get('user_email') or data.get('customer_email') or '').strip().lower()
    if not customer_email:
        print('[lemonsqueezy] no customer email in payload')
        return 'no email', 400

    # ── Revoke flow (#9): refund / cancel / expire ──
    if event_name in REVOKE_EVENTS:
        user = User.query.filter(func.lower(User.email) == customer_email).first()
        if not user:
            print(f'[lemonsqueezy] revoke event for unknown user {customer_email}; ignored')
            return 'ok', 200
        if user.is_admin:
            # Never revoke admin accounts.
            print(f'[lemonsqueezy] revoke event ignored for admin {customer_email}')
            return 'ok', 200
        if event_name == 'order_refunded' or event_name == 'subscription_expired':
            # Hard revoke: immediately end premium access.
            user.is_premium = False
            user.validity_end = datetime.utcnow()
            db.session.commit()
            print(f'[lemonsqueezy] {event_name}: revoked premium for {customer_email}')
        elif event_name == 'subscription_cancelled':
            # Soft cancel: LemonSqueezy still grants access until period end.
            # We only log; subscription_expired will eventually revoke.
            print(f'[lemonsqueezy] subscription_cancelled noted for {customer_email}; '
                  f'access remains until {user.validity_end}')
        return 'ok', 200

    # ── Grant flow: order_created / subscription_created / subscription_payment_success ──
    # Find which variant was purchased to determine months of validity
    variant_id = None
    if event_name == 'order_created':
        first_order_item = (data.get('first_order_item') or {})
        variant_id = str(first_order_item.get('variant_id') or '')
    if not variant_id:
        # subscription events
        variant_id = str(data.get('variant_id') or '')

    months = 3  # default
    for env_var, _label, _price, plan_months in LEMONSQUEEZY_PLANS:
        if str(os.environ.get(env_var, '')) == variant_id:
            months = plan_months
            break

    # Match user account (case-insensitive email)
    user = User.query.filter(func.lower(User.email) == customer_email).first()
    if not user:
        # #10 fix: Do NOT auto-create with NULL password_hash. Anyone who knew
        # the email could try to log in or signup races could attach to it.
        # Instead, create a placeholder "premium pending" record that becomes
        # active only when the buyer signs up (signup route detects NULL hash
        # and lets them set a password to take ownership).
        user = User(email=customer_email, is_premium=True, password_hash=None)
        user.set_validity(months=months)
        db.session.add(user)
        db.session.commit()
        print(f'[lemonsqueezy] queued premium grant for {customer_email} (+{months}mo). '
              f'User must signup to claim access (password_hash is NULL).')
    else:
        user.is_premium = True
        user.extend_validity(months=months)
        db.session.commit()
        print(f'[lemonsqueezy] extended {customer_email} by {months} months '
              f'(new end: {user.validity_end})')

    # Refer-a-friend bonus: only on the user's FIRST paid order, only if their
    # referrer is currently paid Premium. Both get +1mo, then flag is set.
    if user and user.referrer_email and not user.referrer_bonus_applied:
        ref = User.query.filter(func.lower(User.email) == user.referrer_email.lower()).first()
        if ref and ref.is_paid_premium():
            user.extend_validity(months=1)
            ref.extend_validity(months=1)
            user.referrer_bonus_applied = True
            db.session.commit()
            print(f'[referral] +1mo bonus granted to {user.email} and referrer {ref.email}')
        else:
            print(f'[referral] skipped: referrer {user.referrer_email} not paid premium')

    return 'ok', 200


@app.route('/payment/success')
def payment_success():
    """User-facing redirect after successful checkout."""
    return render_template('payment_success.html')


@app.route('/payment/cancel')
def payment_cancel():
    flash('Payment was canceled. You can try again anytime.', 'info')
    return redirect(url_for('upgrade') if _paypal_configured() else url_for('dashboard'))

@app.route('/free/start', methods=['POST'])
def free_start():
    # already Free trial을 Completed한 경우 Upgrade 페이지로 이동
    if session.get('free_used', False):
        return redirect(url_for('free_upgrade'))

    count = int(request.form.get('count', 10))
    count = min(count, Config.FREE_QUESTION_LIMIT)

    # 처음 N items 고정 Question (Random 아님, Question번호 순서대로)
    free_pool = Question.query.order_by(Question.no).limit(Config.FREE_QUESTION_LIMIT).all()
    selected = free_pool[:count]
    q_nos = [q.no for q in selected]

    session['free_questions'] = q_nos
    session['free_answers'] = {}
    session['free_current'] = 0
    return redirect(url_for('free_quiz'))

@app.route('/free/quiz')
def free_quiz():
    q_nos = session.get('free_questions', [])
    if not q_nos:
        return redirect(url_for('free_mode'))
    current = session.get('free_current', 0)
    if current >= len(q_nos):
        return redirect(url_for('free_result'))

    question = Question.query.filter_by(no=q_nos[current]).first()
    return render_template('free_quiz.html',
                         question=question,
                         current=current + 1,
                         total=len(q_nos),
                         answers=session.get('free_answers', {}))

@app.route('/free/answer', methods=['POST'])
def free_answer():
    q_no = request.form.get('question_no')
    selected = request.form.getlist('selected')
    answers = session.get('free_answers', {})
    if q_no:
        answers[str(q_no)] = ','.join(selected)
        session['free_answers'] = answers

    action = request.form.get('action', 'next')
    if action == 'prev':
        session['free_current'] = max(0, session.get('free_current', 0) - 1)
    elif action == 'next':
        session['free_current'] = session.get('free_current', 0) + 1
    elif action == 'goto':
        goto = int(request.form.get('goto_num', 0)) - 1
        session['free_current'] = max(0, min(goto, len(session.get('free_questions', [])) - 1))

    return redirect(url_for('free_quiz'))

@app.route('/free/grade', methods=['POST'])
def free_grade():
    q_nos = session.get('free_questions', [])
    answers = session.get('free_answers', {})

    # Save any last-minute answer
    q_no = request.form.get('question_no')
    selected = request.form.getlist('selected')
    if q_no and selected:
        answers[q_no] = ','.join(selected)
        session['free_answers'] = answers

    return redirect(url_for('free_result'))

@app.route('/free/result')
def free_result():
    q_nos = session.get('free_questions', [])
    user_answers = session.get('free_answers', {})
    if not q_nos:
        return redirect(url_for('free_mode'))

    questions = Question.query.filter(Question.no.in_(q_nos)).all()
    q_map = {q.no: q for q in questions}

    results = []
    correct_count = 0
    for no in q_nos:
        q = q_map.get(no)
        if not q:
            continue
        user_ans_raw = user_answers.get(str(no), '')
        user_ans = sorted([a.strip() for a in user_ans_raw.split(',') if a.strip()])
        correct_ans = sorted(q.get_answer_list())
        is_correct = user_ans == correct_ans
        if is_correct:
            correct_count += 1

        results.append({
            'question': q,
            'user_answer': user_ans,
            'correct_answer': correct_ans,
            'is_correct': is_correct,
            'answered': bool(user_ans_raw),
        })

    total = len(results)
    accuracy = (correct_count / total * 100) if total > 0 else 0

    # Free trial Completed 표시 (다시 Start 시 Upgrade 유도)
    session['free_used'] = True

    # Generate mock wrong-answer list and accuracy for free version
    return render_template('free_result.html',
                         results=results,
                         correct_count=correct_count,
                         total=total,
                         accuracy=accuracy)

# ══════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════

@app.route('/dashboard')
def dashboard():
    if not current_user.is_authenticated:
        total_questions = Question.query.count()
        categories = get_category_options()
        return render_template('dashboard.html',
                             recent=[],
                             total_sessions=0,
                             avg_accuracy=0,
                             wrong_count=0,
                             bookmark_count=0,
                             total_questions=total_questions,
                             categories=categories)

    # Recent sessions
    recent = QuizSession.query.filter_by(user_id=current_user.id, is_completed=True)\
        .order_by(desc(QuizSession.completed_at)).limit(5).all()

    # Overall stats
    total_sessions = QuizSession.query.filter_by(user_id=current_user.id, is_completed=True).count()
    avg_accuracy = db.session.query(func.avg(QuizSession.accuracy))\
        .filter_by(user_id=current_user.id, is_completed=True).scalar() or 0

    wrong_count = WrongAnswer.query.filter_by(user_id=current_user.id).count()
    bookmark_count = Bookmark.query.filter_by(user_id=current_user.id).count()
    total_questions = Question.query.count()

    # By category Select 섹션을 위한 categories context
    categories = get_category_options()

    return render_template('dashboard.html',
                         recent=recent,
                         total_sessions=total_sessions,
                         avg_accuracy=avg_accuracy,
                         wrong_count=wrong_count,
                         bookmark_count=bookmark_count,
                         total_questions=total_questions,
                         categories=categories)

# ══════════════════════════════════════════════════════
# QUIZ ROUTES
# ══════════════════════════════════════════════════════

def _build_tree(parent_col, child_col):
    """Build {parent: [children]} dict, sorted."""
    rows = db.session.query(parent_col, child_col).filter(
        parent_col.isnot(None)
    ).distinct().order_by(parent_col, child_col).all()
    tree = {}
    for parent, child in rows:
        tree.setdefault(parent, [])
        if child and child not in tree[parent]:
            tree[parent].append(child)
    return tree

def get_category_options():
    """Get all available category options and hierarchical trees for filters"""
    return {
        'pmbok7': {
            'domain': sorted(set(q[0] for q in db.session.query(Question.pmbok7_domain).filter(Question.pmbok7_domain.isnot(None)).distinct().all())),
            'principle': sorted(set(q[0] for q in db.session.query(Question.pmbok7_principle).filter(Question.pmbok7_principle.isnot(None)).distinct().all())),
            'eco_domain': sorted(set(q[0] for q in db.session.query(Question.eco2021_domain).filter(Question.eco2021_domain.isnot(None)).distinct().all())),
            'eco_task': sorted(set(q[0] for q in db.session.query(Question.eco2021_task).filter(Question.eco2021_task.isnot(None)).distinct().all())),
        },
        'pmbok8': {
            'domain': sorted(set(q[0] for q in db.session.query(Question.pmbok8_domain).filter(Question.pmbok8_domain.isnot(None)).distinct().all())),
            'principle': sorted(set(q[0] for q in db.session.query(Question.pmbok8_principle).filter(Question.pmbok8_principle.isnot(None)).distinct().all())),
            'process': sorted(set(q[0] for q in db.session.query(Question.pmbok8_process).filter(Question.pmbok8_process.isnot(None)).distinct().all())),
            'focus_area': sorted(set(q[0] for q in db.session.query(Question.pmbok8_focus_area).filter(Question.pmbok8_focus_area.isnot(None)).distinct().all())),
            'new_topics': sorted(set(q[0] for q in db.session.query(Question.pmbok8_new_topics).filter(Question.pmbok8_new_topics.isnot(None)).distinct().all())),
            'eco_domain': sorted(set(q[0] for q in db.session.query(Question.eco2026_domain).filter(Question.eco2026_domain.isnot(None)).distinct().all())),
            'eco_task': sorted(set(q[0] for q in db.session.query(Question.eco2026_task).filter(Question.eco2026_task.isnot(None)).distinct().all())),
        },
        'methodology': sorted(set(q[0] for q in db.session.query(Question.methodology).filter(Question.methodology.isnot(None)).distinct().all())),
        # Hierarchical trees for cascading slicer UI
        'trees': {
            'eco2021': _build_tree(Question.eco2021_domain, Question.eco2021_task),
            'eco2026': _build_tree(Question.eco2026_domain, Question.eco2026_task),
            'methodology': _build_tree(Question.methodology, Question.methodology_detail),
        },
    }

@app.route('/quiz/start')
@login_required
def quiz_start():
    # Question풀이 탭은 dashboard로 통합됨
    return redirect(url_for('dashboard') + '#detail-select')


@app.route('/quiz/begin', methods=['POST'])
@login_required
def quiz_begin():
    mode = request.form.get('mode', 'random')
    filter_type = request.form.get('filter_type', '')
    filter_value = request.form.get('filter_value', '')
    count_raw = request.form.get('count', '10')
    count = int(count_raw) if count_raw.isdigit() else 10


    # Premium gate: free/trial users may only use random + domain-category + exam modes
    if not current_user.is_admin and not current_user.is_paid_premium():
        if mode == 'slicer':
            flash('Detailed slicer practice is a Premium-only feature. Free/Trial members can use Domain selection + Random pickup.', 'warning')
            return redirect(url_for('dashboard'))
        if mode == 'keyword':
            flash('Keyword search practice is a Premium-only feature.', 'warning')
            return redirect(url_for('dashboard'))
        if mode == 'category' and 'principle' in (filter_type or '').lower():
            flash('Principle-based practice is a Premium-only feature. Free/Trial members can use Domain selection + Random pickup.', 'warning')
            return redirect(url_for('dashboard'))
    query = Question.query

    if mode == 'wrong_answers':
        wrong_nos = [w.question_no for w in WrongAnswer.query.filter_by(user_id=current_user.id).all()]
        if not wrong_nos:
            flash('Your incorrect-answer list is empty.', 'info')
            return redirect(url_for('quiz_start'))
        query = query.filter(Question.no.in_(wrong_nos))

    elif mode == 'bookmark':
        bookmark_nos = [b.question_no for b in Bookmark.query.filter_by(user_id=current_user.id).all()]
        if not bookmark_nos:
            flash('No bookmarked questions yet.', 'info')
            return redirect(url_for('quiz_start'))
        query = query.filter(Question.no.in_(bookmark_nos))

    elif mode == 'pmbok7_exam':
        count = 180
        query = query.filter(Question.pmbok7_domain.isnot(None))

    elif mode == 'pmbok8_exam':
        count = 185
        query = query.filter(Question.pmbok8_domain.isnot(None))

    elif mode == 'slicer':
        # 슬라이서 복수 Filter (계층 쌍은 OR, 나머지는 AND)
        filter_json_str = request.form.get('filter_json', '{}')
        try:
            filters = json.loads(filter_json_str)
        except Exception:
            filters = {}
        filter_type = 'slicer'
        filter_value = filter_json_str  # 세션 기록용

        from sqlalchemy import or_
        handled = set()
        for parent_key, child_key in HIERARCHY_PAIRS:
            parent_vals = filters.get(parent_key, [])
            child_vals  = filters.get(child_key, [])
            handled.update([parent_key, child_key])
            if parent_vals or child_vals:
                conds = []
                if parent_vals:
                    conds.append(FILTER_MAP[parent_key].in_(parent_vals))
                if child_vals:
                    conds.append(FILTER_MAP[child_key].in_(child_vals))
                query = query.filter(or_(*conds))

        for ft, values in filters.items():
            if ft in handled or not values:
                continue
            col = FILTER_MAP.get(ft)
            if col is not None:
                query = query.filter(col.in_(values))

    elif mode == 'category':
        if filter_type and filter_value:
            col = FILTER_MAP.get(filter_type)
            if col is not None:
                query = query.filter(col == filter_value)

    # Get questions
    all_questions = query.all()
    if not all_questions:
        flash('No questions match the filters you selected.', 'warning')
        return redirect(url_for('quiz_start'))

    random.shuffle(all_questions)
    selected = all_questions[:count]
    q_nos = [q.no for q in selected]

    # Create quiz session
    quiz_session = QuizSession(
        user_id=current_user.id,
        mode=mode,
        filter_type=filter_type,
        filter_value=filter_value,
        total_questions=len(q_nos),
    )
    db.session.add(quiz_session)
    db.session.commit()

    session['quiz_session_id'] = quiz_session.id
    session['quiz_questions'] = q_nos
    session['quiz_answers'] = {}
    session['quiz_current'] = 0

    return redirect(url_for('quiz_question'))

@app.route('/quiz/question')
@login_required
def quiz_question():
    q_nos = session.get('quiz_questions', [])
    if not q_nos:
        return redirect(url_for('quiz_start'))

    current = session.get('quiz_current', 0)
    if current >= len(q_nos):
        current = len(q_nos) - 1
        session['quiz_current'] = current

    question = Question.query.filter_by(no=q_nos[current]).first()
    saved_answer = session.get('quiz_answers', {}).get(str(q_nos[current]), '')

    is_bookmarked = bool(Bookmark.query.filter_by(
        user_id=current_user.id, question_no=q_nos[current]).first())

    # Multi-select detection: N개 선택 필요한 문제
    expected_count = 1
    if question and question.answer:
        expected_count = len([a for a in question.answer.split(',') if a.strip()])

    return render_template('quiz_question.html',
                         question=question,
                         current=current + 1,
                         total=len(q_nos),
                         expected_count=expected_count,
                         saved_answer=saved_answer.split(',') if saved_answer else [],
                         saved_answer_raw=saved_answer,  # D&D: JSON string
                         all_answers=session.get('quiz_answers', {}),
                         q_nos=q_nos,
                         is_bookmarked=is_bookmarked)

@app.route('/quiz/save_answer', methods=['POST'])
@login_required
def quiz_save_answer():
    q_no = request.form.get('question_no')
    # D&D answers arrive as a JSON string via hidden input name="dnd_answer"
    dnd_ans = request.form.get('dnd_answer')
    selected = request.form.getlist('selected')
    answers = session.get('quiz_answers', {})
    if dnd_ans:
        answers[q_no] = dnd_ans
    elif selected:
        answers[q_no] = ','.join(selected)
    session['quiz_answers'] = answers

    action = request.form.get('action', 'next')
    q_nos = session.get('quiz_questions', [])

    if action == 'prev':
        session['quiz_current'] = max(0, session.get('quiz_current', 0) - 1)
    elif action == 'next':
        session['quiz_current'] = min(len(q_nos) - 1, session.get('quiz_current', 0) + 1)
    elif action == 'goto':
        goto = int(request.form.get('goto_num', 1)) - 1
        session['quiz_current'] = max(0, min(goto, len(q_nos) - 1))
    elif action == 'grade':
        return redirect(url_for('quiz_grade'))

    return redirect(url_for('quiz_question'))

@app.route('/quiz/grade')
@login_required
def quiz_grade():
    quiz_session_id = session.get('quiz_session_id')
    q_nos = session.get('quiz_questions', [])
    user_answers = session.get('quiz_answers', {})

    if not quiz_session_id or not q_nos:
        return redirect(url_for('quiz_start'))

    quiz_sess = db.session.get(QuizSession, quiz_session_id)
    if not quiz_sess:
        return redirect(url_for('quiz_start'))

    questions = Question.query.filter(Question.no.in_(q_nos)).all()
    q_map = {q.no: q for q in questions}

    results = []
    correct_count = 0

    for no in q_nos:
        q = q_map.get(no)
        if not q:
            continue

        user_ans_raw = user_answers.get(str(no), '')

        # D&D branch: user_ans_raw is a JSON string; MCQ branch remains original.
        if q.is_dnd():
            is_correct = q.check_dnd_answer(user_ans_raw)
            user_ans_display = user_ans_raw
            correct_display = q.answer
            user_ans = []
            correct_ans = []
        else:
            user_ans = sorted([a.strip() for a in user_ans_raw.split(',') if a.strip()])
            correct_ans = sorted(q.get_answer_list())
            is_correct = user_ans == correct_ans
            user_ans_display = ','.join(user_ans) if user_ans else ''
            correct_display = q.answer

        if is_correct:
            correct_count += 1

        # Save quiz answer
        qa = QuizAnswer(
            session_id=quiz_session_id,
            question_no=no,
            user_answer=user_ans_display,
            correct_answer=correct_display,
            is_correct=is_correct,
        )
        db.session.add(qa)

        # Update wrong answers
        if is_correct:
            # Remove from wrong answers if exists
            WrongAnswer.query.filter_by(user_id=current_user.id, question_no=no).delete()
        else:
            wrong = WrongAnswer.query.filter_by(user_id=current_user.id, question_no=no).first()
            if wrong:
                wrong.wrong_count += 1
                wrong.last_wrong_at = datetime.utcnow()
            else:
                wrong = WrongAnswer(user_id=current_user.id, question_no=no)
                db.session.add(wrong)

        # Update user answer stats
        stat = UserAnswerStat.query.filter_by(user_id=current_user.id, question_no=no).first()
        if stat:
            stat.total_attempts += 1
            if is_correct:
                stat.correct_attempts += 1
            stat.last_attempted = datetime.utcnow()
        else:
            stat = UserAnswerStat(
                user_id=current_user.id,
                question_no=no,
                total_attempts=1,
                correct_attempts=1 if is_correct else 0,
            )
            db.session.add(stat)

        # Update global stats
        gstat = QuestionGlobalStat.query.filter_by(question_no=no).first()
        if gstat:
            gstat.total_attempts += 1
            if is_correct:
                gstat.correct_attempts += 1
            gstat.accuracy = (gstat.correct_attempts / gstat.total_attempts * 100) if gstat.total_attempts > 0 else 0
            gstat.last_updated = datetime.utcnow()
        else:
            gstat = QuestionGlobalStat(
                question_no=no,
                total_attempts=1,
                correct_attempts=1 if is_correct else 0,
                accuracy=100.0 if is_correct else 0.0,
            )
            db.session.add(gstat)

        results.append({
            'question': q,
            'user_answer': user_ans,
            'correct_answer': correct_ans,
            'user_answer_display': user_ans_display,
            'correct_answer_display': correct_display,
            'is_dnd': q.is_dnd(),
            'is_correct': is_correct,
            'answered': bool(user_ans_raw),
        })

    # Update quiz session
    total = len(results)
    accuracy = (correct_count / total * 100) if total > 0 else 0
    quiz_sess.correct_count = correct_count
    quiz_sess.accuracy = accuracy
    quiz_sess.completed_at = datetime.utcnow()
    quiz_sess.is_completed = True
    db.session.commit()

    # Clear session quiz data
    for key in ['quiz_questions', 'quiz_answers', 'quiz_current', 'quiz_session_id']:
        session.pop(key, None)

    return render_template('quiz_result.html',
                         results=results,
                         correct_count=correct_count,
                         total=total,
                         accuracy=accuracy,
                         quiz_session=quiz_sess)

# ══════════════════════════════════════════════════════
# MY STATUS
# ══════════════════════════════════════════════════════

def _calc_streak(uid):
    """최근 풀이 day자 기반 Streakday 계산 (오늘  or  어제부터)"""
    from datetime import date, timedelta
    rows = db.session.query(func.distinct(func.date(QuizSession.completed_at)))\
        .filter_by(user_id=uid, is_completed=True).all()
    days = sorted({r[0] for r in rows if r[0]}, reverse=True)
    if not days:
        return 0
    today = date.today()
    cursor = today if days[0] == today else (today - timedelta(days=1))
    if days[0] != cursor:
        return 0
    streak = 0
    for d in days:
        if d == cursor:
            streak += 1
            cursor = cursor - timedelta(days=1)
        else:
            break
    return streak


def _calc_weak_domains(cat_stats, top_n=3):
    """전 카테고리에서 Accuracy 낮은 약점 Domain N items (시도 5회 이상). filter_json도 동봉."""
    import json as _json
    all_rows = []
    for ed in cat_stats.values():
        for key, rows in ed.items():
            for r in rows:
                if r.get('total', 0) >= 5:
                    all_rows.append({
                        'name': r['name'],
                        'accuracy': r['accuracy'],
                        'category': key,
                        'filter_json': _json.dumps({key: [r['name']]}, ensure_ascii=False),
                    })
    all_rows.sort(key=lambda x: x['accuracy'])
    return all_rows[:top_n]


def _sample_my_status_data():
    """Free user 미리View용 샘플 데이터 (재현 가능)"""
    from datetime import date, timedelta
    import random
    random.seed(42)
    today = date.today()
    daily = [{'date': str(today - timedelta(days=13 - i)),
              'avg_accuracy': round(random.uniform(58, 94), 1)} for i in range(14)]

    def cat(items, fkey):
        import json as _json
        return [{'name': n, 'correct': c, 'total': t, 'accuracy': round(c / t * 100, 1),
                 'filter_json': _json.dumps({fkey: [n]}, ensure_ascii=False)}
                for n, c, t in items]

    cat_stats = {
        'pmbok7': {
            'eco2021_domain': cat([('People', 35, 42), ('Process', 28, 38), ('Business Environment', 17, 25)], 'eco2021_domain'),
            'eco2021_task': cat([('Manage conflict', 8, 10), ('Engage stakeholders', 12, 15), ('Build a team', 9, 12)], 'eco2021_task'),
            'pmbok7_domain': cat([('Stakeholders', 14, 18), ('Team', 19, 22), ('Planning', 22, 30), ('Delivery', 17, 25)], 'pmbok7_domain'),
            'pmbok7_principle': cat([('Stewardship', 6, 8), ('Leadership', 10, 12), ('Tailoring', 5, 9)], 'pmbok7_principle'),
            'methodology': cat([('Agile', 18, 22), ('Waterfall', 12, 18), ('Hybrid', 8, 11)], 'methodology'),
        },
        'pmbok8': {
            'eco2026_domain': cat([('People', 32, 40), ('Process', 25, 36), ('Business Environment', 14, 22)], 'eco2026_domain'),
            'eco2026_task': cat([('Lead a team', 11, 14), ('Manage conflict', 9, 12)], 'eco2026_task'),
            'pmbok8_domain': cat([('Stakeholders', 13, 17), ('Team', 18, 21), ('Planning', 20, 28), ('Delivery', 15, 22)], 'pmbok8_domain'),
            'pmbok8_focus_area': cat([('AI/Automation', 5, 8), ('Sustainability', 6, 9), ('Diversity & Inclusion', 7, 10)], 'pmbok8_focus_area'),
            'pmbok8_process': cat([('Initiating', 8, 11), ('Planning', 18, 25), ('Executing', 14, 20), ('Monitoring & Controlling', 12, 18), ('Closing', 5, 7)], 'pmbok8_process'),
            'pmbok8_principle': cat([('Stewardship', 7, 10), ('Tailoring', 6, 9)], 'pmbok8_principle'),
            'methodology': cat([('Agile', 18, 22), ('Waterfall', 12, 18)], 'methodology'),
        },
    }
    # Study grass sample — last 365 days, ~60% study days, 5~70 questions/day
    daily_activity = {}
    for i in range(365):
        d = today - timedelta(days=i)
        recent_factor = 0.85 if i < 30 else (0.7 if i < 90 else 0.45)
        if random.random() < recent_factor:
            base = 8 if i < 30 else (5 if i < 180 else 3)
            cnt = base + int(random.expovariate(1.0 / 12))
            daily_activity[str(d)] = min(cnt, 80)

    return {
        'daily_stats': daily,
        'cat_stats': cat_stats,
        'wrong_count': 12,
        'total_attempted': 124,
        'total_correct': 91,
        'overall_accuracy': 73.4,
        'sessions_count': 9,
        'streak_days': 5,
        'daily_activity': daily_activity,
        'weak_domains': [
            {'name': 'AI/Automation', 'accuracy': 62.5, 'category': 'pmbok8_focus_area', 'filter_json': '{"pmbok8_focus_area": ["AI/Automation"]}'},
            {'name': 'Business Environment', 'accuracy': 68.0, 'category': 'eco2021_domain', 'filter_json': '{"eco2021_domain": ["Business Environment"]}'},
            {'name': 'Sustainability', 'accuracy': 66.7, 'category': 'pmbok8_focus_area', 'filter_json': '{"pmbok8_focus_area": ["Sustainability"]}'},
        ],
    }


def _cat_stats(col, uid, filter_key=None):
    """Per-category accuracy helper. Includes filter_json for clickable practice links."""
    import json as _json
    rows = db.session.query(
        col,
        func.sum(UserAnswerStat.correct_attempts).label('correct'),
        func.sum(UserAnswerStat.total_attempts).label('total')
    ).join(UserAnswerStat, UserAnswerStat.question_no == Question.no)\
     .filter(UserAnswerStat.user_id == uid)\
     .filter(col.isnot(None))\
     .group_by(col)\
     .order_by(col).all()
    result = []
    for r in rows:
        total = int(r.total or 0)
        correct = int(r.correct or 0)
        name = r[0]
        result.append({
            'name': name,
            'total': total,
            'correct': correct,
            'accuracy': round(correct / total * 100, 1) if total > 0 else 0.0,
            'filter_json': _json.dumps({filter_key: [name]}, ensure_ascii=False) if filter_key else None,
        })
    return result

@app.route('/status')
@login_required
def my_status():
    uid = current_user.id

    validity_remaining = None
    if current_user.validity_end:
        # Same count the dashboard shows, from the same helper, so the two
        # pages cannot disagree by a day. None still means "no expiry set".
        validity_remaining = _days_remaining(current_user.validity_end)

    # Free user(미인증/Expired/Free등급) → 샘플 데이터로 미리View
    is_free_preview = (not current_user.is_admin) and (not current_user.is_premium or not current_user.is_valid())

    sessions = QuizSession.query.filter_by(user_id=uid, is_completed=True)\
        .order_by(desc(QuizSession.completed_at)).limit(50).all()

    # day별 추이
    daily_stats_raw = db.session.query(
        func.date(QuizSession.completed_at).label('date'),
        func.avg(QuizSession.accuracy).label('avg_accuracy'),
    ).filter_by(user_id=uid, is_completed=True)\
     .group_by(func.date(QuizSession.completed_at))\
     .order_by(func.date(QuizSession.completed_at)).all()
    daily_stats = [{'date': str(s.date), 'avg_accuracy': round(float(s.avg_accuracy), 1)} for s in daily_stats_raw]

    # ── Practice Heatmap (GitHub-style) ──
    # Length: paid premium uses validity span (3/6/12 mo plan); others use 90 days default.
    from datetime import timedelta as _td
    if current_user.is_paid_premium() and current_user.validity_start and current_user.validity_end:
        total_validity_days = (current_user.validity_end - current_user.validity_start).days
        grass_days = max(90, min(370, total_validity_days))
    else:
        grass_days = 90
    activity_rows = db.session.query(
        func.date(QuizSession.completed_at).label('date'),
        func.sum(QuizSession.total_questions).label('cnt'),
    ).filter_by(user_id=uid, is_completed=True)\
     .filter(QuizSession.completed_at >= datetime.utcnow() - _td(days=grass_days))\
     .group_by(func.date(QuizSession.completed_at)).all()
    daily_activity = {str(r.date): int(r.cnt or 0) for r in activity_rows}

    # All By category Accuracy
    cat_stats = {
        'pmbok7': {
            'eco2021_domain':   _cat_stats(Question.eco2021_domain,   uid, 'eco2021_domain'),
            'eco2021_task':     _cat_stats(Question.eco2021_task,     uid, 'eco2021_task'),
            'pmbok7_domain':    _cat_stats(Question.pmbok7_domain,    uid, 'pmbok7_domain'),
            'pmbok7_principle': _cat_stats(Question.pmbok7_principle, uid, 'pmbok7_principle'),
            'methodology':      _cat_stats(Question.methodology,      uid, 'methodology'),
        },
        'pmbok8': {
            'eco2026_domain':    _cat_stats(Question.eco2026_domain,    uid, 'eco2026_domain'),
            'eco2026_task':      _cat_stats(Question.eco2026_task,      uid, 'eco2026_task'),
            'pmbok8_domain':     _cat_stats(Question.pmbok8_domain,     uid, 'pmbok8_domain'),
            'pmbok8_focus_area': _cat_stats(Question.pmbok8_focus_area, uid, 'pmbok8_focus_area'),
            'pmbok8_process':    _cat_stats(Question.pmbok8_process,    uid, 'pmbok8_process'),
            'pmbok8_principle':  _cat_stats(Question.pmbok8_principle,  uid, 'pmbok8_principle'),
            'methodology':       _cat_stats(Question.methodology,       uid, 'methodology'),
        },
    }

    wrong_count = WrongAnswer.query.filter_by(user_id=uid).count()
    total_attempted = db.session.query(func.sum(UserAnswerStat.total_attempts))\
        .filter_by(user_id=uid).scalar() or 0
    total_correct = db.session.query(func.sum(UserAnswerStat.correct_attempts))\
        .filter_by(user_id=uid).scalar() or 0
    overall_accuracy = round(total_correct / total_attempted * 100, 1) if total_attempted > 0 else 0.0

    # streak / 약점 Domain
    streak_days = _calc_streak(uid)
    weak_domains = _calc_weak_domains(cat_stats, top_n=3)
    sessions_count = len(sessions)

    # Free user라면 샘플로 치환 (실 데이터가 빈약해도 와우 효과)
    # Trial users always see sample stats (PMP-KR parity: stats are paid-only).
    if is_free_preview:
        sample = _sample_my_status_data()
        daily_stats = sample['daily_stats']
        cat_stats = sample['cat_stats']
        wrong_count = sample['wrong_count']
        total_attempted = sample['total_attempted']
        total_correct = sample['total_correct']
        overall_accuracy = sample['overall_accuracy']
        sessions_count = sample['sessions_count']
        streak_days = sample['streak_days']
        weak_domains = sample['weak_domains']
        daily_activity = sample.get('daily_activity', {})
        grass_days = 90
        sample_mode = True
    else:
        sample_mode = False

    return render_template('my_status.html',
                           validity_remaining=validity_remaining,
                           sessions=sessions,
                           daily_activity=daily_activity,
                           grass_days=grass_days,
                           daily_stats=daily_stats,
                           cat_stats=cat_stats,
                           wrong_count=wrong_count,
                           total_attempted=total_attempted,
                           total_correct=total_correct,
                           overall_accuracy=overall_accuracy,
                           streak_days=streak_days,
                           weak_domains=weak_domains,
                           sessions_count=sessions_count,
                           sample_mode=sample_mode,
                           is_free_preview=is_free_preview)

# ══════════════════════════════════════════════════════
# API ENDPOINTS
# ══════════════════════════════════════════════════════

@app.route('/api/framework_stats')
@login_required
def api_framework_stats():
    """Return user accuracy + question counts per classification value, grouped by dimension.

    Used by the dashboard's framework grid to color-code each classification box
    by the user's strength in that area and display question availability.
    """
    uid = current_user.id

    def values_for(col):
        all_values = sorted(
            v[0] for v in db.session.query(col).filter(col.isnot(None)).distinct().all()
        )
        stats_rows = db.session.query(
            col,
            func.sum(UserAnswerStat.correct_attempts).label('correct'),
            func.sum(UserAnswerStat.total_attempts).label('total')
        ).join(UserAnswerStat, UserAnswerStat.question_no == Question.no)\
         .filter(UserAnswerStat.user_id == uid)\
         .filter(col.isnot(None))\
         .group_by(col).all()
        stats_map = {r[0]: (int(r.total or 0), int(r.correct or 0)) for r in stats_rows}
        cap_rows = db.session.query(col, func.count(Question.id))\
            .filter(col.isnot(None)).group_by(col).all()
        cap_map = {r[0]: int(r[1]) for r in cap_rows}
        out = []
        for v in all_values:
            total, correct = stats_map.get(v, (0, 0))
            out.append({
                'name': v,
                'total_attempts': total,
                'correct_attempts': correct,
                'accuracy': round(correct / total * 100, 1) if total > 0 else None,
                'question_count': cap_map.get(v, 0),
            })
        return out

    return jsonify({
        'pmbok7_domain': values_for(Question.pmbok7_domain),
        'pmbok7_principle': values_for(Question.pmbok7_principle),
        'pmbok8_domain': values_for(Question.pmbok8_domain),
        'pmbok8_principle': values_for(Question.pmbok8_principle),
        'pmbok8_focus_area': values_for(Question.pmbok8_focus_area),
        'pmbok8_process': values_for(Question.pmbok8_process),
        'eco2021_domain': values_for(Question.eco2021_domain),
        'eco2021_task': values_for(Question.eco2021_task),
        'eco2026_domain': values_for(Question.eco2026_domain),
        'eco2026_task': values_for(Question.eco2026_task),
        'methodology': values_for(Question.methodology),
    })


@app.route('/api/subcategories')
@login_required
def api_subcategories():
    """Get subcategories based on filter type"""
    filter_type = request.args.get('filter_type', '')
    filter_map = {
        'pmbok7_domain': Question.pmbok7_domain,
        'pmbok7_principle': Question.pmbok7_principle,
        'eco2021_domain': Question.eco2021_domain,
        'eco2021_task': Question.eco2021_task,
        'pmbok8_domain': Question.pmbok8_domain,
        'pmbok8_principle': Question.pmbok8_principle,
        'pmbok8_process': Question.pmbok8_process,
        'pmbok8_focus_area': Question.pmbok8_focus_area,
        'pmbok8_new_topics': Question.pmbok8_new_topics,
        'eco2026_domain': Question.eco2026_domain,
        'eco2026_task': Question.eco2026_task,
        'methodology': Question.methodology,
    }
    col = filter_map.get(filter_type)
    if col is None:
        return jsonify([])

    values = sorted(set(q[0] for q in db.session.query(col).filter(col.isnot(None)).distinct().all()))
    counts = {}
    for val in values:
        counts[val] = Question.query.filter(col == val).count()
    return jsonify([{'value': v, 'count': counts.get(v, 0)} for v in values])

@app.route('/api/filter_count', methods=['POST'])
@login_required
def api_filter_count():
    """슬라이서 복수 Filter → this question 수 반환 (계층 쌍은 OR)"""
    try:
        filters = request.get_json(force=True) or {}
    except Exception:
        return jsonify({'count': 0})
    from sqlalchemy import or_
    query = Question.query
    handled = set()
    for parent_key, child_key in HIERARCHY_PAIRS:
        parent_vals = filters.get(parent_key, [])
        child_vals  = filters.get(child_key, [])
        handled.update([parent_key, child_key])
        if parent_vals or child_vals:
            conds = []
            if parent_vals:
                conds.append(FILTER_MAP[parent_key].in_(parent_vals))
            if child_vals:
                conds.append(FILTER_MAP[child_key].in_(child_vals))
            query = query.filter(or_(*conds))
    for ft, values in filters.items():
        if ft in handled or not values:
            continue
        col = FILTER_MAP.get(ft)
        if col is not None:
            query = query.filter(col.in_(values))
    return jsonify({'count': query.count()})

@app.route('/api/daily_trend')
@login_required
def api_daily_trend():
    stats = db.session.query(
        func.date(QuizSession.completed_at).label('date'),
        func.avg(QuizSession.accuracy).label('avg_accuracy'),
    ).filter_by(user_id=current_user.id, is_completed=True)\
     .group_by(func.date(QuizSession.completed_at))\
     .order_by(func.date(QuizSession.completed_at)).all()

    return jsonify([{
        'date': str(s.date),
        'accuracy': round(s.avg_accuracy, 1),
    } for s in stats])

# ══════════════════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════════════════

@app.route('/admin')
@admin_required
def admin_panel():
    sort = request.args.get('sort', 'last_login')
    order = request.args.get('order', 'desc')
    filter_grade = request.args.get('grade', 'all')  # all / premium / free

    q = User.query
    if filter_grade == 'premium':
        q = q.filter_by(is_premium=True)
    elif filter_grade == 'free':
        q = q.filter_by(is_premium=False)

    sort_map = {
        'email':        (User.email,        'asc'),
        'grade':        (User.is_premium,   'desc'),
        'validity':     (User.validity_end, 'desc'),
        'last_login':   (User.last_login,   'desc'),
    }
    col, default_order = sort_map.get(sort, (User.last_login, 'desc'))
    actual_order = order if order in ('asc', 'desc') else default_order
    users = q.order_by(col.asc() if actual_order == 'asc' else col.desc()).all()

    total_questions = Question.query.count()
    pending_report_count = QuestionReport.query.filter_by(status='pending').count()
    return render_template('admin.html',
                           users=users,
                           total_questions=total_questions,
                           sort=sort, order=order, filter_grade=filter_grade,
                           pending_report_count=pending_report_count,
                           payment_enabled=app.config.get('PAYMENT_ENABLED', False))

@app.route('/admin/import_translations', methods=['GET', 'POST'])
@admin_required
def admin_import_translations():
    """Merge zh/es/ja translations from data/PMP_Raw_translated.xlsx
    (sheet 'PMP_Translated') into Question rows by `no`.
    Idempotent — running again just overwrites with the latest values.

    Returns plain-text response so any error shows the full traceback in the
    browser instead of a generic 500 page (and avoids any redirect/template
    surprises while debugging)."""
    import traceback
    filepath = 'data/PMP_Raw_translated.xlsx'
    abs_path = os.path.abspath(filepath)
    cwd = os.getcwd()
    try:
        if not os.path.exists(filepath):
            return (f"File not found.\ncwd={cwd}\nlooking for: {abs_path}\n"
                    f"data/ contents: {os.listdir('data') if os.path.isdir('data') else 'no data/ dir'}\n"), 200, {'Content-Type': 'text/plain; charset=utf-8'}

        from openpyxl import load_workbook
        wb = load_workbook(filepath, read_only=True)
        if 'PMP_Translated' not in wb.sheetnames:
            return (f"Sheet 'PMP_Translated' not found.\nSheets: {wb.sheetnames}\n"), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        ws = wb['PMP_Translated']

        header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        col_idx = {name: i for i, name in enumerate(header) if name}

        field_map = {
            'Question_ZH': 'question_zh', 'OptA_ZH': 'opt_a_zh', 'OptB_ZH': 'opt_b_zh',
            'OptC_ZH': 'opt_c_zh', 'OptD_ZH': 'opt_d_zh', 'OptE_ZH': 'opt_e_zh',
            'Explanation_ZH': 'explanation_zh',
            'Question_ES': 'question_es', 'OptA_ES': 'opt_a_es', 'OptB_ES': 'opt_b_es',
            'OptC_ES': 'opt_c_es', 'OptD_ES': 'opt_d_es', 'OptE_ES': 'opt_e_es',
            'Explanation_ES': 'explanation_es',
            'Question_JA': 'question_ja', 'OptA_JA': 'opt_a_ja', 'OptB_JA': 'opt_b_ja',
            'OptC_JA': 'opt_c_ja', 'OptD_JA': 'opt_d_ja', 'OptE_JA': 'opt_e_ja',
            'Explanation_JA': 'explanation_ja',
        }
        no_col = col_idx.get('No')
        if no_col is None:
            return (f"'No' column missing.\nHeader: {header}\n"), 200, {'Content-Type': 'text/plain; charset=utf-8'}

        updated = 0
        skipped = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            qno = row[no_col]
            if not qno:
                continue
            q = Question.query.filter_by(no=qno).first()
            if not q:
                skipped += 1
                continue
            for xlsx_col, field in field_map.items():
                ci = col_idx.get(xlsx_col)
                if ci is None:
                    continue
                val = row[ci]
                if val is not None and val != '':
                    setattr(q, field, str(val))
            updated += 1
        db.session.commit()
        return (f"OK. updated={updated}, skipped={skipped} (unmatched no).\n"
                f"Header keys mapped: {sorted(set(field_map) & set(col_idx))}\n"), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        db.session.rollback()
        # #8: log traceback server-side; do NOT return it to client
        app.logger.exception('[admin_import_translations] failed')
        return (f"FAILED: {type(e).__name__}: see server logs for details.\n"), 500, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/admin/reload_questions', methods=['GET', 'POST'])
@admin_required
def admin_reload_questions():
    """Force-reload questions from data/PMP_Raw.xlsx.
    Idempotent: load_data.py upserts by question.no, so existing rows
    are updated and new rows inserted. Safe to call multiple times.
    Useful for the EN site whose initial DB only has the 15 seed table
    questions; this populates the full 2,234-question dataset from the
    xlsx that was committed to data/."""
    filepath = 'data/PMP_Raw.xlsx'
    if not os.path.exists(filepath):
        flash(f'File not found: {filepath}', 'error')
        return redirect(url_for('admin_panel'))
    try:
        from load_data import load_questions
        count = load_questions(filepath)
        flash(f'Reloaded {count} questions from {filepath}.', 'success')
    except Exception as e:
        flash(f'Reload failed: {e}', 'error')
    return redirect(url_for('admin_panel'))


@app.route('/admin/add_user', methods=['POST'])
@admin_required
def admin_add_user():
    email = request.form.get('email', '').strip().lower()
    months = int(request.form.get('months', 3))
    is_premium = request.form.get('is_premium') == '1'

    if not email or '@' not in email:
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('admin_panel'))

    if User.query.filter_by(email=email).first():
        flash(f'{email} 은 already 등록된 사용자입니다.', 'warning')
        return redirect(url_for('admin_panel'))

    user = User(email=email, is_premium=is_premium)
    user.set_validity(months=months)
    if email in Config.ADMIN_EMAILS:
        user.is_admin = True
        user.is_premium = True
        user.set_validity(months=120)
    db.session.add(user)
    db.session.commit()
    flash(f'{email} 사용자가 Added. (Valid until {months} mo)', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/user/<int:user_id>', methods=['POST'])
@admin_required
def admin_update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('사용자를 찾을 수 없습니다.', 'error')
        return redirect(url_for('admin_panel'))

    action = request.form.get('action')

    if action == 'set_validity':
        months = int(request.form.get('months', 3))
        user.set_validity(months)
        user.is_premium = True
        flash(f'{user.email}의 Valid until을 오늘부터 {months} mo로 설정했습니다.', 'success')

    elif action == 'extend_validity':
        months = int(request.form.get('months', 3))
        user.extend_validity(months)
        user.is_premium = True
        end_date = user.validity_end.strftime('%Y-%m-%d') if user.validity_end else '?'
        flash(f'{user.email}의 Valid until을 {months} mo 연장했습니다. (Expiry: {end_date})', 'success')

    elif action == 'toggle_premium':
        user.is_premium = not user.is_premium
        if user.is_premium and not user.validity_end:
            user.set_validity(months=Config.DEFAULT_VALIDITY_MONTHS)
        flash(f'{user.email}의 Premium 상태를 변경했습니다.', 'success')

    elif action == 'set_admin_note':
        # Admin-only memo for this account. Never shown to end user.
        raw = (request.form.get('admin_note') or '').strip()
        user.admin_note = raw[:1000]
        db.session.commit()
        flash(f'Saved admin note for {user.email}.', 'success')
        return redirect(url_for('admin_panel'))

    elif action == 'toggle_admin':
        if user.id != current_user.id:
            user.is_admin = not user.is_admin
            flash(f'{user.email}의 Admin 상태를 변경했습니다.', 'success')

    elif action == 'delete':
        if user.id == current_user.id:
            flash('Cannot delete your own account.', 'error')
        else:
            # FK constraints: explicitly delete all child rows before user delete
            try:
                deleted_email = user.email
                session_ids = [s.id for s in QuizSession.query.filter_by(user_id=user.id).all()]
                if session_ids:
                    QuizAnswer.query.filter(QuizAnswer.session_id.in_(session_ids)).delete(synchronize_session=False)
                QuizSession.query.filter_by(user_id=user.id).delete()
                WrongAnswer.query.filter_by(user_id=user.id).delete()
                UserAnswerStat.query.filter_by(user_id=user.id).delete()
                Bookmark.query.filter_by(user_id=user.id).delete()
                QuestionReport.query.filter_by(user_id=user.id).delete()
                QuestionCommentVote.query.filter_by(user_id=user.id).delete()
                QuestionCommentReport.query.filter_by(reporter_id=user.id).delete()
                my_comment_ids = [c.id for c in QuestionComment.query.filter_by(user_id=user.id).all()]
                if my_comment_ids:
                    QuestionCommentVote.query.filter(QuestionCommentVote.comment_id.in_(my_comment_ids)).delete(synchronize_session=False)
                    QuestionCommentReport.query.filter(QuestionCommentReport.comment_id.in_(my_comment_ids)).delete(synchronize_session=False)
                    for cid in my_comment_ids:
                        has_children = QuestionComment.query.filter_by(parent_id=cid).first() is not None
                        c = QuestionComment.query.get(cid)
                        if has_children:
                            c.body = '[deleted account]'
                            c.is_hidden = False
                        else:
                            db.session.delete(c)
                db.session.delete(user)
                db.session.commit()
                flash(f'{deleted_email} account and related data deleted.', 'success')
                return redirect(url_for('admin_panel'))
            except Exception as e:
                db.session.rollback()
                app.logger.exception('[admin_delete_user] failed')
                flash(f'Delete failed: {type(e).__name__} — check server logs.', 'error')
                return redirect(url_for('admin_panel'))

    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/questions')
@admin_required
def admin_questions():
    """Question 검색 & 목록"""
    search = request.args.get('q', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 20

    query = Question.query
    if search:
        if search.isdigit():
            query = query.filter(Question.no == int(search))
        else:
            like = f'%{search}%'
            query = query.filter(
                Question.question.ilike(like) |
                Question.question_kr.ilike(like) |
                Question.explanation.ilike(like)
            )

    total = query.count()
    questions = query.order_by(Question.no).offset((page - 1) * per_page).limit(per_page).all()
    total_pages = (total + per_page - 1) // per_page

    return render_template('admin_questions.html',
                           questions=questions, search=search,
                           page=page, total_pages=total_pages, total=total)


@app.route('/admin/questions/<int:q_no>/edit', methods=['GET', 'POST'])
@admin_required
def admin_question_edit(q_no):
    """Question 직접 Edit"""
    q = Question.query.filter_by(no=q_no).first_or_404()

    if request.method == 'POST':
        # 영문 내용
        q.question    = request.form.get('question', '').strip()
        q.opt_a       = request.form.get('opt_a', '').strip() or None
        q.opt_b       = request.form.get('opt_b', '').strip() or None
        q.opt_c       = request.form.get('opt_c', '').strip() or None
        q.opt_d       = request.form.get('opt_d', '').strip() or None
        q.opt_e       = request.form.get('opt_e', '').strip() or None
        q.answer      = request.form.get('answer', '').strip().upper()
        q.explanation = request.form.get('explanation', '').strip() or None
        # 한국어 번역
        q.question_kr    = request.form.get('question_kr', '').strip() or None
        q.opt_a_kr       = request.form.get('opt_a_kr', '').strip() or None
        q.opt_b_kr       = request.form.get('opt_b_kr', '').strip() or None
        q.opt_c_kr       = request.form.get('opt_c_kr', '').strip() or None
        q.opt_d_kr       = request.form.get('opt_d_kr', '').strip() or None
        q.opt_e_kr       = request.form.get('opt_e_kr', '').strip() or None
        q.explanation_kr = request.form.get('explanation_kr', '').strip() or None
        # Category fields
        q.pmbok7_domain    = request.form.get('pmbok7_domain', '').strip() or None
        q.pmbok7_principle = request.form.get('pmbok7_principle', '').strip() or None
        q.pmbok8_domain    = request.form.get('pmbok8_domain', '').strip() or None
        q.pmbok8_principle = request.form.get('pmbok8_principle', '').strip() or None
        q.pmbok8_process   = request.form.get('pmbok8_process', '').strip() or None
        q.pmbok8_focus_area  = request.form.get('pmbok8_focus_area', '').strip() or None
        q.eco2021_domain   = request.form.get('eco2021_domain', '').strip() or None
        q.eco2021_task     = request.form.get('eco2021_task', '').strip() or None
        q.eco2026_domain   = request.form.get('eco2026_domain', '').strip() or None
        q.eco2026_task     = request.form.get('eco2026_task', '').strip() or None
        q.methodology      = request.form.get('methodology', '').strip() or None

        db.session.commit()
        flash(f'Question {q_no}번이 수정되었습니다.', 'success')

        next_page = request.form.get('next', '')
        return redirect(next_page if next_page else url_for('admin_questions'))

    # GET: category dropdown options
    categories = get_category_options()
    back = request.args.get('back', url_for('admin_questions'))
    return render_template('admin_question_edit.html', q=q, categories=categories, back=back)


@app.route('/admin/questions/export.json')
@admin_required
def admin_questions_export_json():
    """Export current question rows for syncing admin DB edits back to source files."""
    fields = [
        'no',
        'question', 'opt_a', 'opt_b', 'opt_c', 'opt_d', 'opt_e', 'answer', 'explanation',
        'eco2021_domain', 'eco2021_task', 'pmbok7_domain', 'pmbok7_principle',
        'methodology', 'methodology_detail',
        'eco2026_domain', 'eco2026_task', 'pmbok8_domain', 'pmbok8_focus_area',
        'pmbok8_principle', 'pmbok8_process', 'pmbok8_new_topics',
        'question_kr', 'opt_a_kr', 'opt_b_kr', 'opt_c_kr', 'opt_d_kr', 'opt_e_kr',
        'explanation_kr',
    ]
    rows = []
    for q in Question.query.order_by(Question.no).all():
        rows.append({field: getattr(q, field) for field in fields})
    return jsonify(rows)


@app.route('/admin/question_stats')
@admin_required
def admin_question_stats():
    """Admin용 Per-question accuracy"""
    stats = db.session.query(
        QuestionGlobalStat,
        Question
    ).join(Question, Question.no == QuestionGlobalStat.question_no)\
     .order_by(QuestionGlobalStat.accuracy).all()

    return render_template('admin_question_stats.html', stats=stats)

@app.route('/admin/toggle_payment', methods=['POST'])
@admin_required
def admin_toggle_payment():
    app.config['PAYMENT_ENABLED'] = not app.config.get('PAYMENT_ENABLED', False)
    status = '활성화' if app.config['PAYMENT_ENABLED'] else '비활성화'
    flash(f'Payment이 {status}되었습니다.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/load_data', methods=['POST'])
@admin_required
def admin_load_data():
    """Trigger data reload from Excel"""
    filepath = 'data/PMP_Raw.xlsx'
    if os.path.exists(filepath):
        from load_data import load_questions
        count = load_questions(filepath)
        flash(f'{count} items의 Question를 로드했습니다.', 'success')
    else:
        flash('Excel 파day을 찾을 수 없습니다.', 'error')
    return redirect(url_for('admin_panel'))

# ══════════════════════════════════════════════════════
# CONTEXT PROCESSORS
# ══════════════════════════════════════════════════════

@app.context_processor
def inject_config():
    return {
        'payment_enabled': app.config.get('PAYMENT_ENABLED', False),
        'contact_email': 'songodinfo1@gmail.com',
    }


def _days_remaining(end):
    """Whole days of access left, rounded UP. 0 once the period has passed.

    Rounding up, not down, is the point. `(end - now).days` truncates, so a
    7-day trial granted one second ago measures 6 days 23:59:59 and renders
    "6 days left" -- the member is told they already lost a day they still
    have. Worse, anyone in their final hours reads "0 days left" while the
    account still works. Ceiling makes the count match what the member was
    sold: a fresh 7-day trial says 7, and the last partial day says 1 until
    it is actually over.
    """
    if not end:
        return 0
    seconds = int((end - datetime.utcnow()).total_seconds())
    if seconds <= 0:
        return 0
    return -(-seconds // 86400)          # ceil without importing math


@app.context_processor
def inject_now():
    """`now` and `days_remaining`, which the templates already assumed existed.

    dashboard.html and base.html were both written as
    `... if now is defined else <fallback>`. Nothing ever registered `now`,
    so `now is defined` was always False and both branches silently took the
    fallback: every member saw "0 days left" on the dashboard regardless of
    their real expiry date, and the footer printed a hardcoded year.
    """
    return {
        'now': datetime.utcnow,
        'days_remaining': _days_remaining,
    }

# ══════════════════════════════════════════════════════
# BOOKMARK ROUTES
# ══════════════════════════════════════════════════════

@app.route('/bookmarks')
@login_required
def bookmarks():
    items = (Bookmark.query
             .filter_by(user_id=current_user.id)
             .order_by(Bookmark.created_at.desc())
             .all())
    return render_template('bookmarks.html', bookmarks=items)

@app.route('/api/bookmark/toggle', methods=['POST'])
@login_required
def api_bookmark_toggle():
    data = request.get_json()
    q_no = data.get('question_no')
    if not q_no:
        return jsonify({'error': 'missing question_no'}), 400

    existing = Bookmark.query.filter_by(user_id=current_user.id, question_no=q_no).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        count = Bookmark.query.filter_by(user_id=current_user.id).count()
        return jsonify({'bookmarked': False, 'count': count})
    else:
        bm = Bookmark(user_id=current_user.id, question_no=q_no)
        db.session.add(bm)
        db.session.commit()
        count = Bookmark.query.filter_by(user_id=current_user.id).count()
        return jsonify({'bookmarked': True, 'count': count})

# ══════════════════════════════════════════════════════
# REPORT ROUTES
# ══════════════════════════════════════════════════════

@app.route('/api/report', methods=['POST'])
@login_required
def api_report():
    data = request.get_json()
    q_no   = data.get('question_no')
    reason = data.get('reason', 'other')
    detail = data.get('detail', '')
    if not q_no:
        return jsonify({'error': 'missing question_no'}), 400

    # 동day 유저·동day Question 중복 pending Report 방지
    existing = QuestionReport.query.filter_by(
        user_id=current_user.id, question_no=q_no, status='pending').first()
    if existing:
        return jsonify({'ok': False, 'msg': 'You have already reported this question.'})

    rpt = QuestionReport(user_id=current_user.id, question_no=q_no,
                         reason=reason, detail=detail)
    db.session.add(rpt)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    status_filter = request.args.get('status', 'pending')
    reports = (QuestionReport.query
               .filter_by(status=status_filter)
               .order_by(QuestionReport.created_at.desc())
               .all())
    pending_count = QuestionReport.query.filter_by(status='pending').count()
    return render_template('admin_reports.html',
                           reports=reports,
                           status_filter=status_filter,
                           pending_count=pending_count)

@app.route('/admin/reports/<int:report_id>/resolve', methods=['POST'])
@login_required
@admin_required
def admin_report_resolve(report_id):
    rpt = QuestionReport.query.get_or_404(report_id)
    rpt.status = 'resolved'
    rpt.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('Report가 처리됐습니다.', 'success')
    return redirect(url_for('admin_reports'))

@app.route('/admin/reports/<int:report_id>/dismiss', methods=['POST'])
@login_required
@admin_required
def admin_report_dismiss(report_id):
    rpt = QuestionReport.query.get_or_404(report_id)
    rpt.status = 'dismissed'
    rpt.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('Report가 무시됐습니다.', 'info')
    return redirect(url_for('admin_reports'))

# ══════════════════════════════════════════════════════
# Per-question discussion comments (Premium-only, post-grading)
# ══════════════════════════════════════════════════════

COMMENT_MAX_LEN = 1500

def _comment_to_json(c, current_uid=None, voted_ids=None):
    voted_ids = voted_ids or set()
    email = (c.user.email if c.user else '') or ''
    masked = (email.split('@')[0][:3] + '***@' + email.split('@')[1]) if ('@' in email) else 'anonymous'
    return {
        'id': c.id, 'question_no': c.question_no, 'parent_id': c.parent_id,
        'body': c.body, 'upvotes': c.upvotes or 0, 'is_hidden': c.is_hidden,
        'created_at': c.created_at.isoformat() if c.created_at else None,
        'edited_at': c.edited_at.isoformat() if c.edited_at else None,
        'author_email': email, 'author_masked': masked,
        'is_admin': bool(c.user and c.user.is_admin),
        'is_mine': (current_uid is not None and c.user_id == current_uid),
        'has_voted': (c.id in voted_ids),
    }


@app.route('/api/comments/<int:question_no>', methods=['GET'])
@login_required
def api_comments_list(question_no):
    """List comments for a question — Premium only.
    Free/Trial returns premium_required=True so the UI can show the upsell."""
    if not current_user.is_paid_premium():
        return {'comments': [], 'total': 0, 'premium_required': True}, 200
    rows = (QuestionComment.query
            .filter_by(question_no=question_no, is_hidden=False)
            .order_by(QuestionComment.upvotes.desc(), QuestionComment.created_at.desc())
            .limit(200).all())
    voted_ids = set()
    if rows:
        voted_ids = set(r.comment_id for r in
                        QuestionCommentVote.query
                        .filter_by(user_id=current_user.id)
                        .filter(QuestionCommentVote.comment_id.in_([c.id for c in rows]))
                        .all())
    return {
        'comments': [_comment_to_json(c, current_user.id, voted_ids) for c in rows],
        'total': len(rows), 'premium_required': False,
    }, 200


@app.route('/api/comments/<int:question_no>', methods=['POST'])
@login_required
def api_comments_create(question_no):
    if not current_user.is_paid_premium():
        return {'error': 'Premium members only.'}, 403
    if not Question.query.filter_by(no=question_no).first():
        return {'error': 'Question not found'}, 404
    data = request.get_json(silent=True) or {}
    body = (data.get('body') or '').strip()
    if not body:
        return {'error': 'Body is required.'}, 400
    if len(body) > COMMENT_MAX_LEN:
        return {'error': f'Max {COMMENT_MAX_LEN} characters.'}, 400
    parent_id = data.get('parent_id')
    if parent_id is not None:
        parent = QuestionComment.query.get(parent_id)
        if not parent or parent.question_no != question_no or parent.parent_id is not None:
            return {'error': 'Invalid parent_id.'}, 400
    c = QuestionComment(question_no=question_no, user_id=current_user.id,
                        parent_id=parent_id, body=body)
    db.session.add(c)
    db.session.commit()
    return {'comment': _comment_to_json(c, current_user.id)}, 201


@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def api_comments_delete(comment_id):
    c = QuestionComment.query.get_or_404(comment_id)
    if c.user_id != current_user.id and not current_user.is_admin:
        return {'error': 'forbidden'}, 403
    has_children = QuestionComment.query.filter_by(parent_id=c.id).first() is not None
    if has_children:
        c.body = '[deleted]'
        c.is_hidden = False
        c.edited_at = datetime.utcnow()
    else:
        QuestionCommentVote.query.filter_by(comment_id=c.id).delete()
        QuestionCommentReport.query.filter_by(comment_id=c.id).delete()
        db.session.delete(c)
    db.session.commit()
    return {'ok': True}, 200


@app.route('/api/comments/<int:comment_id>/vote', methods=['POST'])
@login_required
def api_comments_vote(comment_id):
    if not current_user.is_paid_premium():
        return {'error': 'Premium members only.'}, 403
    c = QuestionComment.query.get_or_404(comment_id)
    if c.user_id == current_user.id:
        return {'error': 'Cannot vote on your own comment.'}, 400
    existing = QuestionCommentVote.query.filter_by(comment_id=c.id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        c.upvotes = max(0, (c.upvotes or 0) - 1)
        voted = False
    else:
        db.session.add(QuestionCommentVote(comment_id=c.id, user_id=current_user.id))
        c.upvotes = (c.upvotes or 0) + 1
        voted = True
    db.session.commit()
    return {'voted': voted, 'upvotes': c.upvotes}, 200


@app.route('/api/comments/<int:comment_id>/report', methods=['POST'])
@login_required
def api_comments_report(comment_id):
    c = QuestionComment.query.get_or_404(comment_id)
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or 'other').strip()[:50]
    detail = (data.get('detail') or '').strip()[:500]
    existing = QuestionCommentReport.query.filter_by(comment_id=c.id, reporter_id=current_user.id).first()
    if existing:
        return {'error': 'Already reported.'}, 400
    rep = QuestionCommentReport(comment_id=c.id, reporter_id=current_user.id,
                                reason=reason, detail=detail)
    db.session.add(rep)
    c.report_count = (c.report_count or 0) + 1
    if (c.report_count or 0) >= 3 and not c.is_hidden:
        c.is_hidden = True
    db.session.commit()
    return {'ok': True}, 200


@app.route('/admin/comments')
@login_required
@admin_required
def admin_comments():
    pending_reports = (QuestionCommentReport.query.filter_by(status='pending')
                       .order_by(QuestionCommentReport.created_at.desc()).limit(100).all())
    recent_comments = (QuestionComment.query
                       .order_by(QuestionComment.created_at.desc()).limit(100).all())
    return render_template('admin_comments.html',
                           pending_reports=pending_reports,
                           recent_comments=recent_comments)


@app.route('/admin/comments/<int:comment_id>/hide', methods=['POST'])
@login_required
@admin_required
def admin_comment_hide(comment_id):
    c = QuestionComment.query.get_or_404(comment_id)
    c.is_hidden = True
    QuestionCommentReport.query.filter_by(comment_id=c.id, status='pending')\
        .update({'status': 'actioned'})
    db.session.commit()
    return {'ok': True}, 200


@app.route('/admin/comments/<int:comment_id>/restore', methods=['POST'])
@login_required
@admin_required
def admin_comment_restore(comment_id):
    c = QuestionComment.query.get_or_404(comment_id)
    c.is_hidden = False
    QuestionCommentReport.query.filter_by(comment_id=c.id, status='pending')\
        .update({'status': 'dismissed'})
    db.session.commit()
    return {'ok': True}, 200

# ══════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='You do not have permission to access this page.'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='Sorry, we could not find that page.'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message='Something went wrong on our end. Please try again.'), 500


# ══════════════════════════════════════════════════════
# BLOG (PMP study guides — public content for AdSense)
# ══════════════════════════════════════════════════════
PUBLIC_SAMPLE_SIZE = 180
_PUBLIC_SAMPLE_CACHE = None

# Domain grouping order used on the public learning hub.
_PUBLIC_TAG_ATTRS = ('eco2026_domain', 'pmbok8_domain', 'eco2021_domain',
                     'pmbok7_domain', 'methodology')


def get_public_sample_nos():
    """Question numbers that are public (login-free, search-indexable).

    Picks questions that have both an English stem and an English explanation,
    spread evenly across the whole pool so every domain is represented.
    Result is cached for the life of the process.
    """
    global _PUBLIC_SAMPLE_CACHE
    if _PUBLIC_SAMPLE_CACHE is not None:
        return _PUBLIC_SAMPLE_CACHE
    try:
        rows = (db.session.query(Question.no)
                .filter(Question.no < 9000)          # exclude demo/seed items
                .filter(Question.question.isnot(None), Question.question != '')
                .filter(Question.explanation.isnot(None), Question.explanation != '')
                .order_by(Question.no).all())
        nos = [r[0] for r in rows]
    except Exception:
        nos = []
    if len(nos) <= PUBLIC_SAMPLE_SIZE:
        sample = nos
    else:
        step = len(nos) / float(PUBLIC_SAMPLE_SIZE)
        sample = [nos[int(i * step)] for i in range(PUBLIC_SAMPLE_SIZE)]
    _PUBLIC_SAMPLE_CACHE = sample
    return sample


def _q_short_title(q, limit=70):
    """Short, readable title for list/related links."""
    src = (q.question or '').strip().replace('\n', ' ')
    src = re.sub(r'\s+', ' ', src)
    if len(src) > limit:
        src = src[:limit].rstrip() + '...'
    return src or f'PMP practice question {q.no}'


def _q_primary_tag(q):
    """Single representative classification tag (used in titles/SEO)."""
    for attr in _PUBLIC_TAG_ATTRS:
        v = getattr(q, attr, None)
        if v:
            return v
    return None


def _q_tags(q):
    """De-duplicated list of classification tags for display."""
    seen, tags = set(), []
    for attr in _PUBLIC_TAG_ATTRS:
        v = getattr(q, attr, None)
        if v and v not in seen:
            seen.add(v)
            tags.append(v)
    return tags


@app.route('/learn')
def learn_index():
    """Public PMP learning hub for AdSense review and search visitors."""
    if not _BLOG_INDEX_CACHE:
        _load_blog()
    sample_nos = get_public_sample_nos()
    groups = []
    total = 0
    if sample_nos:
        questions = Question.query.filter(Question.no.in_(sample_nos)).all()
        q_map = {q.no: q for q in questions}
        ordered = [q_map[n] for n in sample_nos if n in q_map]
        total = len(ordered)
        groups_map = {}
        for q in ordered:
            key = _q_primary_tag(q) or 'Other topics'
            groups_map.setdefault(key, []).append(
                {'no': q.no, 'title': _q_short_title(q)})
        groups = [{'title': f'{k} ({len(v)} questions)', 'rows': v}
                  for k, v in sorted(groups_map.items(),
                                     key=lambda kv: (-len(kv[1]), kv[0]))]
    return render_template('learn.html', posts=_BLOG_INDEX_CACHE[:8],
                           groups=groups, total=total)


@app.route('/learn/<int:no>')
def learn_question(no):
    """Public sample question - stem, options, answer and explanation, no login."""
    sample_nos = get_public_sample_nos()
    if no not in sample_nos:
        abort(404)          # keep the rest of the bank behind the paywall
    q = Question.query.filter_by(no=no).first()
    if not q:
        abort(404)

    ans_list = q.get_answer_list()
    options = []
    for letter in ['A', 'B', 'C', 'D', 'E']:
        text = getattr(q, f'opt_{letter.lower()}', None)
        if text:
            options.append({'letter': letter, 'text': text,
                            'correct': letter in ans_list})

    idx = sample_nos.index(no)
    prev_no = sample_nos[idx - 1] if idx > 0 else None
    next_no = sample_nos[idx + 1] if idx < len(sample_nos) - 1 else None

    pool = [n for n in sample_nos if n != no]
    start = max(0, min(idx, len(pool) - 3))
    pick = pool[start:start + 3] if pool else []
    related = []
    if pick:
        rel_qs = Question.query.filter(Question.no.in_(pick)).all()
        rel_map = {r.no: r for r in rel_qs}
        related = [{'no': n, 'title': _q_short_title(rel_map[n])}
                   for n in pick if n in rel_map]

    tags = _q_tags(q)
    primary_tag = tags[0] if tags else None
    stem = re.sub(r'\s+', ' ', (q.question or '').strip())
    # SEO title. Every public /learn page used to be titled
    # "PMP Practice Question <no> - <2026 ECO domain>". That domain has only
    # three values (People / Process / Business Environment), so all 180
    # indexed pages shared four title patterns differing by a number and
    # nothing else: no text anyone searches for, and near-duplicate to a
    # crawler. GSC showed the result - 203 pages indexed, average position
    # 19.4, 7 clicks in three months.
    # Now: the PMBOK8 performance domain (Stakeholders / Governance / Finance
    # / Risk / ... - twelve values, more specific than the ECO domain) leads,
    # so "PMP" and the knowledge area survive Google's ~60-character display
    # truncation, followed by the scenario text so the visible portion is also
    # unique page to page and matches long-tail queries.
    topic = getattr(q, 'pmbok8_domain', None) or primary_tag
    lead = f'PMP {topic} Question' if topic else 'PMP Practice Question'
    seo_title = f'{lead}: {_q_short_title(q, limit=60)}'
    # Visible heading can run longer than the <title> budget. The question
    # number stays in the breadcrumb, so it is not lost.
    heading = _q_short_title(q, limit=110)
    seo_desc = (stem[:150] + '...') if len(stem) > 150 else stem

    return render_template('learn_question.html',
                           question=q, options=options,
                           answer_str=', '.join(ans_list),
                           tags=tags, primary_tag=primary_tag,
                           tag_keywords=', '.join(tags),
                           seo_title=seo_title, seo_desc=seo_desc,
                           heading=heading,
                           prev_no=prev_no, next_no=next_no, related=related)


_BLOG_CACHE = {}
_BLOG_INDEX_CACHE = []
_BLOG_DB_LOADED = False
_BLOG_DB_SIG = None


def _parse_frontmatter(text):
    meta = {}
    body = text
    if text.startswith('---'):
        end = text.find('\n---', 3)
        if end != -1:
            block = text[3:end].strip()
            body = text[end + 4:].lstrip('\n')
            for line in block.split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _md_to_html(md):
    import html as _html
    lines = md.split('\n')
    out = []
    i = 0
    n = len(lines)

    def inline(text):
        text = _html.escape(text)
        text = re.sub(r'\*\*([^\*\n]+)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'(?<!\*)\*([^\*\n]+)\*(?!\*)', r'<em>\1</em>', text)
        text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                      lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
        return text

    while i < n:
        line = lines[i]
        s = line.rstrip()
        if not s.strip():
            i += 1
            continue
        m = re.match(r'^(#{1,6})\s+(.*)$', s)
        if m:
            level = len(m.group(1))
            out.append(f'<h{level}>{inline(m.group(2))}</h{level}>')
            i += 1
            continue
        if s.lstrip().startswith('> '):
            block = []
            while i < n and lines[i].lstrip().startswith('> '):
                block.append(lines[i].lstrip()[2:])
                i += 1
            out.append('<blockquote>' + inline(' '.join(block)) + '</blockquote>')
            continue
        if s.lstrip().startswith('|') and i + 1 < n and re.match(r'^\s*\|[\s\-:|]+\|\s*$', lines[i + 1]):
            header_cells = [c.strip() for c in s.strip().strip('|').split('|')]
            i += 2
            rows = []
            while i < n and lines[i].lstrip().startswith('|'):
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
                i += 1
            tbl = ['<table>']
            tbl.append('<tr>' + ''.join(f'<th>{inline(c)}</th>' for c in header_cells) + '</tr>')
            for r in rows:
                tbl.append('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>')
            tbl.append('</table>')
            out.append('\n'.join(tbl))
            continue
        if re.match(r'^\s*[-*]\s+', s):
            items = []
            while i < n and re.match(r'^\s*[-*]\s+', lines[i]):
                items.append(re.sub(r'^\s*[-*]\s+', '', lines[i]).rstrip())
                i += 1
            out.append('<ul>' + ''.join(f'<li>{inline(it)}</li>' for it in items) + '</ul>')
            continue
        if re.match(r'^\s*\d+\.\s+', s):
            items = []
            while i < n and re.match(r'^\s*\d+\.\s+', lines[i]):
                items.append(re.sub(r'^\s*\d+\.\s+', '', lines[i]).rstrip())
                i += 1
            out.append('<ol>' + ''.join(f'<li>{inline(it)}</li>' for it in items) + '</ol>')
            continue
        para = [s]
        i += 1
        while i < n and lines[i].strip() and not re.match(
            r'^(#{1,6}\s|\s*[-*]\s+|\s*\d+\.\s+|\||>\s)', lines[i]
        ):
            para.append(lines[i].rstrip())
            i += 1
        out.append('<p>' + inline(' '.join(para)) + '</p>')
    return '\n'.join(out)


def _blog_db_signature():
    """Cheap fingerprint of the published-post table: (row count, newest update).

    Each gunicorn worker holds its own _BLOG_CACHE. A post published through
    /blog/publish therefore refreshes only the worker that happened to serve
    that POST; every other worker kept answering 404 for the new slug, and
    kept it out of /blog and /sitemap.xml, until the service was restarted.
    Observed live on 2026-09-19: the same URL alternated 200 and 404 by worker.

    Comparing this two-value fingerprint on each blog request lets any worker
    notice another worker's publish and reload on its next request. Returns
    None when the query fails, which leaves the existing cache in place.
    """
    try:
        return db.session.query(
            func.count(BlogPost.id), func.max(BlogPost.updated_at)
        ).select_from(BlogPost).filter(BlogPost.published.is_(True)).one()
    except Exception:
        try: db.session.rollback()
        except Exception: pass
        return None


def _blog_refresh_if_stale():
    """Reload the per-worker blog cache if another worker changed the table."""
    if app.config.get('DEBUG') or not _BLOG_DB_LOADED:
        _load_blog()
        return
    sig = _blog_db_signature()
    if sig is not None and sig != _BLOG_DB_SIG:
        _load_blog()


def _load_blog():
    global _BLOG_CACHE, _BLOG_INDEX_CACHE
    _BLOG_CACHE = {}
    blog_dir = os.path.join(app.root_path, 'templates', 'blog')
    if not os.path.isdir(blog_dir):
        _BLOG_INDEX_CACHE = []
        return
    posts = []
    for fname in os.listdir(blog_dir):
        if not fname.endswith('.md'):
            continue
        slug = fname[:-3]
        try:
            with open(os.path.join(blog_dir, fname), 'r', encoding='utf-8') as f:
                meta, body = _parse_frontmatter(f.read())
            html_body = _md_to_html(body)
            _BLOG_CACHE[slug] = {'slug': slug, 'meta': meta, 'html': html_body}
            posts.append({
                'slug': slug,
                'title': meta.get('title', slug),
                'summary': meta.get('summary', ''),
                'date': meta.get('date', ''),
            })
        except Exception as e:
            try: app.logger.warning(f'[BLOG] failed to load {fname}: {e}')
            except Exception: print(f'[BLOG] failed to load {fname}: {e}')
    # DB-published posts (added at runtime via /blog/publish). Additive:
    # a row with the same slug overrides the file-based post.
    global _BLOG_DB_LOADED
    try:
        for row in BlogPost.query.filter_by(published=True).all():
            meta, body = _parse_frontmatter(row.body_md)
            _BLOG_CACHE[row.slug] = {
                'slug': row.slug, 'meta': meta, 'html': _md_to_html(body),
            }
            posts = [p for p in posts if p['slug'] != row.slug]
            posts.append({
                'slug': row.slug,
                'title': meta.get('title', row.slug),
                'summary': meta.get('summary', ''),
                'date': meta.get('date', ''),
            })
        _BLOG_DB_LOADED = True
        global _BLOG_DB_SIG
        _BLOG_DB_SIG = _blog_db_signature()
    except Exception as e:
        # DB not ready yet (module import happens before create_all). The first
        # /blog request retries via _BLOG_DB_LOADED below.
        try: app.logger.info(f'[BLOG] db posts not loaded yet: {e}')
        except Exception: pass

    posts.sort(key=lambda p: p['date'], reverse=True)
    _BLOG_INDEX_CACHE = posts


_load_blog()


@app.route('/blog')
def blog_index():
    _blog_refresh_if_stale()
    return render_template('blog_index.html', posts=_BLOG_INDEX_CACHE)


@app.route('/blog/<slug>')
def blog_post(slug):
    _blog_refresh_if_stale()
    entry = _BLOG_CACHE.get(slug)
    if not entry:
        abort(404)
    related = [p for p in _BLOG_INDEX_CACHE if p['slug'] != slug][:3]
    return render_template('blog_post.html',
        post=entry, meta=entry['meta'], body_html=entry['html'], related=related)


@app.route('/blog/publish', methods=['POST'])
def blog_publish():
    """Publish or update one blog post at runtime.

    Disabled unless BLOG_PUBLISH_TOKEN is set in the environment. Authenticates
    with the X-Publish-Token header. Body: JSON {"slug": "...", "markdown": "..."}
    where markdown is the full file content including frontmatter.
    """
    expected = os.environ.get('BLOG_PUBLISH_TOKEN', '')
    if not expected:
        abort(404)  # feature off -> endpoint does not exist
    supplied = request.headers.get('X-Publish-Token', '')
    if not hmac.compare_digest(supplied, expected):
        abort(403)

    payload = request.get_json(silent=True) or {}
    slug = (payload.get('slug') or '').strip()
    markdown = payload.get('markdown') or ''

    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,79}', slug):
        return jsonify(ok=False, error='invalid slug'), 400
    if not (50 <= len(markdown) <= 200000):
        return jsonify(ok=False, error='markdown length out of range'), 400

    meta, _body = _parse_frontmatter(markdown)
    for field in ('title', 'summary', 'date', 'read_time', 'keywords'):
        if not meta.get(field):
            return jsonify(ok=False, error=f'missing frontmatter field: {field}'), 400

    row = BlogPost.query.filter_by(slug=slug).first()
    created = row is None
    if created:
        row = BlogPost(slug=slug)
        db.session.add(row)
    row.body_md = markdown
    row.published = True
    db.session.commit()

    _load_blog()
    return jsonify(ok=True, slug=slug, created=created,
                   url=url_for('blog_post', slug=slug, _external=True)), (201 if created else 200)


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


# ══════════════════════════════════════════════════════
# SEO ROUTES
# ══════════════════════════════════════════════════════

@app.route('/robots.txt')
def robots_txt():
    base = app.config.get('PRIMARY_HOST', PRIMARY_HOST or 'wayexam.com')
    body = ('User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /admin/\n'
            f'Disallow: /api/\n\nSitemap: https://{base}/sitemap.xml\n')
    return body, 200, {'Content-Type': 'text/plain'}


@app.route('/sitemap.xml')
def sitemap_xml():
    """Dynamic sitemap including blog URLs."""
    _blog_refresh_if_stale()
    today = datetime.utcnow().strftime('%Y-%m-%d')
    base = 'https://' + app.config.get('PRIMARY_HOST', PRIMARY_HOST or 'wayexam.com')
    urls = [
        ('/', '1.0', 'weekly'),
        ('/free', '0.9', 'weekly'),
        ('/learn', '0.9', 'weekly'),
        ('/blog', '0.9', 'weekly'),
        ('/pricing', '0.8', 'monthly'),
        ('/signup', '0.5', 'monthly'),
        ('/about', '0.6', 'monthly'),
        ('/privacy', '0.3', 'yearly'),
        ('/terms', '0.3', 'yearly'),
    ]
    try:
        for p in _BLOG_INDEX_CACHE:
            urls.append((f"/blog/{p['slug']}", '0.7', 'monthly'))
    except NameError:
        pass
    # Public sample questions - every /learn/<no> detail page is indexable
    try:
        for _no in get_public_sample_nos():
            urls.append((f"/learn/{_no}", '0.6', 'monthly'))
    except Exception:
        pass
    body = '<?xml version="1.0" encoding="UTF-8"?>\n'
    body += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for loc, pri, cf in urls:
        body += f'  <url><loc>{base}{loc}</loc><lastmod>{today}</lastmod><changefreq>{cf}</changefreq><priority>{pri}</priority></url>\n'
    body += '</urlset>\n'
    return body, 200, {'Content-Type': 'application/xml'}

@app.route('/llms.txt')
def llms_txt():
    """Serve llms.txt for AI indexing"""
    try:
        with open(os.path.join(app.static_folder, 'llms.txt'), 'r') as f:
            content = f.read()
        return content, 200, {'Content-Type': 'text/plain'}
    except FileNotFoundError:
        abort(404)

@app.route('/ads.txt')
def ads_txt():
    """Serve ads.txt for Google AdSense publisher verification.
    Format: 'google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, f08c47fec0942fa0'
    Generated dynamically from ADSENSE_PUBLISHER_ID env var.
    """
    publisher = app.config.get('ADSENSE_PUBLISHER_ID', '')
    if not publisher:
        abort(404)
    pub_id = publisher.replace('ca-pub-', 'pub-') if publisher.startswith('ca-pub-') else publisher
    body = f'google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n'
    return body, 200, {'Content-Type': 'text/plain'}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)


# i18n: language resolver (added by transform.py)
# 'ko' is the secondary translation (Korean) — DB columns use legacy `_kr` suffix.
SUPPORTED_LANGS = ('en', 'ko', 'zh', 'es', 'ja')

@app.before_request
def _resolve_lang():
    from flask import g, request
    lang = request.cookies.get('lang', 'en')
    if lang not in SUPPORTED_LANGS:
        lang = 'en'
    g.lang = lang

@app.context_processor
def _inject_lang():
    from flask import g
    return {'current_lang': getattr(g, 'lang', 'en'),
            'supported_langs': SUPPORTED_LANGS}

@app.route('/lang/<lang>')
def set_lang(lang):
    from flask import redirect, request, make_response
    if lang not in SUPPORTED_LANGS:
        lang = 'en'
    resp = make_response(redirect(request.referrer or '/'))
    resp.set_cookie('lang', lang, max_age=60*60*24*365, samesite='Lax')
    return resp


@app.route('/admin/apply_question_fixes')
@admin_required
def admin_apply_question_fixes():
    """일회성 hotfix: 사용자 신고 4건 정정 (Q990 / Q1513 / Q1768 / Q1196)."""
    fixes = [
        {'no': 990,  'answer': 'D'},
        {'no': 1513, 'answer': 'B, E', 'opt_d': 'Project schedule'},
        {'no': 1768, 'answer': 'B'},
        {'no': 1196, 'question_kr': '」+'},  # placeholder, replaced below
    ]
    fixes[3]['question_kr'] = (
        '프로젝트 관리자가 최근 하이브리드 프로젝트에 배정되었다. '
        '팀에 합류한 지 몇 개월 후, 프로젝트 관리자는 '
        '이 프로젝트의 일부가 조직 내 다른 프로젝트들과 의존성이 '
        '있다는 사실을 깨달았다. 이러한 의존성은 아직 식별되지 않았다. '
        '프로젝트 관리자는 무엇을 해야 하는가?'
    )
    results = []
    for fix in fixes:
        q = Question.query.filter_by(no=fix['no']).first()
        if not q:
            results.append('Q' + str(fix['no']) + ': NOT FOUND')
            continue
        changes = []
        if 'answer' in fix and (q.answer or '').strip() != fix['answer']:
            changes.append('answer ' + repr(q.answer) + ' -> ' + repr(fix['answer']))
            q.answer = fix['answer']
        if 'opt_d' in fix and (q.opt_d or '').strip() != fix['opt_d']:
            changes.append('opt_d updated')
            q.opt_d = fix['opt_d']
        if 'question_kr' in fix and (q.question_kr or '').strip() != fix['question_kr'].strip():
            changes.append('question_kr updated')
            q.question_kr = fix['question_kr']
        results.append('Q' + str(fix['no']) + ': ' + (', '.join(changes) if changes else 'no change needed'))
    db.session.commit()
    body = '<h2>Question Fixes Applied</h2><ul>' + ''.join('<li>' + r + '</li>' for r in results) + '</ul>'
    body += '<p><a href="/dashboard">&larr; Dashboard</a> &middot; <a href="/admin">Admin</a></p>'
    return body


@app.route('/admin/cleanup_question_text')
@admin_required
def admin_cleanup_question_text():
    """일회성 정리: PMP KR과 동일한 일괄 텍스트 오류 수정.

    1) 보기 끝에 붙은 잔여 숫자 제거   (PDF 추출 흔적, 예: '... syndication. 1216')
    2) 한글 보기 앞 중복 라벨 제거      (예: 'A. A. 팀 위키에...' -> 'A. ' 제거)
    3) 개별 정정 (Q51 깨진 글자 / Q1610 오역 / Q2115 해설 라벨 오타)

    문제 테이블만 UPDATE한다. 회원·풀이기록 테이블은 일절 건드리지 않는다.
    ?dry=1 을 붙이면 미리보기만 하고 커밋하지 않는다.
    """
    import re as _re

    dry = request.args.get('dry') == '1'
    OPT_EN = ['opt_a', 'opt_b', 'opt_c', 'opt_d', 'opt_e']
    OPT_KR = [c + '_kr' for c in OPT_EN]

    TRAIL_NUM = _re.compile(r'\s+\d{3,4}\s*$')
    DUP_LABEL = _re.compile(r'^\s*([A-E])\.\s+')

    changes = []

    for q in Question.query.order_by(Question.no).all():
        for field in OPT_EN + OPT_KR:
            val = getattr(q, field, None)
            if not val:
                continue
            new = TRAIL_NUM.sub('', val)
            if field in OPT_KR:
                letter = field[4].upper()
                m = DUP_LABEL.match(new)
                if m and m.group(1) == letter:
                    new = DUP_LABEL.sub('', new, count=1)
            new = new.strip()
            if new and new != val:
                changes.append((q.no, field, val, new))
                if not dry:
                    setattr(q, field, new)

    Q1610_KR = (
        '한 조직이 비즈니스 프로젝트에 하이브리드 전달 방식을 사용하고 있다. '
        '프로젝트를 관리하기도 했던 제품 책임자가 더 상위 직책으로 승진했고, '
        '새로운 프로젝트 리더가 프로젝트에 합류했다. 프로젝트 리더가 '
        '프로젝트 편익이 식별되었는지 확인하려면 어떤 산출물을 사용해야 하는가?'
    )
    Q2115_EXP = (
        '대규모 퇴사로 자원 제약이 생기면 납품 역량이 감소한다. 문제는 "다가오는 목표일을 '
        '맞추면서 지연을 복구"하는 방법을 묻고 있다. 크래싱(A)은 자원을 추가 투입하는 기법인데 '
        '투입할 인력 자체가 없어 불가능하다. 패스트트래킹(B)은 활동을 병행해 리스크와 재작업을 '
        '키우며 이 역시 추가 역량을 전제로 한다. 목표일 수정(D)은 일정 자체를 바꾸는 것이므로 '
        '"복구"가 아니라 재기준선 설정이다. 따라서 가용 역량에 맞게 작업을 재우선순위화하는 '
        '범위 축소(C)가 남는 유일한 실행 가능한 복구 수단이다. 다만 범위 축소는 PM이 단독으로 '
        '결정할 수 없으며, 변경요청을 제출해 스폰서·주요 이해관계자의 승인을 받아 통합 변경통제 '
        '절차를 거쳐야 한다.'
    )

    singles = [
        {'no': 51,   'question_kr': lambda v: v.replace('괰5범위한', '광범위한')},
        {'no': 1610, 'question_kr': lambda v: Q1610_KR},
        {'no': 2115, 'explanation_kr': lambda v: Q2115_EXP},
    ]
    for s in singles:
        q = Question.query.filter_by(no=s['no']).first()
        if not q:
            changes.append((s['no'], '(not found)', '', ''))
            continue
        for field, fn in s.items():
            if field == 'no':
                continue
            before = getattr(q, field, None) or ''
            if not before:
                continue
            after = fn(before)
            if after and after != before:
                changes.append((q.no, field, before, after))
                if not dry:
                    setattr(q, field, after)

    if not dry:
        db.session.commit()

    by_field = {}
    for no, field, _b, _a in changes:
        by_field[field] = by_field.get(field, 0) + 1

    head = ('<h2>Question text cleanup %s</h2>' % ('preview (dry run, nothing saved)' if dry else 'applied'))
    head += '<p>total <b>%d</b> / by field: %s</p>' % (
        len(changes), ', '.join('%s=%d' % kv for kv in sorted(by_field.items())))
    rows = ''.join(
        '<tr><td>Q%s</td><td>%s</td><td style="color:#b91c1c">%s</td>'
        '<td style="color:#047857">%s</td></tr>' % (
            no, field,
            (b[-70:] if b else '').replace('<', '&lt;'),
            (a[-70:] if a else '').replace('<', '&lt;'))
        for no, field, b, a in changes)
    body = (head +
            '<table border=1 cellpadding=4 style="border-collapse:collapse;font-size:12px">'
            '<tr><th>Q</th><th>field</th><th>before (last 70)</th><th>after</th></tr>'
            + rows + '</table>'
            '<p><a href="/admin/reports">&larr; Reports</a> &middot; '
            '<a href="/admin">Admin</a></p>')
    return body


@app.route('/q/<int:q_no>')
@login_required
def jump_to_question(q_no):
    """Q번호로 즉시 조회 — admin은 edit 페이지로, 일반 사용자는 1문제 quiz session 시작."""
    q = Question.query.filter_by(no=q_no).first()
    if not q:
        flash(f'Q{q_no}: no question with that number exists.', 'warning')
        return redirect(url_for('dashboard'))
    if current_user.is_admin:
        return redirect(url_for('admin_question_edit', q_no=q_no))
    # Regular user: 1-question quiz session
    quiz_session = QuizSession(
        user_id=current_user.id,
        mode='category',
        filter_type='question_no',
        filter_value=str(q_no),
        total_questions=1,
    )
    db.session.add(quiz_session)
    db.session.commit()
    session['quiz_session_id'] = quiz_session.id
    session['quiz_questions'] = [q_no]
    session['quiz_answers'] = {}
    session['quiz_current'] = 0
    return redirect(url_for('quiz_question'))


@app.route('/admin/resync_kr_translations')
@admin_required
def admin_resync_kr_translations():
    """PMP_Raw.xlsx의 한글 번역을 DB에 일괄 동기화 (영문은 건드리지 않음)."""
    import os, openpyxl
    xlsx_path = os.getenv('PMP_RAW_XLSX_PATH', '/app/PMP_Raw.xlsx')
    if not os.path.exists(xlsx_path):
        return f'<p style="color:red">xlsx 파일이 서버에 없음: {xlsx_path}</p><p>Railway env var <code>PMP_RAW_XLSX_PATH</code> 또는 파일 경로 확인.</p>'
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb['PMP_All_Data']
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    def col(name, occ=0):
        m = [i for i, h in enumerate(headers) if h == name]
        return m[occ] if len(m) > occ else None

    NO = col('No')
    cols = {
        'question_kr': col('Question_KR'),
        'opt_a_kr': col('A_KR'),
        'opt_b_kr': col('B_KR'),
        'opt_c_kr': col('C_KR'),
        'opt_d_kr': col('D_KR'),
        'opt_e_kr': col('E_KR'),
        'explanation_kr': col('Explanation_KR'),
    }

    results = {'updated': 0, 'unchanged': 0, 'not_found': 0, 'fields_changed': 0}
    samples = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        no = row[NO]
        if not no: continue
        q = Question.query.filter_by(no=no).first()
        if not q:
            results['not_found'] += 1
            continue
        any_change = False
        for attr, ci in cols.items():
            if ci is None: continue
            new_val = (str(row[ci]).strip() if row[ci] not in (None, '') else None)
            cur_val = getattr(q, attr, None)
            cur_val_str = (cur_val.strip() if isinstance(cur_val, str) else cur_val)
            # Only update if different (and new_val not None unless current is)
            if new_val != cur_val_str:
                setattr(q, attr, new_val)
                results['fields_changed'] += 1
                any_change = True
                if len(samples) < 30:
                    samples.append(f"Q{no} {attr}: {repr(cur_val_str)[:40]} -> {repr(new_val)[:40]}")
        if any_change:
            results['updated'] += 1
        else:
            results['unchanged'] += 1
    db.session.commit()
    wb.close()

    body = '<h2>KR Translation Resync Result</h2>'
    body += '<ul>'
    body += f'<li>Updated questions: <b>{results["updated"]}</b></li>'
    body += f'<li>Unchanged: {results["unchanged"]}</li>'
    body += f'<li>Total fields changed: <b>{results["fields_changed"]}</b></li>'
    body += f'<li>Not found in DB: {results["not_found"]}</li>'
    body += '</ul>'
    if samples:
        body += '<h3>Sample changes (first 30):</h3><pre style="font-size:12px;background:#f5f5f5;padding:10px;border-radius:6px">' + '\n'.join(samples) + '</pre>'
    body += '<p><a href="/dashboard">Dashboard</a></p>'
    return body


@app.route('/admin/apply_kr_translation_fixes')
@admin_required
def admin_apply_kr_translation_fixes():
    """Apply 84 Korean translation fixes from kr_translation_fixes.py BATCH dict."""
    from kr_translation_fixes import BATCH
    results = {'updated': 0, 'unchanged': 0, 'not_found': 0, 'fields_changed': 0}
    not_found = []
    samples = []
    for no, fields in BATCH.items():
        q = Question.query.filter_by(no=no).first()
        if not q:
            results['not_found'] += 1
            not_found.append(no)
            continue
        any_change = False
        for field, val in fields.items():
            if not hasattr(q, field):
                continue
            cur = getattr(q, field)
            cur_s = (cur or '').strip() if isinstance(cur, str) else cur
            new_s = (val or '').strip() if isinstance(val, str) else val
            if cur_s != new_s:
                setattr(q, field, val)
                results['fields_changed'] += 1
                any_change = True
                if len(samples) < 30:
                    samples.append(f'Q{no} {field}: {len(cur_s) if cur_s else 0} -> {len(new_s)} chars')
        if any_change:
            results['updated'] += 1
        else:
            results['unchanged'] += 1
    db.session.commit()

    body = '<h2>KR Translation Fixes Applied (Batches 1+2+3)</h2>'
    body += '<ul>'
    body += f'<li>Total in BATCH dict: <b>{len(BATCH)}</b> questions</li>'
    body += f'<li>Updated: <b>{results["updated"]}</b></li>'
    body += f'<li>Unchanged (already current): {results["unchanged"]}</li>'
    body += f'<li>Total fields changed: <b>{results["fields_changed"]}</b></li>'
    body += f'<li>Not found in DB: {results["not_found"]} {not_found if not_found else ""}</li>'
    body += '</ul>'
    if samples:
        body += '<h3>Sample changes (first 30 fields):</h3><pre style="font-size:12px;background:#f5f5f5;padding:10px;border-radius:6px">' + '\n'.join(samples) + '</pre>'
    body += '<p><a href="/dashboard">Dashboard</a> &middot; <a href="/admin">Admin</a></p>'
    return body


@app.route('/admin/cleanup_old_seed')
@admin_required
def admin_cleanup_old_seed():
    """Remove legacy table-seed questions (no=90001-90015).
    Deletes child records first (bookmarks/wrong_answers/stats/reports/answers),
    then the questions themselves. Idempotent."""
    try:
        from sqlalchemy import text as _sql
        deleted = []
        skipped = []
        for old_no in range(90001, 90016):
            # Delete child rows first (FK constraints may not have CASCADE)
            for tbl in ['bookmarks', 'wrong_answers', 'question_global_stats',
                        'question_reports', 'quiz_answers', 'user_answer_stats']:
                try:
                    db.session.execute(_sql(f'DELETE FROM {tbl} WHERE question_no = :n'),
                                       {'n': old_no})
                except Exception as ce:
                    print(f'  child delete {tbl}/{old_no} skipped: {ce}')
            # Now the question itself
            q = Question.query.filter_by(no=old_no).first()
            if q:
                db.session.delete(q)
                deleted.append(old_no)
            else:
                skipped.append(old_no)
        db.session.commit()
        body = '<h2>Old Seed Cleanup</h2>'
        body += f'<p>Deleted {len(deleted)} legacy questions: {deleted}</p>'
        body += f'<p>Already absent: {skipped}</p>'
        body += '<p>Now run /admin/reload_questions (EN) or /admin/load_data (KR) to import 2236-2250.</p>'
        body += '<p><a href="/dashboard">Dashboard</a> &middot; <a href="/admin">Admin</a></p>'
        return body
    except Exception as e:
        db.session.rollback()
        # #8: log traceback server-side; do NOT render it in the response
        app.logger.exception('[admin_cleanup_old_seed] failed')
        import html as _html
        return ('<h2 style="color:#b91c1c">cleanup_old_seed error</h2>'
                f'<p>{_html.escape(type(e).__name__)}: see server logs for details.</p>'
                '<p><a href="/admin">Admin</a></p>'), 500

@app.route('/pricing')
def pricing():
    """Public pricing page (no login required)."""
    plans = []
    for key, label, price, months in PAYPAL_PLANS:
        plans.append({'key': key, 'label': label, 'price': price, 'months': months})
    return render_template('pricing.html', plans=plans)


# ══════════════════════════════════════════════════════
# GROWTH STATS — funnel measurement (2026-09-06)
# ──────────────────────────────────────────────────────
# Why: until now there was no way to answer "how many people signed up,
# how many started a trial, how many actually paid". /admin showed only
# raw user rows. Two consumers:
#   1. /admin/stats  — a page WS can read.
#   2. an hourly "WAYEXAM_STATS {json}" line on stdout, so a Claude session
#      can read the numbers straight from the Railway deploy logs without
#      needing DB credentials or an authenticated HTTP request.
# ══════════════════════════════════════════════════════

def _growth_stats():
    """Funnel counters. Admins are excluded from every user metric."""
    now = datetime.utcnow()

    def since(days):
        return now - timedelta(days=days)

    users = [u for u in User.query.all() if not u.is_admin]

    def born_since(days):
        cutoff = since(days)
        return sum(1 for u in users if u.created_at and u.created_at >= cutoff)

    trial_active = sum(1 for u in users if u.is_trial())
    paid_active = sum(1 for u in users if u.is_paid_premium())
    expired = sum(1 for u in users
                  if u.is_premium and u.validity_end and u.validity_end < now)

    return {
        'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        # acquisition
        'users_total': len(users),
        'users_with_password': sum(1 for u in users if u.password_hash),
        'new_1d': born_since(1),
        'new_7d': born_since(7),
        'new_30d': born_since(30),
        # activation / conversion
        'trial_active': trial_active,
        'paid_active': paid_active,
        'premium_expired': expired,
        # engagement
        'active_7d': sum(1 for u in users if u.last_login and u.last_login >= since(7)),
        'quiz_sessions_7d': QuizSession.query.filter(QuizSession.started_at >= since(7)).count(),
        'quiz_sessions_total': QuizSession.query.count(),
        # lead magnet
        'pdf_sent': sum(1 for u in users if u.free_pdf_sent_at),
        'pdf_downloaded': sum(1 for u in users if u.free_pdf_downloaded_at),
        # catalogue
        'questions': Question.query.count(),
    }


@app.route('/admin/stats')
@admin_required
def admin_stats():
    """Funnel dashboard: signups -> trials -> paying customers."""
    return render_template('admin_stats.html', s=_growth_stats())


def _start_stats_logger(interval_seconds=3600, first_delay=90):
    """Emit one WAYEXAM_STATS line per interval so Railway logs carry the funnel.

    Runs in a daemon thread. Under gunicorn each worker starts one, so the
    line appears once per worker — harmless duplication, the values match.
    """
    import threading
    import time

    def loop():
        time.sleep(first_delay)          # let the DB finish coming up
        while True:
            try:
                with app.app_context():
                    payload = json.dumps(_growth_stats(), ensure_ascii=False)
                    print('WAYEXAM_STATS ' + payload, flush=True)
                    db.session.remove()
            except Exception as exc:
                print('WAYEXAM_STATS_ERROR {}: {}'.format(type(exc).__name__, exc),
                      flush=True)
            time.sleep(interval_seconds)

    threading.Thread(target=loop, daemon=True, name='stats-logger').start()


_start_stats_logger()
