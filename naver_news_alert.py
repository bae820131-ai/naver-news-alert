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
import difflib
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

# 제목 유사도가 이 값 이상이면 "같은 사건을 다룬 다른 언론사 기사"로 보고 건너뜀
# (0~1 사이 값, 1에 가까울수록 완전히 똑같아야 중복으로 판단)
TITLE_SIMILARITY_THRESHOLD = 0.72

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

SENT_LINKS_FILE = "sent_links.json"
# NAVER API HUB 뉴스 검색 엔드포인트 (구 openapi.naver.com/v1/search/news.json 에서 이관됨)
NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

KST = timezone(timedelta(hours=9))


def load_sent_data():
    """
    이전 실행 기록을 읽어옵니다.
    - 새 형식: [{"link": "...", "title": "..."}, ...]
    - 구 형식(문자열 리스트)도 그대로 인식해서 title 없이 불러옵니다.
    """
    if not os.path.exists(SENT_LINKS_FILE):
        return []
    with open(SENT_LINKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data and isinstance(data[0], str):
        return [{"link": link, "title": ""} for link in data]
    return data


def save_sent_data(items):
    # 파일이 무한정 커지지 않도록 최근 2000개만 보관
    trimmed = items[-2000:]
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


def is_duplicate_title(title, existing_titles, threshold=TITLE_SIMILARITY_THRESHOLD):
    # 언론사마다 제목이 조금씩 달라도 같은 사건이면 유사도가 높게 나옴
    norm_title = normalize(title)
    for existing in existing_titles:
        norm_existing = normalize(existing)
        if not norm_existing:
            continue
        ratio = difflib.SequenceMatcher(None, norm_title, norm_existing).ratio()
        if ratio >= threshold:
            return True
    return False


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

    sent_data = load_sent_data()
    sent_links = {item["link"] for item in sent_data}
    # 최근 200개 정도의 제목만 유사도 비교에 사용 (전체 다 비교하면 느려짐)
    recent_titles = [item.get("title", "") for item in sent_data[-200:] if item.get("title")]

    new_sent_links = set(sent_links)
    new_titles_this_run = []  # 이번 실행에서 채택한 기사 제목들 (같은 실행 내 유사 제목 비교용)
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

            # 이전에 보낸 기사 + 이번 실행에서 이미 채택한 기사와 제목이 비슷하면
            # 다른 언론사의 같은 사건 보도로 보고 건너뜀
            if is_duplicate_title(title, recent_titles + new_titles_this_run):
                continue

            new_articles.append({"keyword": keyword, "title": title, "link": link})
            new_sent_links.add(link)
            new_titles_this_run.append(title)

        time.sleep(0.2)  # 네이버 API 호출 간 살짝 텀

    if not new_articles:
        print("새 기사 없음")
        return

    for article in new_articles:
        message = f"📰 [{article['keyword']}] {article['title']}\n{article['link']}"
        send_telegram(message)
        send_slack(message)
        print(f"전송 완료: {message}")

    updated_data = sent_data + [
        {"link": article["link"], "title": article["title"]} for article in new_articles
    ]
    save_sent_data(updated_data)


if __name__ == "__main__":
    main()
