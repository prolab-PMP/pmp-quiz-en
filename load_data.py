"""Load PMP questions from Excel into SQLite database.
Usage: python load_data.py [excel_path]
"""
import os, sys, sqlite3
import pandas as pd

EXCEL_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'PMP_Raw.xlsx')
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'data', 'pmp_quiz.db'))

# Excel column name -> DB column name mapping
COLUMN_MAP = {
    'No':                        'no',
    'Question. 번역, 코드,Web으로 만들기': 'question',
    'A':                         'opt_a',
    'B':                         'opt_b',
    'C':                         'opt_c',
    'D':                         'opt_d',
    'E':                         'opt_e',
    'Answer':                    'answer',
    'Explanation(Changed)':      'explanation',
    '2021 ECO Domain':           'domain',
    '2021 ECO Task':             'eco_task',
    'PMBOK7 Performance Domain': 'pmbok7_domain',
    'PMBOK7 Principle':          'pmbok7_principle',
    'Methodology':               'methodology',
    'Methodology detail':        'methodology_detail',
    '2026 ECO Domain':           'eco_domain_2026',
    '2026 ECO Task':             'eco_task_2026',
    'PMBOK8 Performance Domain': 'pmbok8_domain',
    'PMBOK8 Focus Area':         'pmbok8_focus_area',
    'PMBOK8 Principle':          'pmbok8_principle',
    'PMBOK8 Process':            'pmbok8_process',
    'PMBOK8 New Topics':         'pmbok8_new_topics',
}

DB_COLS = list(COLUMN_MAP.values())

INSERT_SQL = f"""INSERT OR REPLACE INTO questions
    ({', '.join(DB_COLS)})
    VALUES ({', '.join(['?'] * len(DB_COLS))})"""

def load():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    sys.path.insert(0, os.path.dirname(__file__))
    from app import init_db
    init_db()

    df = pd.read_excel(EXCEL_PATH, sheet_name='PMP_All_Data', engine='openpyxl')
    db = sqlite3.connect(DB_PATH)
    db.execute('DELETE FROM questions')

    loaded = skipped = 0
    for _, row in df.iterrows():
        no_val = row.get('No')
        ans_val = row.get('Answer')
        if pd.isna(no_val) or pd.isna(ans_val):
            skipped += 1
            continue
        vals = []
        for excel_col, db_col in COLUMN_MAP.items():
            v = row.get(excel_col)
            if excel_col == 'No':
                try:
                    vals.append(int(v))
                except Exception:
                    skipped += 1
                    break
            elif pd.isna(v) if not isinstance(v, str) else (v.strip() == ''):
                vals.append(None)
            else:
                vals.append(str(v).strip())
        else:
            db.execute(INSERT_SQL, vals)
            loaded += 1

    db.commit()
    db.close()
    print(f"Loaded: {loaded} questions, Skipped: {skipped}")

if __name__ == '__main__':
    load()
