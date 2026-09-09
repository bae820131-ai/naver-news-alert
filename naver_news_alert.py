"""
네이버 뉴스 검색 API 키워드 알림 봇 (NAVER API HUB 버전)
- 지정한 키워드로 네이버 뉴스를 검색
- 이미 보낸 기사는 중복 전송하지 않음 (sent_links.json에 기록)
- 새 기사를 텔레그램 + 슬랙으로 전송

2026년부터 네이버 검색 API는 기존 네이버 개발자센터(openapi.naver.com)에서
NAVER API HUB(네이버 클라우드 플랫폼)로 이관되었습니다.
Client ID/Secret은 네이버 클라우드 플랫폼(ncloud.com) 콘솔에서 발급받으세요.

필요한 환경변수 (GitHub Actions Secrets 또는 로컬 .env):
  NAVER_CLIENT_ID       - NAVER API HUB(네이버 클라우드 플랫폼) 발급 Client ID
  NAVER_CLIENT_SECRET   - NAVER API HUB(네이버 클라우드 플랫폼) 발급 Client Secret
  TELEGRAM_BOT_TOKEN    - 텔레그램 봇 토큰 (선택, 없으면 텔레그램 전송 생략)
  TELEGRAM_CHAT_ID      - 텔레그램 채팅 ID (선택)
  SLACK_WEBHOOK_URL     - 슬랙 Incoming Webhook URL (선택, 없으면 슬랙 전송 생략)
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone

# ------------------------------------------------------------------
# 1) 여기에 원하는 키워드를 자유롭게 추가/삭제하세요.
# ------------------------------------------------------------------
KEYWORDS = [
    "주식보상",
    "RSA",
    "RSU",
    "스톡그랜트",
    "스탁그랜트",
    "Stock Grant",
    "Stock-Grant",
    "스톡옵션",
]

# ------------------------------------------------------------------
# 1-1) RSA, RSU 등 IT/보안 분야에서도 쓰이는 모호한 키워드는
#      아래 문맥 단어 중 하나라도 같이 나와야 알림 대상으로 인정합니다.
#      (없으면 암호화/보안/기타 IT 기사로 보고 걸러냄)
# ------------------------------------------------------------------
CONTEXT_REQUIRED = {
    "RSA": ["주식", "보상", "스톡", "임직원", "양도제한", "그랜트"],
    "RSU": ["주식", "보상", "스톡", "임직원", "양도제한", "그랜트"],
}

# 검색 결과 중 이 시간(시간 단위) 이내에 나온 기사만 알림 대상으로 처리
RECENT_HOURS = 1

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

SENT_LINKS_FILE = "sent_links.json"
# NAVER API HUB 뉴스 검색 엔드포인트 (구 openapi.naver.com/v1/search/news.json 에서 이관됨)
NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

KST = timezone(timedelta(hours=9))


def load_sent_links():
    if os.path.exists(SENT_LINKS_FILE):
        with open(SENT_LINKS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent_links(links):
    # 파일이 무한정 커지지 않도록 최근 2000개만 보관
    trimmed = list(links)[-2000:]
    with open(SENT_LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def search_naver_news(keyword, display=20):
    # NAVER API HUB 공통 인증 헤더 (구 X-Naver-Client-Id/Secret 에서 변경됨)
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": keyword,
        "display": display,
        "sort": "date",  # 최신순 정렬
        "format": "json",
    }
    resp = requests.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("items", [])


def strip_html(text):
    return (
        text.replace("<b>", "")
        .replace("</b>", "")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def normalize(text):
    # 대소문자, 공백 차이를 무시하고 비교하기 위한 정규화
    return "".join(text.lower().split())


def contains_exact_keyword(keyword, title, description):
    # 네이버 검색 API는 형태소 분석 기반이라 키워드가 실제로 안 들어있어도
    # 관련 기사로 잡힐 수 있음 -> 제목/요약에 정확히 그 문자열이 있는지 재확인
    combined = normalize(title + " " + description)
    return normalize(keyword) in combined


def passes_context_filter(keyword, title, description):
    # RSA, RSU처럼 다른 분야(보안/IT 등)에서도 쓰이는 키워드는
    # 문맥 단어가 같이 있어야 통과시킴. CONTEXT_REQUIRED에 없는 키워드는 그냥 통과.
    required_words = CONTEXT_REQUIRED.get(keyword)
    if not required_words:
        return True
    combined = normalize(title + " " + description)
    return any(normalize(word) in combined for word in required_words)


def is_recent(pub_date_str, hours=RECENT_HOURS):
    # pubDate 예: "Tue, 08 Sep 2026 10:00:00 +0900"
    try:
        pub_dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        return True  # 파싱 실패 시 일단 포함
    now = datetime.now(KST)
    return (now - pub_dt) <= timedelta(hours=hours)


def send_telegram(message):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, data=payload, timeout=10)
    if r.status_code != 200:
        print(f"[텔레그램 전송 실패] {r.status_code} {r.text}")


def send_slack(message):
    if not SLACK_WEBHOOK_URL:
        return
    payload = {"text": message}
    r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    if r.status_code != 200:
        print(f"[슬랙 전송 실패] {r.status_code} {r.text}")


def main():
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        raise SystemExit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 설정되지 않았습니다.")

    sent_links = load_sent_links()
    new_sent_links = set(sent_links)
    new_articles = []

    for keyword in KEYWORDS:
        try:
            items = search_naver_news(keyword)
        except requests.RequestException as e:
            print(f"[{keyword}] 검색 실패: {e}")
            continue

        for item in items:
            link = item.get("originallink") or item.get("link")
            if not link or link in new_sent_links:
                continue
            if not is_recent(item.get("pubDate", "")):
                continue

            raw_title = item.get("title", "")
            raw_description = item.get("description", "")
            title = strip_html(raw_title)
            description = strip_html(raw_description)

            # 제목/요약에 키워드 문자열이 실제로 없으면 건너뜀 (형태소 분석 오탐 방지)
            if not contains_exact_keyword(keyword, title, description):
                continue

            # RSA/RSU처럼 다른 분야와 겹치는 키워드는 문맥 단어 확인
            if not passes_context_filter(keyword, title, description):
                continue

            new_articles.append({"keyword": keyword, "title": title, "link": link})
            new_sent_links.add(link)

        time.sleep(0.2)  # 네이버 API 호출 간 살짝 텀

    if not new_articles:
        print("새 기사 없음")
        return

    for article in new_articles:
        message = f"📰 [{article['keyword']}] {article['title']}\n{article['link']}"
        send_telegram(message)
        send_slack(message)
        print(f"전송 완료: {message}")

    save_sent_links(new_sent_links)


if __name__ == "__main__":
    main()
