# 네이버 뉴스 키워드 알림 봇

주식보상제도 관련 키워드로 네이버 뉴스를 검색해 텔레그램/슬랙으로 알림을 보냅니다.
30분(또는 1시간) 주기로 GitHub Actions에서 자동 실행됩니다.

## 1. 네이버 API 키 발급 (NAVER API HUB)

⚠️ 2026년부터 네이버 검색 API는 기존 네이버 개발자센터(developers.naver.com)에서
**NAVER API HUB(네이버 클라우드 플랫폼)** 로 이관되었습니다. 아래 새 절차를 따르세요.

1. https://www.ncloud.com 접속 후 네이버 클라우드 플랫폼 계정으로 로그인 (없으면 회원가입, 결제수단 등록 필요할 수 있음)
2. 콘솔 접속 → 우측 상단 "리전 & 플랫폼"에서 한국 리전 선택
3. Menu → All Services → Application Services → **NAVER API HUB** 이동
4. 좌측 "Application" 메뉴 → "Application 등록" 클릭
5. 사용할 API로 "검색"(뉴스 검색 포함) 선택 → Application 이름 입력 후 완료
6. Application 상세 화면 → API 관리 하위 "인증 정보" 버튼 클릭 → Client ID / Client Secret 확인

참고: NAVER API HUB는 종량제(사용한 만큼 과금) 방식이지만, 현재는 한시적으로 무료 제공 중이며 유료 전환 시 사전 공지될 예정입니다.

## 2. 저장소 설정
1. 이 폴더(`naver_news_bot`)를 새 GitHub 저장소에 올립니다.
2. 저장소 Settings → Secrets and variables → Actions 에서 아래 값을 등록합니다.
   - `NAVER_CLIENT_ID`
   - `NAVER_CLIENT_SECRET`
   - `TELEGRAM_BOT_TOKEN` (텔레그램 알림을 원할 경우)
   - `TELEGRAM_CHAT_ID` (텔레그램 알림을 원할 경우)
   - `SLACK_WEBHOOK_URL` (슬랙 알림을 원할 경우, Incoming Webhook URL)
3. Settings → Actions → General 에서 "Read and write permissions"를 활성화하세요.
   (sent_links.json을 커밋해서 중복 전송을 막기 위함입니다.)

## 3. 키워드 수정
`naver_news_alert.py` 상단의 `KEYWORDS` 리스트를 원하는 대로 수정하세요.

```python
KEYWORDS = [
    "스톡옵션",
    "RSU",
    ...
]
```

## 4. 주기 변경
`.github/workflows/naver_news_alert.yml`의 cron 표현식을 수정하면 됩니다.
- 30분 주기 (기본값): `*/30 * * * *`
- 1시간 주기: `0 * * * *`

## 5. 동작 방식
- 각 키워드로 네이버 뉴스 검색 API 호출 (최신순 정렬)
- 최근 1시간 이내 발행된 기사만 필터링 (`RECENT_HOURS` 값으로 조절 가능)
- 이미 보낸 링크는 `sent_links.json`에 기록해두고 중복 알림 방지
- 새 기사가 있으면 텔레그램/슬랙으로 전송

## 6. 로컬 테스트
```bash
export NAVER_CLIENT_ID=xxx
export NAVER_CLIENT_SECRET=xxx
export TELEGRAM_BOT_TOKEN=xxx
export TELEGRAM_CHAT_ID=xxx
export SLACK_WEBHOOK_URL=xxx
pip install requests
python naver_news_alert.py
```
