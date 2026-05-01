# Claude 작업 지침 — 사이트  items선·수정 시 반드시 준수

> 이 파day은 **모든 Claude 세션**(Cowork, Claude Code, Claude.ai, 다른 어떤 환경이든)이 이 폴더에서 작업할 때 자동으로 참조해야 하는 영구 지침입니다.
> 작성: 2026-04-27 / 사용자: WS (rladhkdtlr@daum.net)

## 🎯 사용자 합의 사항 (Non-Negotiable)

> **"모든 작업은 로컬에서 먼저 작업하고, 깃허브에 푸쉬하고 배포하는 것"**
> — 이 원칙을 어떤 이유로도 어기지 말 것.

## 🚨 핵심 원칙

**GitHub이 정본(single source of truth), 로컬은 그 사본day 뿐.**

새 세션의 Claude는 작업 Start 전 반드시:
1. 사용자가 어느 사이트에서 작업하는지 OK
2. 해당 사이트 폴더(`*-quiz`  or  `pmp-flask`)로 이동
3. **`git pull origin main`부터 실행**해서 GitHub과 동기화
4. 그 후 로컬에서 수정

## ✅ 표준 작업 순서 (모든 사이트 공통)

```bash
cd <사이트_폴더>           # 예: cd "C:\Users\rladh\Documents\Claude\Projects\공인노무사\cpla-quiz"
git pull origin main      # ① 항상 최신화부터
# (로컬에서 파day 수정)
git status                # ② 변경 OK
git add -A
git commit -m "변경 내용 요약"
git push origin main      # ③ Railway 자동 배포
```

## ⛔ 절대 금지 행위 (사이트 망가뜨림)

| 위험 행위 | 왜 위험한가 |
|---|---|
| already git clone된 폴더에서 `git init` 다시 실행 | history min리, force-push 시 GitHub 코드 Delete됨 |
| `git push --force` / `--force-with-lease` | 다른 commit/자동 빌드 통째로 날림 |
| 새 폴더 만들어서 push | 풀스택 앱이 정적 파day로 덮임 (2026-04-26 사고 사례) |
| 로컬 폴더 Delete 후 재clone | 미커밋 변경 영구 손실 |
| GitHub 웹UI Edit + 동시 로컬 Edit | 충돌 발생, 한쪽이 사라짐 |
| 사용자 동의 없이 `--force` 류 명령 사용 | **명시적 동의 없이는 절대 X** |

## 🚦 헷갈리는 상황별 안전 행동

- **`git push`가 "rejected"로 거부됨** → 누가 GitHub에 먼저 push한 것. `git pull`부터 하고 다시 시도. **--force 쓰지 말 것.**
- **`git status`에 변경사항이 너무 많이 표시** → LF/CRLF 줄 끝 차이 가능. `git diff`로 실제 변경 OK. 가짜라면 `git config core.autocrlf true` 한 번 실행.
- **로컬과 GitHub이 다른 코드처럼 보임** → 멈추고 사용자에게 OK. 강제로 덮어쓰지 말 것.
- **`.git/index.lock` 같은 lock 에러** → `Remove-Item .git/index.lock` 후 재시도.
- **충돌(merge conflict) 발생** → 사용자에게 어느 쪽을 우선할지 묻고 진행.

## 🗂 4 items 사이트 위치 (2026-04-27 기준)

```
C:\Users\rladh\Documents\Claude\Projects\
├── PMP 웹사이트\pmp-flask\           ← prolab-PMP/pmp-quiz (Python Flask)
├── 산업안전지도사\safety-quiz\       ← prolab-PMP/safety-quiz (Node.js Express)
├── 산업보건지도사\health-quiz\       ← prolab-PMP/health-quiz (Node.js Express)
└── 공인노무사\cpla-quiz\             ← prolab-PMP/cpla-quiz (Node.js Express)
```

작업할 폴더는 **항상 위 4 items 중 하나** 안입니다. 그 외 폴더(, 2차, Keyword추출 등)는 원본 자료실로 git과 무관.

## 📚 자세한 정보

- **상세 매뉴얼**: `사이트_운영_매뉴얼.md` (이 폴더에 있음) — 파day 역할, 수정 금지 항목, Railway 설정, 보안 등 전부
- **각 사이트별 CLAUDE.md**: 해당 사이트 폴더 안에 같은 지침 사본 + 사이트별 특이사항

## 🤖 Claude를 위한 행동 규칙

1. **사용자가 "사이트 수정/ items선/배포" 요청 시**: 먼저 위 표준 순서를 따르겠다고 말하고 `git pull`부터 Start.
2. **위험 명령(`--force`, `git init` 재실행 등)을 쓸 day이 생기면**: 사용자에게 명시적으로 이유와 위험을 설명하고 **동의 받은 후에만** 실행.
3. **로컬과 GitHub이 min기되거나 충돌**: 자동으로 결정하지 말고 사용자에게 옵션 제시 후 Select받기.
4. **새로 Start하지 말 것**: already git clone돼 있으면 그 폴더에서 작업. 새 폴더 만들고 거기서 작업하지 말 것.
5. **PowerShell 스크립트로 자동화 시**: 위 모든 규칙을 스크립트 안에도 반영.
