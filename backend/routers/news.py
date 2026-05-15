"""News Router — /api/news
FIXES:
- Added socket timeout so slow RSS feeds don't hang the server
- Endpoint registered as both "" and "/" so /api/news works without trailing slash
- Graceful fallback if all feeds fail (returns empty list, not 500)
- Sentiment now returns a dict (positive/negative/verdict) for easier frontend use
"""
from fastapi import APIRouter
import feedparser
import socket
from datetime import datetime

router = APIRouter()

RSS_FEEDS = [
    ("Economic Times Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Moneycontrol",           "https://www.moneycontrol.com/rss/business.xml"),
    ("Reuters Business",       "https://feeds.reuters.com/reuters/businessNews"),
    ("Mint Markets",           "https://www.livemint.com/rss/markets"),
]

POSITIVE_KW = ["growth","profit","bullish","strong","upgrade","record","expansion","beat","surge","positive","rise","rally","gain"]
NEGATIVE_KW = ["loss","decline","bearish","weak","downgrade","fall","drop","miss","crash","negative","slump","sell-off"]


def parse_time(time_str: str) -> datetime:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            return datetime.strptime(time_str, fmt)
        except Exception:
            pass
    return datetime.min


def fetch_feed_with_timeout(url: str, timeout: int = 8):
    """feedparser has no built-in timeout — use socket default timeout as workaround."""
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        return feedparser.parse(url)
    except Exception:
        return None
    finally:
        socket.setdefaulttimeout(old)


def compute_sentiment(news_list: list) -> dict:
    pos = neg = 0
    for item in news_list:
        text = item.get("title", "").lower()
        for w in POSITIVE_KW:
            if w in text:
                pos += 1
        for w in NEGATIVE_KW:
            if w in text:
                neg += 1

    if pos > neg + 2:
        verdict = "POSITIVE"
        verdict_text = "Good environment for longs"
    elif neg > pos + 2:
        verdict = "NEGATIVE"
        verdict_text = "Trade smaller size — caution"
    else:
        verdict = "MIXED"
        verdict_text = "Stick to highest-score setups only"

    return {"positive": pos, "negative": neg, "verdict": verdict, "verdict_text": verdict_text}


# Register both "" and "/" so /api/news and /api/news/ both work
@router.get("")
@router.get("/")
def get_news():
    news_items = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = fetch_feed_with_timeout(feed_url, timeout=8)
            if not feed or not feed.entries:
                continue
            for entry in feed.entries[:5]:
                time_str = entry.get("published", "")
                news_items.append({
                    "title":       entry.get("title", "No title")[:150],
                    "link":        entry.get("link", ""),
                    "source":      source_name,
                    "time":        time_str,
                    "_sort_time":  parse_time(time_str),
                })
        except Exception:
            continue  # never let one broken feed crash the whole endpoint

    # Sort latest first, remove internal sort key
    news_items.sort(key=lambda x: x["_sort_time"], reverse=True)
    for n in news_items:
        n.pop("_sort_time", None)

    news_items = news_items[:20]
    sentiment  = compute_sentiment(news_items)

    return {
        "news":      news_items,
        "count":     len(news_items),
        "sentiment": sentiment,
        "fetched_at": datetime.now().isoformat(),
        "status":    "ok" if news_items else "no_data",
    }