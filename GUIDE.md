# naver-realestate-bot — 오늘의 브리핑

매일 아침 운세, 날씨, 뉴스, 부동산, 환율, 금·코인, 베스트셀러를 모아 한 페이지로 만드는 자동화 봇.

브리핑 페이지: https://busanfransisco-source.github.io/naver-realestate-bot/briefing.html

## 작동 방식 (2026-07-24 기준)

GitHub Actions(깃허브의 자동 실행 기능)가 매일 스스로 데이터를 수집해 briefing.html을 새로 만든다. 클로드 앱이나 내 컴퓨터가 꺼져 있어도 상관없이 돌아간다.

예약은 이중으로 걸려 있다.

1. **메인(정시 보장): cron-job.org 외부 알람** — 매일 한국시간 아침 6:00에 cron-job.org라는 외부 서비스가 GitHub API를 직접 호출해서(workflow_dispatch) 브리핑을 즉시 새로고침한다. 이 방식은 몇 분 안에 실행되고 시간이 거의 정확하다.
2. **백업: GitHub 자체 예약(schedule)** — .github/workflows/manual-briefing.yml 안에 새벽 4시~7시(한국시간), 20분 간격으로 총 10번의 cron이 걸려 있다. GitHub 자체 예약은 이 계정에서 몇 시간씩 늦게 도는 문제가 있어서(아래 "기록 및 주의사항" 참고) 보조 수단으로만 남겨둔 것.

즉시 새로고침: trigger.txt 파일을 아무렇게나 수정해서 커밋하면 바로 새 브리핑이 만들어진다. 또는 Actions 탭 → Manual Briefing Refresh → Run workflow 버튼.

## 시간 바꾸는 법

- 6시가 아닌 다른 시각에 정시로 받고 싶으면: cron-job.org 로그인 → 해당 job의 Schedule 수정.
- 백업용 GitHub 자체 예약 시각을 바꾸려면: manual-briefing.yml의 cron 목록 숫자를 수정. 순서는 "분 시" 이고 세계표준시(UTC) 기준이므로 한국시간에서 9시간을 빼면 된다.

## 기록 및 주의사항

- 2026-07-17까지는 클로드(Claude) 데스크톱 앱의 예약 작업이 매일 아침 6:30에 trigger.txt를 갱신하는 방식이었다. 앱 재설치로 예약 작업이 사라지는 일이 있어서, 2026-07-18부터 GitHub 자체 예약으로 전환했다.
- 주의: 클로드 앱을 삭제 후 재설치하면 앱에 저장된 채팅과 예약 작업이 지워질 수 있다. 이 봇은 GitHub와 cron-job.org에서 돌아가므로 영향받지 않는다.
- 2026-07-2X 무렵 확인된 사실: 이 계정/저장소에서는 GitHub 자체 예약(schedule)이 보통 3~9시간, 때로는 그 이상 늦게 실행되고 가끔 아예 실행되지 않기도 한다. 여러 번 재시도 cron을 걸어봐도 근본적으로 해결되지 않아서, cron-job.org가 GitHub API(workflow_dispatch)를 직접 호출하는 방식으로 전환해 정시 실행을 확보했다.

## 다른 자동화에도 재사용 가능한 계정·노하우 (2026-07-24 추가)

이번 작업 중 만든 계정과 알아낸 패턴. 실제 비밀번호·토큰 값은 아래에 적지 않는다(안전을 위해 절대 기록하지 않음).

- **cron-job.org 계정**: busanfransisco 이메일로 가입됨. 무료 요금제로 정해진 시각에 원하는 URL을 자동 호출할 수 있다(정시 알람 서비스). 다른 자동화에서도 "매일/매주 정확한 시각에 어떤 API를 호출해야 한다"는 상황이면 재사용 가능.
- **GitHub Fine-grained Personal Access Token 발급 방법**: github.com/settings/tokens?type=beta → Generate new token → Resource owner와 대상 저장소(예: naver-realestate-bot) 지정 → Repository permissions에서 "Actions: Read and write" 선택 → 생성. 토큰 값은 생성 직후 딱 한 번만 보여지므로 그 자리에서 바로 복사해서 안전한 곳(예: 비밀번호 관리자)에 저장해야 한다.
- **핵심 재사용 패턴 — "외부 알람이 GitHub API를 정시에 호출"**: GitHub 자체 예약(schedule)은 계정에 따라 몇 시간씩 늦게 실행될 수 있다. 정확한 시각 실행이 필요하면, cron-job.org 같은 외부 알람 서비스가 GitHub REST API의 workflow_dispatch 엔드포인트(POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches)를 직접 호출하도록 설정한다. 헤더에 Authorization: Bearer <PAT>, Accept: application/vnd.github+json, Content-Type: application/json을 넣고 본문에 {"ref":"main"}을 넣으면 된다. 이 방식은 다른 어떤 GitHub 저장소/자동화에도 그대로 적용 가능.
