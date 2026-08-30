# RehabPulse — 개인회생 인가 감시기

## 환경
- Windows 11, Python 3.11+
- 가상환경: `.venv` (프로젝트 루트)
- 실행: `python -m rehabpulse sync`

## 작업 순서
PRD(`docs/PRD.md`) §6.3 순서를 따른다:
1. M0 — 조사: 성공/결번 HTML을 `tests/fixtures/`에 저장, `docs/M0_조사메모.md`에 DOM 기록
2. M1 — fetch + excel_store. 시드 6건 엑셀 등록, 재실행 중복 없음
3. M2 — differ + judge. `PLAN_APPROVED`, `DISMISSED`, `CASE_ARCHIVED` 테스트 고정
4. M3 — CLI, 백업, 로그, 이메일, 작업 스케줄러

## 규칙
- 포털 원문 값을 정규화로 잃지 않는다. 판정은 `config/rules.yaml`.
- SMTP 비밀번호를 코드·yaml에 넣지 않는다. 환경변수 `REHABPULSE_SMTP_PASSWORD` (없으면 `AUCTIONPULSE_SMTP_PASSWORD` fallback).
- 캡차 토큰/쿠키를 훔쳐 검색을 우회하지 않는다.
- 파서 변경 시 fixture 테스트가 통과해야 한다.
- 사이트 의존 코드는 `rehabpulse/fetch/` 안에만 둔다.
- 사건목록·열 이름·진행구분·명령 명칭은 포털 화면 표기를 그대로 쓴다.
- 엑셀 잠금 시 임시 파일 저장 후 안내. 저장 전 `backup/` 사본.
- 한 사건의 실패가 다른 사건 조회를 중단시키지 않는다.

## 디렉터리
```
rehabpulse/           # 패키지
  __main__.py         # python -m rehabpulse 진입점
  cli.py              # CLI 명령 (add/remove/list/sync/report)
  models.py           # 데이터클래스
  fetch/              # 브라우저 조회 + 파서 (사이트 의존)
    browser.py        # Playwright 브라우저 관리
    ssgo.py           # ssgo.scourt.go.kr 폼 조작 + 파싱
  store/
    excel_store.py    # openpyxl 업서트
  diff/
    differ.py         # 스냅샷 비교 → ChangeEvent
  judge/
    judge.py          # 인가·종료 판정 (rules.yaml 기반)
  notify/
    mailer.py         # SMTP 이메일
config/
  settings.yaml       # 경로, 이메일, 딜레이 설정
  rules.yaml          # 명령 명칭, 알림 이벤트 매핑
tests/
  fixtures/           # 성공 HTML, 결번 응답, 명령 테이블
scripts/
  register_task.ps1   # Windows 작업 스케줄러 등록
```

<comet-ambient-resume>
<!-- Managed by Comet. Edits inside this block may be replaced by comet init/update. -->
<!-- Contract: comet.resume_probe.v2 -->

## Comet Ambient Resume

In this repository, before starting work that may need code changes or investigation, pass the current user request to the read-only probe when a Comet workflow may already be active: `comet resume-probe . --stdin --json`.

- If the user explicitly invokes any Comet Skill through the host (for example, `@comet`, `/comet`, `@comet-native`, or `/comet-hotfix`), that explicit invocation takes precedence over this resume protocol; do not run the resume probe, and enter the invoked Skill directly.
- Trust only the returned `workflow`, `skill`, and `entrySource`; project configuration or the no-config compatibility fallback alone selects them. Do not scan or switch to the other workflow.
- If the probe returns `auto_resume`, briefly state the selected active change and enter the permanent entry in `nextCommand`. Do not treat a state command as the resume entry or advance it blindly.
- If the probe returns `ask_user`, ask one short question and wait.
- If the current request did not explicitly invoke a Comet Skill and the probe returns `out_of_scope` or `none`, do not enter the Comet workflow.
- If configuration or state is invalid and `nextCommand` is absent, stop and report the reason; do not guess another workflow.
- Never attach unrelated work merely because an active change exists. The Native entry inspects uncommitted work; the probe does not attribute it automatically.
</comet-ambient-resume>
