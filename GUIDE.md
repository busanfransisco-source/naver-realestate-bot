# naver-realestate-bot — 오늘의 브리핑

매일 아침 운세, 날씨, 뉴스, 부동산, 환율, 금·코인, 베스트셀러를 모아 한 페이지로 만드는 자동화 봇.

브리핑 페이지: https://busanfransisco-source.github.io/naver-realestate-bot/briefing.html

## 작동 방식 (2026-07-18 기준)

GitHub Actions(깃허브의 자동 실행 기능)가 매일 스스로 데이터를 수집해 briefing.html을 새로 만든다. 클로드 앱이나 내 컴퓨터가 꺼져 있어도 상관없이 돌아간다.

예약 설정: .github/workflows/manual-briefing.yml 파일 안의 cron "25 18 * * *" (세계표준시 18:25 = 한국시간 새벽 3:25). GitHub 무료 예약은 보통 2~3시간 늦게 실행되므로 실제 브리핑 완성은 아침 6~7시쯤이다.

즉시 새로고침: trigger.txt 파일을 아무렇게나 수정해서 커밋하면 바로 새 브리핑이 만들어진다. 또는 Actions 탭 → Manual Briefing Refresh → Run workflow 버튼.

## 시간 바꾸는 법

manual-briefing.yml에서 cron: "25 18 * * *" 의 숫자를 수정한다. 순서는 "분 시" 이고 세계표준시 기준이므로 한국시간에서 9시간을 빼면 된다. 실제 실행이 2~3시간 늦는 것까지 감안해서 정할 것.

## 기록 및 주의사항

2026-07-17까지는 클로드(Claude) 데스크톱 앱의 예약 작업이 매일 아침 6:30에 trigger.txt를 갱신하는 방식이었다. 앱 재설치로 예약 작업이 사라지는 일이 있어서, 2026-07-18부터 GitHub 자체 예약으로 전환했다.

주의: 클로드 앱을 삭제 후 재설치하면 앱에 저장된 채팅과 예약 작업이 지워질 수 있다. 이 봇은 GitHub에서 돌아가므로 영향받지 않는다.
