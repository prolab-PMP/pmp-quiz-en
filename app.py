import os, sqlite3, json, random, hashlib, secrets, time
from datetime import datetime, date
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, g)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'data', 'pmp_quiz.db'))
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin@pmpquiz.com')

# ── Payment placeholder (replace with your Gumroad or Payhip link) ──
PURCHASE_URL = os.environ.get('PURCHASE_URL', 'https://YOUR_GUMROAD_OR_PAYHIP_LINK_HERE')

# ──────────────────────────── DB helpers ────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        referrer TEXT DEFAULT NULL,
        is_admin INTEGER DEFAULT 0,
        plan TEXT DEFAULT 'free',
        plan_expires_at TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS questions (
        no INTEGER PRIMARY KEY,
        question TEXT NOT NULL,
        opt_a TEXT, opt_b TEXT, opt_c TEXT, opt_d TEXT, opt_e TEXT,
        answer TEXT NOT NULL,
        explanation TEXT,
        -- Classification fields
        domain TEXT, eco_task TEXT,
        pmbok7_domain TEXT, pmbok7_principle TEXT,
        methodology TEXT, methodology_detail TEXT,
        eco_domain_2026 TEXT, eco_task_2026 TEXT,
        pmbok8_domain TEXT, pmbok8_focus_area TEXT,
        pmbok8_principle TEXT, pmbok8_process TEXT, pmbok8_new_topics TEXT,
        -- Legacy (compatibility)
        knowledge_area TEXT, question_type TEXT, key_concepts TEXT
    );
    CREATE TABLE IF NOT EXISTS quiz_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mode TEXT NOT NULL,
        question_count INTEGER,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        score INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS quiz_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        question_no INTEGER NOT NULL,
        user_answer TEXT,
        correct_answer TEXT NOT NULL,
        is_correct INTEGER NOT NULL DEFAULT 0,
        answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES quiz_sessions(id),
        FOREIGN KEY (question_no) REFERENCES questions(no)
    );
    CREATE TABLE IF NOT EXISTS wrong_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question_no INTEGER NOT NULL,
        wrong_count INTEGER DEFAULT 1,
        last_wrong_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved INTEGER DEFAULT 0,
        resolved_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (question_no) REFERENCES questions(no),
        UNIQUE(user_id, question_no)
    );
    CREATE TABLE IF NOT EXISTS bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question_no INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, question_no),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (question_no) REFERENCES questions(no)
    );
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question_no INTEGER NOT NULL,
        reason TEXT NOT NULL,
        detail TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (question_no) REFERENCES questions(no)
    );
    CREATE INDEX IF NOT EXISTS idx_quiz_answers_session ON quiz_answers(session_id);
    CREATE INDEX IF NOT EXISTS idx_quiz_sessions_user ON quiz_sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_wrong_answers_user ON wrong_answers(user_id, resolved);
    CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id);
    CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
    """)
    db.commit()
    # DB migration - users table
    for col, definition in [
        ('referrer',        'TEXT DEFAULT NULL'),
        ('is_admin',        'INTEGER DEFAULT 0'),
        ('plan',            "TEXT DEFAULT 'free'"),
        ('plan_expires_at', 'TIMESTAMP DEFAULT NULL'),
    ]:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            db.commit()
        except Exception:
            pass
    # DB migration - questions table (new columns)
    new_q_cols = [
        ('eco_task',          'TEXT'), ('pmbok7_domain',    'TEXT'),
        ('pmbok7_principle',  'TEXT'), ('methodology_detail','TEXT'),
        ('eco_domain_2026',   'TEXT'), ('eco_task_2026',    'TEXT'),
        ('pmbok8_domain',     'TEXT'), ('pmbok8_focus_area','TEXT'),
        ('pmbok8_principle',  'TEXT'), ('pmbok8_process',   'TEXT'),
        ('pmbok8_new_topics', 'TEXT'),
    ]
    for col, definition in new_q_cols:
        try:
            db.execute(f"ALTER TABLE questions ADD COLUMN {col} {definition}")
            db.commit()
        except Exception:
            pass
    db.close()

# ──────────────────────────── Auth helpers ────────────────────────────
def hash_password(password, salt=None):
    if not salt:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return h.hex(), salt

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash('Admin access required.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def is_plan_valid(user):
    if user['plan'] == 'free':
        return False
    if user['plan_expires_at'] is None:
        return True
    try:
        exp = datetime.fromisoformat(str(user['plan_expires_at']))
        return exp > datetime.now()
    except Exception:
        return False

# ──────────────────────────── Context processor ────────────────────────────
@app.context_processor
def inject_purchase_url():
    return dict(PURCHASE_URL=PURCHASE_URL)

# ──────────────────────────── Auth routes ────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    referrer_error = None
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        referrer = request.form.get('referrer', '').strip().lower() or None

        if len(username) < 4 or '@' not in username:
            flash('Please enter a valid email address.', 'error')
            return render_template('register.html', referrer_error=referrer_error)
        if len(password) < 4:
            flash('Password must be at least 4 characters.', 'error')
            return render_template('register.html', referrer_error=referrer_error)

        db = get_db()
        if referrer:
            ref_user = db.execute("SELECT id FROM users WHERE username=?", (referrer,)).fetchone()
            if not ref_user:
                referrer_error = 'Referrer ID does not exist.'
                return render_template('register.html', referrer_error=referrer_error)

        existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            flash('This email is already registered.', 'error')
            return render_template('register.html', referrer_error=referrer_error)

        pw_hash, salt = hash_password(password)
        is_admin = 1 if username == ADMIN_USERNAME.lower() else 0
        db.execute(
            "INSERT INTO users (username, password_hash, salt, referrer, is_admin) VALUES (?,?,?,?,?)",
            (username, pw_hash, salt, referrer, is_admin))
        db.commit()
        flash('Registration complete! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', referrer_error=referrer_error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user:
            pw_hash, _ = hash_password(password, user['salt'])
            if pw_hash == user['password_hash']:
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['is_admin'] = bool(user['is_admin'])
                session['plan'] = user['plan'] if is_plan_valid(user) else 'free'
                return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ──────────────────────────── Dashboard ────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    uid = session['user_id']
    total_q = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    sessions_done = db.execute("SELECT COUNT(*) FROM quiz_sessions WHERE user_id=? AND completed_at IS NOT NULL", (uid,)).fetchone()[0]
    total_answered = db.execute("""SELECT COUNT(*) FROM quiz_answers qa
        JOIN quiz_sessions qs ON qa.session_id=qs.id WHERE qs.user_id=?""", (uid,)).fetchone()[0]
    total_correct = db.execute("""SELECT COALESCE(SUM(qa.is_correct),0) FROM quiz_answers qa
        JOIN quiz_sessions qs ON qa.session_id=qs.id WHERE qs.user_id=?""", (uid,)).fetchone()[0]
    wrong_count = db.execute("SELECT COUNT(*) FROM wrong_answers WHERE user_id=? AND resolved=0", (uid,)).fetchone()[0]
    bookmark_count = db.execute("SELECT COUNT(*) FROM bookmarks WHERE user_id=?", (uid,)).fetchone()[0]
    accuracy = round(total_correct / total_answered * 100, 1) if total_answered > 0 else 0

    user = db.execute("SELECT plan, plan_expires_at FROM users WHERE id=?", (uid,)).fetchone()
    plan_expires = user['plan_expires_at'] if user else None

    # Weak area analysis (after 20+ questions answered)
    weak_alert = None
    if total_answered >= 20:
        domain_stats = db.execute("""SELECT q.domain,
            COUNT(*) as total, ROUND(SUM(qa.is_correct)*100.0/COUNT(*),1) as accuracy
            FROM quiz_answers qa
            JOIN quiz_sessions qs ON qa.session_id=qs.id
            JOIN questions q ON qa.question_no=q.no
            WHERE qs.user_id=? AND q.domain IS NOT NULL GROUP BY q.domain HAVING total >= 5""", (uid,)).fetchall()
        if domain_stats:
            weakest = min(domain_stats, key=lambda x: x['accuracy'])
            if weakest['accuracy'] < 65:
                weak_alert = {'domain': weakest['domain'], 'accuracy': weakest['accuracy']}

    return render_template('dashboard.html',
        total_q=total_q, sessions_done=sessions_done,
        total_answered=total_answered, total_correct=total_correct,
        wrong_count=wrong_count, accuracy=accuracy,
        plan_expires=plan_expires, bookmark_count=bookmark_count,
        weak_alert=weak_alert)

# ──────────────────────────── Bookmark ────────────────────────────
@app.route('/bookmarks')
@login_required
def bookmark_list():
    db = get_db()
    uid = session['user_id']
    rows = db.execute("""SELECT b.question_no, b.created_at,
        q.question, q.answer, q.domain, q.knowledge_area, q.methodology,
        q.opt_a, q.opt_b, q.opt_c, q.opt_d, q.opt_e, q.explanation
        FROM bookmarks b JOIN questions q ON b.question_no=q.no
        WHERE b.user_id=? ORDER BY b.created_at DESC""", (uid,)).fetchall()
    return render_template('bookmarks.html', bookmarks=rows)

@app.route('/api/bookmark/toggle', methods=['POST'])
@login_required
def api_bookmark_toggle():
    q_no = request.json.get('question_no')
    uid = session['user_id']
    db = get_db()
    existing = db.execute("SELECT id FROM bookmarks WHERE user_id=? AND question_no=?", (uid, q_no)).fetchone()
    if existing:
        db.execute("DELETE FROM bookmarks WHERE user_id=? AND question_no=?", (uid, q_no))
        db.commit()
        return jsonify({'bookmarked': False})
    else:
        db.execute("INSERT INTO bookmarks (user_id, question_no) VALUES (?,?)", (uid, q_no))
        db.commit()
        return jsonify({'bookmarked': True})

# ──────────────────────────── Report ────────────────────────────
@app.route('/api/report', methods=['POST'])
@login_required
def api_report():
    data = request.json
    q_no = data.get('question_no')
    reason = data.get('reason', '')
    detail = data.get('detail', '')
    uid = session['user_id']
    if not q_no or not reason:
        return jsonify({'ok': False, 'msg': 'Please fill in all required fields.'})
    db = get_db()
    dup = db.execute("SELECT id FROM reports WHERE user_id=? AND question_no=? AND status='pending'", (uid, q_no)).fetchone()
    if dup:
        return jsonify({'ok': False, 'msg': 'You have already reported this question. Under review.'})
    db.execute("INSERT INTO reports (user_id, question_no, reason, detail) VALUES (?,?,?,?)",
               (uid, q_no, reason, detail))
    db.commit()
    return jsonify({'ok': True, 'msg': 'Report submitted. Thank you!'})

# ──────────────────────────── Admin ────────────────────────────
@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    users = db.execute("""
        SELECT u.id, u.username, u.referrer, u.plan, u.plan_expires_at,
               u.is_admin, u.created_at,
               COUNT(DISTINCT qs.id) as session_count,
               COUNT(qa.id) as answered_count,
               ROUND(COALESCE(SUM(qa.is_correct),0)*100.0/NULLIF(COUNT(qa.id),0),1) as accuracy
        FROM users u
        LEFT JOIN quiz_sessions qs ON u.id=qs.user_id AND qs.completed_at IS NOT NULL
        LEFT JOIN quiz_answers qa ON qs.id=qa.session_id
        GROUP BY u.id ORDER BY u.created_at DESC
    """).fetchall()

    total_users = len(users)
    paid_users  = sum(1 for u in users if u['plan'] != 'free')
    free_users  = total_users - paid_users

    referral_counts = db.execute("""
        SELECT referrer, COUNT(*) as cnt
        FROM users WHERE referrer IS NOT NULL AND referrer != ''
        GROUP BY referrer ORDER BY cnt DESC
    """).fetchall()

    reports = db.execute("""
        SELECT r.id, r.question_no, r.reason, r.detail, r.status, r.created_at,
               u.username, q.question
        FROM reports r
        JOIN users u ON r.user_id=u.id
        JOIN questions q ON r.question_no=q.no
        ORDER BY r.status ASC, r.created_at DESC
    """).fetchall()
    pending_reports = sum(1 for r in reports if r['status'] == 'pending')

    today = date.today().isoformat()
    return render_template('admin.html',
        users=users, total_users=total_users,
        paid_users=paid_users, free_users=free_users,
        referral_counts=referral_counts,
        reports=reports, pending_reports=pending_reports,
        today=today)

@app.route('/admin/update-plan', methods=['POST'])
@admin_required
def admin_update_plan():
    user_id = request.form.get('user_id')
    plan    = request.form.get('plan', 'free')
    expires = request.form.get('plan_expires_at', '').strip() or None
    db = get_db()
    db.execute("UPDATE users SET plan=?, plan_expires_at=? WHERE id=?", (plan, expires, user_id))
    db.commit()
    flash('Plan updated successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete-user', methods=['POST'])
@admin_required
def admin_delete_user():
    user_id = request.form.get('user_id')
    db = get_db()
    db.execute("DELETE FROM bookmarks WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM reports WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM wrong_answers WHERE user_id=?", (user_id,))
    db.execute("""DELETE FROM quiz_answers WHERE session_id IN
                  (SELECT id FROM quiz_sessions WHERE user_id=?)""", (user_id,))
    db.execute("DELETE FROM quiz_sessions WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    flash('User has been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/report/resolve', methods=['POST'])
@admin_required
def admin_report_resolve():
    report_id = request.form.get('report_id')
    db = get_db()
    db.execute("UPDATE reports SET status='resolved', resolved_at=CURRENT_TIMESTAMP WHERE id=?", (report_id,))
    db.commit()
    flash('Report resolved.', 'success')
    return redirect(url_for('admin_dashboard') + '#reports')

@app.route('/admin/report/dismiss', methods=['POST'])
@admin_required
def admin_report_dismiss():
    report_id = request.form.get('report_id')
    db = get_db()
    db.execute("UPDATE reports SET status='dismissed', resolved_at=CURRENT_TIMESTAMP WHERE id=?", (report_id,))
    db.commit()
    flash('Report dismissed.', 'success')
    return redirect(url_for('admin_dashboard') + '#reports')

# ──────────────────────────── Quiz Start ────────────────────────────
@app.route('/quiz/start', methods=['GET', 'POST'])
@login_required
def quiz_start():
    db = get_db()
    FREE_LIMIT = 50

    if request.method == 'POST':
        mode = request.form['mode']
        count = int(request.form.get('count', 10))
        domain_filter = request.form.get('domain', '')
        method_filter = request.form.get('methodology', '')
        area_filter = request.form.get('knowledge_area', '')

        if session.get('plan', 'free') == 'free':
            count = min(count, FREE_LIMIT)

        pmbok_edition = request.form.get('pmbok_edition', '')

        query = "SELECT no FROM questions WHERE 1=1"
        params = []
        if domain_filter:
            query += " AND domain=?"; params.append(domain_filter)
        if method_filter:
            query += " AND methodology=?"; params.append(method_filter)
        if area_filter:
            query += " AND knowledge_area=?"; params.append(area_filter)
        if pmbok_edition == '7':
            query += " AND pmbok7_domain IS NOT NULL AND pmbok7_domain != ''"
        elif pmbok_edition == '8':
            query += " AND pmbok8_domain IS NOT NULL AND pmbok8_domain != ''"

        rows = db.execute(query, params).fetchall()
        q_nos = [r['no'] for r in rows]

        if session.get('plan', 'free') == 'free':
            q_nos = sorted(q_nos)[:FREE_LIMIT]

        is_exam_mode = (mode == 'exam')
        if is_exam_mode:
            random.shuffle(q_nos)
            q_nos = q_nos[:180]
        elif mode == 'wrong':
            wrong_rows = db.execute(
                "SELECT question_no FROM wrong_answers WHERE user_id=? AND resolved=0",
                (session['user_id'],)).fetchall()
            wrong_set = {r['question_no'] for r in wrong_rows}
            q_nos = [n for n in q_nos if n in wrong_set] if (domain_filter or method_filter or area_filter) else list(wrong_set)
            if session.get('plan', 'free') == 'free':
                q_nos = [n for n in q_nos if n <= FREE_LIMIT]
            if not q_nos:
                flash('No wrong answers found!', 'info')
                return redirect(url_for('dashboard'))
            random.shuffle(q_nos)
            q_nos = q_nos[:count]
        elif mode == 'random':
            random.shuffle(q_nos)
            q_nos = q_nos[:count]
        elif mode == 'sequential':
            q_nos = sorted(q_nos)[:count]

        cur = db.execute(
            "INSERT INTO quiz_sessions (user_id, mode, question_count) VALUES (?,?,?)",
            (session['user_id'], mode, len(q_nos)))
        db.commit()
        sid = cur.lastrowid

        quiz_data = {
            'session_id': sid,
            'questions': q_nos,
            'current': 0,
            'answers': {}
        }
        if is_exam_mode:
            quiz_data['exam_end'] = int(time.time()) + 4 * 3600  # 4 hours

        session['quiz'] = quiz_data
        return redirect(url_for('quiz_question'))

    domains = [r[0] for r in db.execute("SELECT DISTINCT domain FROM questions WHERE domain IS NOT NULL ORDER BY domain").fetchall()]
    methods = [r[0] for r in db.execute("SELECT DISTINCT methodology FROM questions WHERE methodology IS NOT NULL ORDER BY methodology").fetchall()]
    areas = [r[0] for r in db.execute("SELECT DISTINCT knowledge_area FROM questions WHERE knowledge_area IS NOT NULL ORDER BY knowledge_area").fetchall()]
    wrong_count = db.execute("SELECT COUNT(*) FROM wrong_answers WHERE user_id=? AND resolved=0", (session['user_id'],)).fetchone()[0]

    return render_template('quiz_start.html',
        domains=domains, methods=methods, areas=areas, wrong_count=wrong_count,
        is_free=(session.get('plan', 'free') == 'free'),
        free_limit=FREE_LIMIT,
        pmbok7_count=db.execute("SELECT COUNT(*) FROM questions WHERE pmbok7_domain IS NOT NULL AND pmbok7_domain != ''").fetchone()[0],
        pmbok8_count=db.execute("SELECT COUNT(*) FROM questions WHERE pmbok8_domain IS NOT NULL AND pmbok8_domain != ''").fetchone()[0])

# ──────────────────────────── Quiz Question ────────────────────────────
@app.route('/quiz/question')
@login_required
def quiz_question():
    quiz = session.get('quiz')
    if not quiz:
        return redirect(url_for('quiz_start'))
    idx = quiz['current']
    if idx >= len(quiz['questions']):
        return redirect(url_for('quiz_result'))
    q_no = quiz['questions'][idx]
    db = get_db()
    q = db.execute("SELECT * FROM questions WHERE no=?", (q_no,)).fetchone()
    options = []
    for key in ['opt_a', 'opt_b', 'opt_c', 'opt_d', 'opt_e']:
        if q[key]:
            options.append((key[-1].upper(), q[key]))

    uid = session['user_id']
    is_bookmarked = bool(db.execute("SELECT id FROM bookmarks WHERE user_id=? AND question_no=?", (uid, q_no)).fetchone())

    # Exam mode remaining time
    exam_end = quiz.get('exam_end')
    remaining_sec = max(0, exam_end - int(time.time())) if exam_end else None

    return render_template('quiz_question.html',
        question=q, options=options,
        current=idx+1, total=len(quiz['questions']),
        progress=round((idx) / len(quiz['questions']) * 100),
        is_bookmarked=is_bookmarked,
        remaining_sec=remaining_sec)

@app.route('/quiz/answer', methods=['POST'])
@login_required
def quiz_answer():
    quiz = session.get('quiz')
    if not quiz:
        return redirect(url_for('quiz_start'))

    answer = request.form.get('answer', '')
    idx = quiz['current']
    q_no = quiz['questions'][idx]
    db = get_db()
    q = db.execute("SELECT * FROM questions WHERE no=?", (q_no,)).fetchone()
    is_correct = 1 if answer.upper() == q['answer'].upper() else 0

    db.execute("""INSERT INTO quiz_answers (session_id, question_no, user_answer, correct_answer, is_correct)
        VALUES (?,?,?,?,?)""", (quiz['session_id'], q_no, answer.upper() or '', q['answer'].upper(), is_correct))
    db.commit()

    quiz['answers'][str(q_no)] = {'user': answer.upper(), 'correct': q['answer'].upper(), 'is_correct': is_correct}

    uid = session['user_id']
    if is_correct:
        db.execute("UPDATE wrong_answers SET resolved=1, resolved_at=CURRENT_TIMESTAMP WHERE user_id=? AND question_no=?",
                   (uid, q_no))
    else:
        existing = db.execute("SELECT id FROM wrong_answers WHERE user_id=? AND question_no=?", (uid, q_no)).fetchone()
        if existing:
            db.execute("UPDATE wrong_answers SET wrong_count=wrong_count+1, last_wrong_at=CURRENT_TIMESTAMP, resolved=0, resolved_at=NULL WHERE user_id=? AND question_no=?",
                       (uid, q_no))
        else:
            db.execute("INSERT INTO wrong_answers (user_id, question_no) VALUES (?,?)", (uid, q_no))
    db.commit()

    quiz['current'] = idx + 1
    session['quiz'] = quiz

    # Exam mode timeout handling
    exam_end = quiz.get('exam_end')
    is_timeout = request.form.get('timeout') == '1'
    if is_timeout and quiz['current'] < len(quiz['questions']):
        remaining_nos = quiz['questions'][quiz['current']:]
        for rno in remaining_nos:
            rq = db.execute("SELECT answer FROM questions WHERE no=?", (rno,)).fetchone()
            if rq:
                db.execute("""INSERT OR IGNORE INTO quiz_answers (session_id, question_no, user_answer, correct_answer, is_correct)
                    VALUES (?,?,?,?,0)""", (quiz['session_id'], rno, '', rq['answer'].upper()))
        db.commit()
        quiz['current'] = len(quiz['questions'])
        session['quiz'] = quiz
        return redirect(url_for('quiz_result'))

    show_result = request.form.get('show_result', '0')
    if show_result == '1':
        uid = session['user_id']
        is_bookmarked = bool(db.execute("SELECT id FROM bookmarks WHERE user_id=? AND question_no=?", (uid, q_no)).fetchone())
        explanation = q['explanation'] or ''
        options = []
        for key in ['opt_a', 'opt_b', 'opt_c', 'opt_d', 'opt_e']:
            if q[key]:
                options.append((key[-1].upper(), q[key]))
        remaining_sec = max(0, exam_end - int(time.time())) if exam_end else None
        return render_template('quiz_answer_review.html',
            question=q, options=options, user_answer=answer.upper(),
            is_correct=is_correct, explanation=explanation,
            current=idx+1, total=len(quiz['questions']),
            is_bookmarked=is_bookmarked, remaining_sec=remaining_sec)

    return redirect(url_for('quiz_question'))

# ──────────────────────────── Quiz Result ────────────────────────────
@app.route('/quiz/result')
@login_required
def quiz_result():
    quiz = session.get('quiz')
    if not quiz:
        return redirect(url_for('quiz_start'))
    db = get_db()
    sid = quiz['session_id']
    answers = db.execute("""SELECT qa.*, q.question, q.domain, q.knowledge_area, q.explanation,
        q.opt_a, q.opt_b, q.opt_c, q.opt_d
        FROM quiz_answers qa JOIN questions q ON qa.question_no=q.no
        WHERE qa.session_id=? ORDER BY qa.id""", (sid,)).fetchall()
    correct = sum(1 for a in answers if a['is_correct'])
    total = len(answers)
    db.execute("UPDATE quiz_sessions SET completed_at=CURRENT_TIMESTAMP, score=?, total=? WHERE id=?",
               (correct, total, sid))
    db.commit()
    session.pop('quiz', None)
    return render_template('quiz_result.html',
        answers=answers, correct=correct, total=total,
        accuracy=round(correct/total*100, 1) if total > 0 else 0,
        session_id=sid)

# ──────────────────────────── Wrong Answers ────────────────────────────
@app.route('/wrong')
@login_required
def wrong_answers():
    db = get_db()
    uid = session['user_id']
    rows = db.execute("""SELECT wa.*, q.question, q.answer, q.domain, q.knowledge_area, q.methodology
        FROM wrong_answers wa JOIN questions q ON wa.question_no=q.no
        WHERE wa.user_id=? AND wa.resolved=0
        ORDER BY wa.last_wrong_at DESC""", (uid,)).fetchall()
    domain_counts = {}
    area_counts = {}
    for r in rows:
        d = r['domain'] or 'Unknown'
        a = r['knowledge_area'] or 'Unknown'
        domain_counts[d] = domain_counts.get(d, 0) + 1
        area_counts[a] = area_counts.get(a, 0) + 1
    return render_template('wrong_answers.html',
        wrongs=rows, domain_counts=domain_counts, area_counts=area_counts)

# ──────────────────────────── Stats ────────────────────────────
@app.route('/stats')
@login_required
def stats():
    db = get_db()
    uid = session['user_id']
    sessions_data = db.execute("""SELECT id, mode, score, total, completed_at,
        ROUND(score*100.0/total,1) as accuracy
        FROM quiz_sessions WHERE user_id=? AND completed_at IS NOT NULL
        ORDER BY completed_at""", (uid,)).fetchall()

    domain_stats = db.execute("""SELECT q.domain,
        COUNT(*) as total, SUM(qa.is_correct) as correct,
        ROUND(SUM(qa.is_correct)*100.0/COUNT(*),1) as accuracy
        FROM quiz_answers qa
        JOIN quiz_sessions qs ON qa.session_id=qs.id
        JOIN questions q ON qa.question_no=q.no
        WHERE qs.user_id=? GROUP BY q.domain""", (uid,)).fetchall()

    area_stats = db.execute("""SELECT q.knowledge_area,
        COUNT(*) as total, SUM(qa.is_correct) as correct,
        ROUND(SUM(qa.is_correct)*100.0/COUNT(*),1) as accuracy
        FROM quiz_answers qa
        JOIN quiz_sessions qs ON qa.session_id=qs.id
        JOIN questions q ON qa.question_no=q.no
        WHERE qs.user_id=? GROUP BY q.knowledge_area ORDER BY accuracy""", (uid,)).fetchall()

    method_stats = db.execute("""SELECT q.methodology,
        COUNT(*) as total, SUM(qa.is_correct) as correct,
        ROUND(SUM(qa.is_correct)*100.0/COUNT(*),1) as accuracy
        FROM quiz_answers qa
        JOIN quiz_sessions qs ON qa.session_id=qs.id
        JOIN questions q ON qa.question_no=q.no
        WHERE qs.user_id=? GROUP BY q.methodology""", (uid,)).fetchall()

    weak_domains = [d for d in domain_stats if d['accuracy'] is not None and d['accuracy'] < 65 and d['total'] >= 5]
    weak_areas   = [a for a in area_stats   if a['accuracy'] is not None and a['accuracy'] < 65 and a['total'] >= 5]

    return render_template('stats.html',
        sessions=sessions_data, domain_stats=domain_stats,
        area_stats=area_stats, method_stats=method_stats,
        weak_domains=weak_domains, weak_areas=weak_areas)

# ──────────────────────────── Global Stats ────────────────────────────
@app.route('/global-stats')
@login_required
def global_stats():
    db = get_db()
    question_stats = db.execute("""SELECT q.no, q.question, q.answer, q.domain, q.knowledge_area,
        COUNT(qa.id) as attempts, SUM(qa.is_correct) as correct,
        ROUND(SUM(qa.is_correct)*100.0/COUNT(qa.id),1) as accuracy
        FROM questions q
        JOIN quiz_answers qa ON q.no=qa.question_no
        GROUP BY q.no HAVING attempts >= 1
        ORDER BY accuracy ASC""").fetchall()

    hardest = list(question_stats[:20])
    easiest = list(question_stats[-20:])[::-1]

    user_rankings = db.execute("""SELECT u.username,
        COUNT(DISTINCT qs.id) as sessions,
        COUNT(qa.id) as total_answered,
        SUM(qa.is_correct) as total_correct,
        ROUND(SUM(qa.is_correct)*100.0/COUNT(qa.id),1) as accuracy
        FROM users u
        JOIN quiz_sessions qs ON u.id=qs.user_id
        JOIN quiz_answers qa ON qs.id=qa.session_id
        GROUP BY u.id ORDER BY accuracy DESC""").fetchall()

    domain_global = db.execute("""SELECT q.domain,
        COUNT(*) as total, SUM(qa.is_correct) as correct,
        ROUND(SUM(qa.is_correct)*100.0/COUNT(*),1) as accuracy
        FROM quiz_answers qa JOIN questions q ON qa.question_no=q.no
        GROUP BY q.domain""").fetchall()

    return render_template('global_stats.html',
        hardest=hardest, easiest=easiest,
        user_rankings=user_rankings, domain_global=domain_global,
        total_questions=len(question_stats))

# ──────────────────────────── API ────────────────────────────
@app.route('/api/trend')
@login_required
def api_trend():
    db = get_db()
    uid = session['user_id']
    data = db.execute("""SELECT completed_at as date,
        ROUND(score*100.0/total,1) as accuracy, score, total
        FROM quiz_sessions WHERE user_id=? AND completed_at IS NOT NULL
        ORDER BY completed_at""", (uid,)).fetchall()
    return jsonify([dict(r) for r in data])

@app.route('/api/question-stats')
@login_required
def api_question_stats():
    db = get_db()
    data = db.execute("""SELECT q.no, q.domain, q.knowledge_area,
        COUNT(qa.id) as attempts,
        ROUND(SUM(qa.is_correct)*100.0/COUNT(qa.id),1) as accuracy
        FROM questions q JOIN quiz_answers qa ON q.no=qa.question_no
        GROUP BY q.no""").fetchall()
    return jsonify([dict(r) for r in data])

# ──────────────────────────── Init ────────────────────────────
with app.app_context():
    init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
