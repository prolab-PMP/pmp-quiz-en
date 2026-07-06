"""PMP Drag & Drop 문제 10개 (매칭 5 + 순서 5) — idempotent seed 모듈.

question_no 91001~91010 (일반 PMP 문제 및 표 문제 90000번대와 충돌 방지 위해 91000번대).

Data model:
- question_type: 'dnd_match' → answer JSON dict, dnd_items(prompt) ↔ dnd_targets(choice)
- question_type: 'dnd_order' → answer JSON list, dnd_items를 정답 순서로

로컬 seed에서 dnd_items/dnd_targets/answer는 파이썬 자료구조로 두고
DB 저장 직전에 json.dumps로 직렬화한다 (관리자 편집 UX·저장 안정성 향상).
"""
import json

DND_QUESTIONS = [
    # ========== 매칭 5문항 ==========
    # 1. Tuckman의 팀 발달 5단계 매칭
    {
        "no": 91001,
        "question_type": "dnd_match",
        "question": "Match each Tuckman team development stage with its typical behavior.",
        "question_kr": "터크만(Tuckman)의 팀 발달 단계와 대표적 행동을 매칭하십시오.",
        "dnd_items": [
            {"id": "1", "label": "Forming"},
            {"id": "2", "label": "Storming"},
            {"id": "3", "label": "Norming"},
            {"id": "4", "label": "Performing"},
            {"id": "5", "label": "Adjourning"},
        ],
        "dnd_targets": [
            {"id": "A", "label": "Members meet, roles are unclear, tone is polite and cautious"},
            {"id": "B", "label": "Members express conflicting opinions and challenge each other"},
            {"id": "C", "label": "Team agrees on ways of working; trust and cohesion grow"},
            {"id": "D", "label": "Team operates at peak efficiency and self-organizes"},
            {"id": "E", "label": "Project ends; team members are released and celebrated"},
        ],
        "dnd_items_kr": [
            {"id": "1", "label": "형성기 (Forming)"},
            {"id": "2", "label": "격동기 (Storming)"},
            {"id": "3", "label": "규범기 (Norming)"},
            {"id": "4", "label": "성취기 (Performing)"},
            {"id": "5", "label": "해체기 (Adjourning)"},
        ],
        "dnd_targets_kr": [
            {"id": "A", "label": "구성원이 처음 만나 역할이 불분명하고 예의 바르며 조심스러움"},
            {"id": "B", "label": "구성원 간 의견 충돌과 도전이 나타남"},
            {"id": "C", "label": "일하는 방식을 합의하고 신뢰·응집력이 형성됨"},
            {"id": "D", "label": "팀이 최고 효율로 자율 운영되는 단계"},
            {"id": "E", "label": "프로젝트 종료 및 팀원 해산·격려 단계"},
        ],
        "answer": {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"},
        "explanation": "Tuckman's classic 5-stage model: Forming → Storming → Norming → Performing → Adjourning.",
        "explanation_kr": "터크만의 고전 5단계 모형: 형성기 → 격동기 → 규범기 → 성취기 → 해체기.",
        "eco2021_domain": "People", "eco2021_task": "Build a team",
        "pmbok7_domain": "Team", "pmbok7_principle": "Team",
        "methodology": "Any",
    },
    # 2. 갈등 해결 5기법 매칭
    {
        "no": 91002,
        "question_type": "dnd_match",
        "question": "Match each conflict resolution technique with its description.",
        "question_kr": "갈등 해결 기법과 설명을 매칭하십시오.",
        "dnd_items": [
            {"id": "1", "label": "Withdraw / Avoid"},
            {"id": "2", "label": "Smooth / Accommodate"},
            {"id": "3", "label": "Compromise / Reconcile"},
            {"id": "4", "label": "Force / Direct"},
            {"id": "5", "label": "Collaborate / Problem-solve"},
        ],
        "dnd_targets": [
            {"id": "A", "label": "Retreat from the disagreement, postpone the issue"},
            {"id": "B", "label": "Emphasize areas of agreement, downplay differences"},
            {"id": "C", "label": "Find a middle ground where both parties give up something"},
            {"id": "D", "label": "Push one viewpoint at the expense of others"},
            {"id": "E", "label": "Openly analyze the issue and seek a win-win outcome"},
        ],
        "dnd_items_kr": [
            {"id": "1", "label": "회피 (Withdraw)"},
            {"id": "2", "label": "수용 (Smooth)"},
            {"id": "3", "label": "타협 (Compromise)"},
            {"id": "4", "label": "강요 (Force)"},
            {"id": "5", "label": "협력 (Collaborate)"},
        ],
        "dnd_targets_kr": [
            {"id": "A", "label": "논의에서 물러나며 이슈를 뒤로 미룸"},
            {"id": "B", "label": "합의점을 강조하고 차이는 축소함"},
            {"id": "C", "label": "양쪽이 조금씩 양보하여 중간점을 찾음"},
            {"id": "D", "label": "한쪽 관점을 관철시키기 위해 밀어붙임"},
            {"id": "E", "label": "이슈를 개방적으로 분석해 win-win 해결책을 도출"},
        ],
        "answer": {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"},
        "explanation": "PMBOK's five conflict-resolution techniques: Withdraw, Smooth, Compromise, Force, Collaborate. Collaborate is preferred; Force is the strongest short-term but damages relationships.",
        "explanation_kr": "PMBOK의 5가지 갈등 해결 기법: 회피·수용·타협·강요·협력. 협력이 가장 권장되며, 강요는 단기 효과가 크지만 관계를 손상시킴.",
        "eco2021_domain": "People", "eco2021_task": "Manage conflict",
        "pmbok7_domain": "Team", "pmbok7_principle": "Team",
        "methodology": "Any",
    },
    # 3. 리스크 대응 전략 매칭 (Negative + Positive 혼합)
    {
        "no": 91003,
        "question_type": "dnd_match",
        "question": "Match each risk response strategy with its description.",
        "question_kr": "리스크 대응 전략과 설명을 매칭하십시오.",
        "dnd_items": [
            {"id": "1", "label": "Avoid (threat)"},
            {"id": "2", "label": "Transfer (threat)"},
            {"id": "3", "label": "Mitigate (threat)"},
            {"id": "4", "label": "Exploit (opportunity)"},
            {"id": "5", "label": "Share (opportunity)"},
        ],
        "dnd_targets": [
            {"id": "A", "label": "Eliminate the threat entirely by removing its cause"},
            {"id": "B", "label": "Shift the impact to a third party (e.g., insurance, subcontract)"},
            {"id": "C", "label": "Reduce the probability or impact to acceptable limits"},
            {"id": "D", "label": "Ensure the opportunity is realized (100% probability)"},
            {"id": "E", "label": "Allocate ownership to a partner best able to capture the opportunity"},
        ],
        "dnd_items_kr": [
            {"id": "1", "label": "회피 (Avoid — 위협)"},
            {"id": "2", "label": "전가 (Transfer — 위협)"},
            {"id": "3", "label": "완화 (Mitigate — 위협)"},
            {"id": "4", "label": "이용 (Exploit — 기회)"},
            {"id": "5", "label": "공유 (Share — 기회)"},
        ],
        "dnd_targets_kr": [
            {"id": "A", "label": "원인 자체를 제거하여 위협을 완전히 없앰"},
            {"id": "B", "label": "영향을 제3자에게 이전 (보험, 하도급 등)"},
            {"id": "C", "label": "발생 확률이나 영향을 수용 가능 수준으로 낮춤"},
            {"id": "D", "label": "기회가 반드시 실현되도록 함 (확률 100%)"},
            {"id": "E", "label": "기회를 가장 잘 활용할 수 있는 파트너에게 소유권을 넘김"},
        ],
        "answer": {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"},
        "explanation": "Threats → Avoid/Transfer/Mitigate/Accept · Opportunities → Exploit/Share/Enhance/Accept · Escalate applies to both.",
        "explanation_kr": "위협 대응: 회피·전가·완화·수용 · 기회 대응: 이용·공유·증대·수용 · 에스컬레이션은 위협·기회 모두에 적용.",
        "eco2021_domain": "Process", "eco2021_task": "Assess and manage risks",
        "pmbok7_domain": "Uncertainty", "pmbok7_principle": "Risk",
        "methodology": "Any",
    },
    # 4. EVM 지표 매칭 (Formula)
    {
        "no": 91004,
        "question_type": "dnd_match",
        "question": "Match each EVM indicator with its formula.",
        "question_kr": "EVM(획득가치관리) 지표와 계산식을 매칭하십시오.",
        "dnd_items": [
            {"id": "1", "label": "CPI — Cost Performance Index"},
            {"id": "2", "label": "SPI — Schedule Performance Index"},
            {"id": "3", "label": "CV — Cost Variance"},
            {"id": "4", "label": "SV — Schedule Variance"},
            {"id": "5", "label": "EAC — Estimate at Completion (typical CPI)"},
        ],
        "dnd_targets": [
            {"id": "A", "label": "EV / AC"},
            {"id": "B", "label": "EV / PV"},
            {"id": "C", "label": "EV − AC"},
            {"id": "D", "label": "EV − PV"},
            {"id": "E", "label": "BAC / CPI"},
        ],
        "dnd_items_kr": [
            {"id": "1", "label": "CPI (비용성과지수)"},
            {"id": "2", "label": "SPI (일정성과지수)"},
            {"id": "3", "label": "CV (비용편차)"},
            {"id": "4", "label": "SV (일정편차)"},
            {"id": "5", "label": "EAC (완료시점 총원가 예측, 전형적 CPI 유지 가정)"},
        ],
        "dnd_targets_kr": [
            {"id": "A", "label": "EV / AC"},
            {"id": "B", "label": "EV / PV"},
            {"id": "C", "label": "EV − AC"},
            {"id": "D", "label": "EV − PV"},
            {"id": "E", "label": "BAC / CPI"},
        ],
        "answer": {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"},
        "explanation": "CPI = EV/AC · SPI = EV/PV · CV = EV−AC · SV = EV−PV · EAC (typical CPI) = BAC/CPI.",
        "explanation_kr": "CPI = EV/AC · SPI = EV/PV · CV = EV−AC · SV = EV−PV · EAC(전형적 CPI 유지) = BAC/CPI.",
        "eco2021_domain": "Process", "eco2021_task": "Manage budget and resources",
        "pmbok7_domain": "Measurement", "pmbok7_principle": "Value",
        "methodology": "Predictive",
    },
    # 5. Agile 방법론과 특징 매칭
    {
        "no": 91005,
        "question_type": "dnd_match",
        "question": "Match each Agile framework with its most distinctive characteristic.",
        "question_kr": "각 애자일 프레임워크와 대표적 특징을 매칭하십시오.",
        "dnd_items": [
            {"id": "1", "label": "Scrum"},
            {"id": "2", "label": "Kanban"},
            {"id": "3", "label": "XP (Extreme Programming)"},
            {"id": "4", "label": "SAFe"},
            {"id": "5", "label": "Lean"},
        ],
        "dnd_targets": [
            {"id": "A", "label": "Fixed-length Sprints (1-4 weeks) with a defined Sprint Goal"},
            {"id": "B", "label": "Continuous flow with WIP limits and a visual board"},
            {"id": "C", "label": "Engineering practices: pair programming, TDD, refactoring"},
            {"id": "D", "label": "Scaled framework using Agile Release Trains (ARTs) and PI Planning"},
            {"id": "E", "label": "Eliminate waste, maximize flow and value delivery"},
        ],
        "dnd_items_kr": [
            {"id": "1", "label": "스크럼 (Scrum)"},
            {"id": "2", "label": "칸반 (Kanban)"},
            {"id": "3", "label": "XP (익스트림 프로그래밍)"},
            {"id": "4", "label": "SAFe"},
            {"id": "5", "label": "린 (Lean)"},
        ],
        "dnd_targets_kr": [
            {"id": "A", "label": "고정 길이 스프린트(1~4주)와 스프린트 목표"},
            {"id": "B", "label": "WIP 제한과 시각적 보드를 이용한 지속적 흐름"},
            {"id": "C", "label": "페어 프로그래밍·TDD·리팩터링 등 엔지니어링 실천"},
            {"id": "D", "label": "ART와 PI Planning을 이용한 대규모 애자일 프레임워크"},
            {"id": "E", "label": "낭비 제거, 흐름 및 가치 전달 극대화"},
        ],
        "answer": {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"},
        "explanation": "Scrum uses Sprints. Kanban uses continuous flow + WIP limits. XP focuses on engineering practices. SAFe scales Agile via ARTs. Lean eliminates waste.",
        "explanation_kr": "스크럼은 스프린트, 칸반은 흐름+WIP, XP는 엔지니어링 실천, SAFe는 ART로 대규모화, Lean은 낭비 제거.",
        "eco2021_domain": "Process", "eco2021_task": "Deliver project value",
        "pmbok7_domain": "Development Approach", "pmbok7_principle": "Adaptability",
        "methodology": "Agile",
    },

    # ========== 순서 5문항 ==========
    # 6. Project Life Cycle 5 단계 순서
    {
        "no": 91006,
        "question_type": "dnd_order",
        "question": "Arrange the five Project Management Process Groups in the correct order.",
        "question_kr": "프로젝트 관리 프로세스 그룹 5단계를 올바른 순서로 정렬하십시오.",
        "dnd_items": [
            {"id": "A", "label": "Executing"},
            {"id": "B", "label": "Initiating"},
            {"id": "C", "label": "Closing"},
            {"id": "D", "label": "Planning"},
            {"id": "E", "label": "Monitoring & Controlling"},
        ],
        "dnd_items_kr": [
            {"id": "A", "label": "실행 (Executing)"},
            {"id": "B", "label": "착수 (Initiating)"},
            {"id": "C", "label": "종료 (Closing)"},
            {"id": "D", "label": "기획 (Planning)"},
            {"id": "E", "label": "감시 및 통제 (Monitoring & Controlling)"},
        ],
        "answer": ["B", "D", "A", "E", "C"],
        "explanation": "The 5 Process Groups sequence: Initiating → Planning → Executing → Monitoring & Controlling → Closing. M&C overlaps with all others but is placed logically between Executing and Closing.",
        "explanation_kr": "5개 프로세스 그룹 순서: 착수 → 기획 → 실행 → 감시 및 통제 → 종료. 감시 및 통제는 다른 모든 그룹과 겹치지만 논리적으로 실행과 종료 사이에 배치.",
        "eco2021_domain": "Process", "eco2021_task": "Manage project changes",
        "pmbok7_domain": "Delivery", "pmbok7_principle": "Change",
        "methodology": "Predictive",
    },
    # 7. Risk Management 프로세스 순서
    {
        "no": 91007,
        "question_type": "dnd_order",
        "question": "Arrange the PMBOK Risk Management processes in the correct order (planning to control).",
        "question_kr": "PMBOK 리스크 관리 프로세스를 기획~통제 순서로 정렬하십시오.",
        "dnd_items": [
            {"id": "A", "label": "Perform Quantitative Risk Analysis"},
            {"id": "B", "label": "Plan Risk Management"},
            {"id": "C", "label": "Identify Risks"},
            {"id": "D", "label": "Plan Risk Responses"},
            {"id": "E", "label": "Perform Qualitative Risk Analysis"},
            {"id": "F", "label": "Implement Risk Responses"},
            {"id": "G", "label": "Monitor Risks"},
        ],
        "dnd_items_kr": [
            {"id": "A", "label": "정량적 리스크 분석 수행"},
            {"id": "B", "label": "리스크 관리 계획 수립"},
            {"id": "C", "label": "리스크 식별"},
            {"id": "D", "label": "리스크 대응 계획 수립"},
            {"id": "E", "label": "정성적 리스크 분석 수행"},
            {"id": "F", "label": "리스크 대응 실행"},
            {"id": "G", "label": "리스크 감시"},
        ],
        "answer": ["B", "C", "E", "A", "D", "F", "G"],
        "explanation": "Plan Risk Management → Identify → Qualitative → Quantitative → Plan Responses → Implement Responses → Monitor Risks.",
        "explanation_kr": "리스크 관리 계획 → 식별 → 정성적 분석 → 정량적 분석 → 대응 계획 → 대응 실행 → 감시.",
        "eco2021_domain": "Process", "eco2021_task": "Assess and manage risks",
        "pmbok7_domain": "Uncertainty", "pmbok7_principle": "Risk",
        "methodology": "Predictive",
    },
    # 8. Change Control 절차 순서
    {
        "no": 91008,
        "question_type": "dnd_order",
        "question": "Arrange the integrated change control steps in the correct order.",
        "question_kr": "통합 변경 통제(Integrated Change Control) 단계를 올바른 순서로 정렬하십시오.",
        "dnd_items": [
            {"id": "A", "label": "Update baselines and communicate the decision"},
            {"id": "B", "label": "Submit a formal Change Request (CR)"},
            {"id": "C", "label": "Assess impact on scope, schedule, cost, risk, quality"},
            {"id": "D", "label": "CCB (Change Control Board) reviews and decides"},
            {"id": "E", "label": "Log CR in the change log"},
            {"id": "F", "label": "Implement the approved change"},
        ],
        "dnd_items_kr": [
            {"id": "A", "label": "기준선 갱신 및 결정 사항 전파"},
            {"id": "B", "label": "공식 변경요청(CR) 제출"},
            {"id": "C", "label": "범위·일정·원가·리스크·품질 영향 분석"},
            {"id": "D", "label": "변경통제위원회(CCB) 검토 및 결정"},
            {"id": "E", "label": "변경 대장에 CR 기록"},
            {"id": "F", "label": "승인된 변경 실행"},
        ],
        "answer": ["B", "E", "C", "D", "F", "A"],
        "explanation": "Submit CR → Log → Assess impact → CCB decides → Implement → Update baselines & communicate.",
        "explanation_kr": "CR 제출 → 대장 기록 → 영향 분석 → CCB 결정 → 실행 → 기준선 갱신 및 전파.",
        "eco2021_domain": "Business Environment", "eco2021_task": "Manage project changes",
        "pmbok7_domain": "Delivery", "pmbok7_principle": "Change",
        "methodology": "Predictive",
    },
    # 9. Kotter의 조직 변화 8단계 (compressed to 5 for exam-realistic scope)
    {
        "no": 91009,
        "question_type": "dnd_order",
        "question": "Arrange Kotter's 8 steps for leading organizational change in the correct order.",
        "question_kr": "코터(Kotter)의 조직 변화 리더십 8단계를 올바른 순서로 정렬하십시오.",
        "dnd_items": [
            {"id": "A", "label": "Empower broad-based action"},
            {"id": "B", "label": "Create a sense of urgency"},
            {"id": "C", "label": "Form a powerful guiding coalition"},
            {"id": "D", "label": "Generate short-term wins"},
            {"id": "E", "label": "Develop a vision and strategy"},
            {"id": "F", "label": "Communicate the change vision"},
            {"id": "G", "label": "Consolidate gains and produce more change"},
            {"id": "H", "label": "Anchor new approaches in the culture"},
        ],
        "dnd_items_kr": [
            {"id": "A", "label": "광범위한 실행 권한 부여"},
            {"id": "B", "label": "긴급성(위기감) 조성"},
            {"id": "C", "label": "강력한 변화 주도 연합 구성"},
            {"id": "D", "label": "단기 성공 사례 창출"},
            {"id": "E", "label": "비전과 전략 개발"},
            {"id": "F", "label": "변화 비전 공유(소통)"},
            {"id": "G", "label": "성과 통합 및 추가 변화 창출"},
            {"id": "H", "label": "새 방식을 조직 문화로 정착"},
        ],
        "answer": ["B", "C", "E", "F", "A", "D", "G", "H"],
        "explanation": "Kotter's 8 steps: Urgency → Coalition → Vision → Communicate → Empower → Short-term wins → Consolidate → Anchor.",
        "explanation_kr": "코터 8단계: 긴급성 → 연합 → 비전 → 소통 → 권한 부여 → 단기 성공 → 통합 → 문화 정착.",
        "eco2021_domain": "Business Environment", "eco2021_task": "Manage project changes",
        "pmbok7_domain": "Stakeholders", "pmbok7_principle": "Stewardship",
        "methodology": "Any",
    },
    # 10. Scrum Sprint Events 순서
    {
        "no": 91010,
        "question_type": "dnd_order",
        "question": "Arrange the Scrum events that occur during a single Sprint in the correct order.",
        "question_kr": "하나의 스프린트 안에서 발생하는 스크럼 이벤트를 올바른 순서로 정렬하십시오.",
        "dnd_items": [
            {"id": "A", "label": "Sprint Review"},
            {"id": "B", "label": "Sprint Planning"},
            {"id": "C", "label": "Daily Scrum (repeated during the Sprint)"},
            {"id": "D", "label": "Sprint Retrospective"},
            {"id": "E", "label": "The Sprint itself (development work)"},
        ],
        "dnd_items_kr": [
            {"id": "A", "label": "스프린트 리뷰"},
            {"id": "B", "label": "스프린트 계획"},
            {"id": "C", "label": "일일 스크럼 (스프린트 기간 중 반복)"},
            {"id": "D", "label": "스프린트 회고"},
            {"id": "E", "label": "스프린트 자체 (개발 작업)"},
        ],
        "answer": ["B", "E", "C", "A", "D"],
        "explanation": "Sprint Planning kicks off the Sprint. The Sprint itself contains the development work with Daily Scrums held each day. It ends with Sprint Review (product) then Sprint Retrospective (process).",
        "explanation_kr": "스프린트 계획으로 시작, 스프린트 기간 중 개발 작업과 일일 스크럼이 진행되고, 마지막에 스프린트 리뷰(산출물)와 스프린트 회고(프로세스) 순서로 종료.",
        "eco2021_domain": "Process", "eco2021_task": "Deliver project value",
        "pmbok7_domain": "Development Approach", "pmbok7_principle": "Adaptability",
        "methodology": "Agile",
    },
]


# 저장 시 JSON으로 직렬화되는 필드
DND_JSON_FIELDS = {'dnd_items', 'dnd_targets', 'dnd_items_kr', 'dnd_targets_kr', 'answer'}

# Question 모델에 허용된 필드 화이트리스트
ALLOWED_FIELDS = {
    'no', 'question_type',
    'question', 'opt_a', 'opt_b', 'opt_c', 'opt_d', 'opt_e', 'answer', 'explanation',
    'question_kr', 'opt_a_kr', 'opt_b_kr', 'opt_c_kr', 'opt_d_kr', 'opt_e_kr', 'explanation_kr',
    'dnd_items', 'dnd_targets', 'dnd_items_kr', 'dnd_targets_kr',
    'eco2021_domain', 'eco2021_task',
    'pmbok7_domain', 'pmbok7_principle',
    'methodology', 'methodology_detail',
    'eco2026_domain', 'eco2026_task',
    'pmbok8_domain', 'pmbok8_focus_area', 'pmbok8_principle', 'pmbok8_process', 'pmbok8_new_topics',
}


def seed_dnd_questions(db, Question):
    """Insert D&D questions if not exists. Idempotent.

    파이썬 dict/list 형태로 정의된 dnd_items/dnd_targets/answer 를 DB 저장 직전에
    JSON 문자열로 직렬화한다. 기존 저장된 문항은 skip.
    """
    inserted = 0
    for q in DND_QUESTIONS:
        if Question.query.filter_by(no=q['no']).first():
            continue
        kwargs = {}
        for k, v in q.items():
            if k not in ALLOWED_FIELDS:
                continue
            if k in DND_JSON_FIELDS and not isinstance(v, str):
                kwargs[k] = json.dumps(v, ensure_ascii=False)
            else:
                kwargs[k] = v
        db.session.add(Question(**kwargs))
        inserted += 1
    if inserted:
        db.session.commit()
        print(f'[INIT] D&D 문제 {inserted}개 시드 완료 (no 91001-{91000+len(DND_QUESTIONS)})')
    return inserted
