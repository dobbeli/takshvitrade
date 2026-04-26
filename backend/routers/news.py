# """News Router — /api/news (user's get_eod_news integrated)"""
# from fastapi import APIRouter
# import feedparser
# from datetime import datetime

# router = APIRouter()

# FEEDS = {
#     "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
#     "Moneycontrol":           "https://www.moneycontrol.com/rss/marketreports.xml",
#     "Reuters Business":       "https://feeds.reuters.com/reuters/businessNews",
#     "Mint Markets":           "https://www.livemint.com/rss/markets",
# }

# POSITIVE = ["rally","gain","rise","surge","bull","up","high","record","growth","positive"]
# NEGATIVE = ["fall","drop","decline","crash","bear","down","low","loss","recession","negative"]

# @router.get("/eod")
# def get_eod_news():
#     all_headlines = []
#     sources       = []

#     for source, url in FEEDS.items():
#         try:
#             feed    = feedparser.parse(url)
#             entries = feed.entries[:3]
#             if not entries: continue
#             items = []
#             for entry in entries:
#                 title = entry.get("title", "")[:120]
#                 pub   = entry.get("published", "")[:16]
#                 link  = entry.get("link", "")
#                 items.append({"title": title, "published": pub, "link": link})
#                 all_headlines.append(title)
#             sources.append({"source": source, "articles": items})
#         except Exception:
#             pass

#     text      = " ".join(all_headlines).lower()
#     pos_count = sum(1 for w in POSITIVE if w in text)
#     neg_count = sum(1 for w in NEGATIVE if w in text)

#     if pos_count > neg_count + 2:
#         verdict = "POSITIVE"
#         verdict_text = "Good environment for longs"
#     elif neg_count > pos_count + 2:
#         verdict = "NEGATIVE"
#         verdict_text = "Trade smaller size tomorrow"
#     else:
#         verdict = "MIXED"
#         verdict_text = "Stick to highest-score trades only"

#     return {
#         "sources":      sources,
#         "sentiment": {
#             "positive":     pos_count,
#             "negative":     neg_count,
#             "verdict":      verdict,
#             "verdict_text": verdict_text,
#         },
#         "fetched_at": datetime.now().isoformat(),
#     }

from fastapi import APIRouter
import feedparser
from datetime import datetime

router = APIRouter()

# 🔹 RSS Sources
RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/business.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.livemint.com/rss/markets",
]

# 🔥 Safe Time Parser (IMPORTANT for sorting)
def parse_time(time_str):
    try:
        return datetime.strptime(time_str, "%a, %d %b %Y %H:%M:%S %z")
    except:
        return datetime.min  # fallback if parsing fails


# 🔥 Sentiment Function
def get_news_sentiment(news_list):
    positive_keywords = [
        "growth", "profit", "bullish", "strong", "upgrade",
        "record", "expansion", "beat", "surge", "positive"
    ]

    negative_keywords = [
        "loss", "decline", "bearish", "weak", "downgrade",
        "fall", "drop", "miss", "crash", "negative"
    ]

    score = 0

    for news in news_list:
        text = news.get("title", "").lower()

        for word in positive_keywords:
            if word in text:
                score += 1

        for word in negative_keywords:
            if word in text:
                score -= 1

    return score


# 🔥 NEWS API
@router.get("/")
def get_news():
    news_items = []

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:5]:
            time_str = entry.get("published", "")

            news_items.append({
                "title": entry.title,
                "link": entry.link,
                "source": feed.feed.get("title", "Market"),
                "time": time_str,
                "parsed_time": parse_time(time_str)  # for sorting
            })

    # 🔥 SORT → Latest first
    news_items = sorted(news_items, key=lambda x: x["parsed_time"], reverse=True)

    # 🔥 Remove parsed_time before sending
    for n in news_items:
        n.pop("parsed_time", None)

    # 🔥 Calculate sentiment AFTER sorting
    sentiment_score = get_news_sentiment(news_items)

    # 🔥 Final response (UI compatible)
    return {
        "news": news_items[:15],
        "sentiment": sentiment_score
    }