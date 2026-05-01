"""Load PMP questions from Excel file into database"""
import sys
import os
from openpyxl import load_workbook
from app import app
from models import db, Question

# Column mapping from Excel to model fields
COLUMN_MAP = {
    'No': 'no',
    'Question. 번역, 코드,Web으로 만들기': 'question',
    'A': 'opt_a',
    'B': 'opt_b',
    'C': 'opt_c',
    'D': 'opt_d',
    'E': 'opt_e',
    'Explanation(Changed)': 'explanation',
    '2021 ECO Domain': 'eco2021_domain',
    '2021 ECO Task': 'eco2021_task',
    'PMBOK7 Performance Domain': 'pmbok7_domain',
    'PMBOK7 Principle': 'pmbok7_principle',
    'Methodology': 'methodology',
    'Methodology detail': 'methodology_detail',
    '2026 ECO Domain': 'eco2026_domain',
    '2026 ECO Task': 'eco2026_task',
    'PMBOK8 Performance Domain': 'pmbok8_domain',
    'PMBOK8 Focus Area': 'pmbok8_focus_area',
    'PMBOK8 Principle': 'pmbok8_principle',
    'PMBOK8 Process': 'pmbok8_process',
    'PMBOK8 New Topics': 'pmbok8_new_topics',
    'Question_KR': 'question_kr',
    'A_KR': 'opt_a_kr',
    'B_KR': 'opt_b_kr',
    'C_KR': 'opt_c_kr',
    'D_KR': 'opt_d_kr',
    'E_KR': 'opt_e_kr',
    'Explanation_KR': 'explanation_kr',
}

def load_questions(filepath):
    """Load questions from Excel file"""
    print(f"Loading questions from: {filepath}")
    wb = load_workbook(filepath, read_only=True, data_only=True)
    ws = wb['PMP_All_Data']

    # Get header row
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]

    # Find Answer column (first one at index 7)
    answer_col_idx = 7  # First "Answer" column

    # Build column index map
    col_indices = {}
    for excel_col, model_field in COLUMN_MAP.items():
        if excel_col in headers:
            col_indices[model_field] = headers.index(excel_col)

    loaded = 0
    skipped = 0

    with app.app_context():
        for row in ws.iter_rows(min_row=2):
            values = [cell.value for cell in row]

            # Get question number
            no_val = values[col_indices.get('no', 0)]
            if not no_val:
                skipped += 1
                continue

            # Get answer from first Answer column
            answer_val = values[answer_col_idx]
            if not answer_val:
                skipped += 1
                continue

            # Build question data
            q_data = {}
            for model_field, col_idx in col_indices.items():
                val = values[col_idx]
                if val is not None:
                    q_data[model_field] = str(val).strip() if isinstance(val, str) else val

            q_data['no'] = int(no_val)
            q_data['answer'] = str(answer_val).strip()

            # Check if question exists
            existing = Question.query.filter_by(no=q_data['no']).first()
            if existing:
                for key, val in q_data.items():
                    setattr(existing, key, val)
            else:
                q = Question(**q_data)
                db.session.add(q)

            loaded += 1
            if loaded % 100 == 0:
                print(f"  Loaded {loaded} questions...")
                db.session.commit()

        db.session.commit()

    wb.close()
    print(f"Done! Loaded: {loaded}, Skipped: {skipped}")
    return loaded

if __name__ == '__main__':
    filepath = sys.argv[1] if len(sys.argv) > 1 else 'data/PMP_Raw.xlsx'
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)
    load_questions(filepath)
