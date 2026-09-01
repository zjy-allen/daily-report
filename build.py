# -*- coding: utf-8 -*-
"""
每日日报云端生成脚本（跑在 GitHub Actions 上）
抓取公开新闻源 -> 生成手机友好的单页 HTML（archive/YYYY-MM-DD.html + index.html）
无 LLM，纯聚合：每条新闻为「标题 + 日期 + 原文链接」。
"""
import html
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

CN_TZ = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
TIMEOUT = 25
STRIP_TAGS = re.compile(r"<[^>]+>")


def log(msg):
    print(msg, flush=True)


def fetch_text(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


def fmt_pubdate(raw):
    """RSS pubDate -> 'MM-DD'；失败返回 ''"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{m.group(2)}-{m.group(3)}"
    try:
        dt = parsedate_to_datetime(raw)
        dt = dt.astimezone(CN_TZ)
        return dt.strftime("%m-%d")
    except Exception:
        return ""


# ---------------- 新闻源 ----------------

def rss_items(xml_text, n=8):
    """通用 RSS 解析：title 可缺省时用 description 兜底"""
    out = []
    root = ET.fromstring(xml_text.encode("utf-8"))
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = (it.findtext("description") or "").strip()
        if not title and desc:
            title = STRIP_TAGS.sub("", desc)[:60].strip()
        if not title or not link:
            continue
        out.append((title, link, fmt_pubdate(it.findtext("pubDate"))))
        if len(out) >= n:
            break
    return out


def src_politics(n=8):
    """国家大事：中新网滚动新闻，优先 /gn/（国内）条目"""
    items = rss_items(fetch_text("https://www.chinanews.com.cn/rss/scroll-news.xml"), n=40)

    def rank(tu):
        url = tu[1]
        if "/gn/" in url:
            return 0
        if "/sh/" in url or "/tp/" in url:
            return 1
        if "/gj/" in url:
            return 2
        return 3

    items.sort(key=rank)
    return items[:n]


def src_world(n=8):
    """世界大事（中国之外）：联合早报国际 + 中新网国际频道，按新到旧合并"""
    merged, seen = [], set()

    def add(items):
        for t, u, d in items:
            key = re.sub(r"\s+", "", t)[:20]
            if key in seen:
                continue
            seen.add(key)
            merged.append((t, u, d))

    try:
        text = fetch_text("https://www.zaobao.com/news/world")
        soup = BeautifulSoup(text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            m = re.search(r"(/news/world/story\d{8}-\d+)", a["href"])
            if not m:
                continue
            title = a.get_text(strip=True)
            if len(title) < 6:
                continue
            dm = re.search(r"story(\d{4})(\d{2})(\d{2})-", m.group(1))
            datestr = f"{dm.group(2)}-{dm.group(3)}" if dm else ""
            items.append((title, "https://www.zaobao.com" + m.group(1), datestr))
        # 去重保持顺序
        dedup, u_seen = [], set()
        for t, u, d in items:
            if u not in u_seen:
                u_seen.add(u)
                dedup.append((t, u, d))
        add(dedup[:n])
        log(f"[ok] zaobao world: {len(dedup)} items")
    except Exception as e:
        log(f"[warn] zaobao world failed: {e}")

    try:
        text = fetch_text("https://www.chinanews.com.cn/world/")
        soup = BeautifulSoup(text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            m = re.search(r"(/gj/20\d{2}/\d{2}-\d{2}/\d+\.shtml)", a["href"])
            if not m:
                continue
            title = a.get_text(strip=True)
            if len(title) < 8 or title.endswith("..."):
                continue
            path = m.group(1)
            dm = re.search(r"/(\d{2})-(\d{2})/", path)
            items.append((title, "https://www.chinanews.com.cn" + path, dm.group(0)[1:6] if dm else ""))
        dedup, u_seen = [], set()
        for t, u, d in items:
            if u not in u_seen:
                u_seen.add(u)
                dedup.append((t, u, d))
        add(dedup[:n])
        log(f"[ok] chinanews world: {len(dedup)} items")
    except Exception as e:
        log(f"[warn] chinanews world failed: {e}")

    return merged[:n]


def src_finance(n=8):
    """财经：华尔街见闻"""
    return rss_items(fetch_text("https://dedicated.wallstreetcn.com/rss.xml"), n=n)


def src_ai(n=8):
    """AI：量子位"""
    return rss_items(fetch_text("https://www.qbitai.com/feed"), n=n)


# ---------------- 页面渲染 ----------------

CSS = """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    background: #f2f3f5; color: #1c1c1e; line-height: 1.6; }
  .hero { background: linear-gradient(135deg, #10214b 0%, #1d3a8f 60%, #2b5cff 100%); color: #fff; padding: 30px 20px 24px; }
  .hero-inner { max-width: 680px; margin: 0 auto; }
  .badge { display: inline-block; font-size: 12px; letter-spacing: 2px; border: 1px solid rgba(255,255,255,.45);
    border-radius: 999px; padding: 3px 12px; opacity: .95; }
  .hero h1 { font-size: 26px; margin-top: 12px; font-weight: 700; }
  .hero .meta { margin-top: 6px; font-size: 13px; opacity: .82; }
  .nav { max-width: 680px; margin: 14px auto 0; padding: 0 16px; display: flex; gap: 8px; }
  .nav a { flex: 1; text-align: center; text-decoration: none; font-size: 13px; color: #1d3a8f; background: #e3eaff;
    border-radius: 999px; padding: 7px 0; font-weight: 600; }
  main { max-width: 680px; margin: 0 auto; padding: 4px 16px 48px; }
  section { margin-top: 26px; }
  .sec-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }
  .sec-head .emoji { font-size: 20px; }
  .sec-head h2 { font-size: 19px; font-weight: 700; }
  .sec-head .line { flex: 1; height: 3px; border-radius: 2px; opacity: .25; }
  .sec-politics .line { background: #d84a3f; } .sec-politics h2 { color: #c2392e; }
  .sec-world .line { background: #2b7de0; } .sec-world h2 { color: #1e6fd0; }
  .sec-finance .line { background: #b8860b; } .sec-finance h2 { color: #9a6b00; }
  .sec-ai .line { background: #7b4bd8; } .sec-ai h2 { color: #6a3ec9; }
  .card { background: #fff; border-radius: 14px; padding: 14px 16px; margin-top: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,.06); border-left: 4px solid transparent; }
  .sec-politics .card { border-left-color: #d84a3f; }
  .sec-world .card { border-left-color: #2b7de0; }
  .sec-finance .card { border-left-color: #d9a514; }
  .sec-ai .card { border-left-color: #7b4bd8; }
  .card h3 { font-size: 15.5px; font-weight: 700; line-height: 1.5; }
  .card h3 .tag { font-size: 11px; color: #999; font-weight: 400; }
  .card p { font-size: 13.5px; color: #555; margin-top: 5px; line-height: 1.65; }
  .card .src { margin-top: 7px; font-size: 12px; }
  .card .src a { color: #3a6ff0; text-decoration: none; }
  .headline h3 { font-size: 17px; }
  footer { max-width: 680px; margin: 0 auto; padding: 0 16px 48px; font-size: 12px; color: #9a9a9a; }
  footer .box { background: #ececee; border-radius: 12px; padding: 12px 14px; line-height: 1.8; }
  footer a { color: #3a6ff0; text-decoration: none; }
  @media (prefers-color-scheme: dark) {
    body { background: #111114; color: #e8e8ea; }
    .card { background: #1c1c20; box-shadow: none; }
    .card p { color: #b6b6bc; }
    .nav a { background: #23233a; color: #9db6ff; }
    footer .box { background: #1a1a1e; }
  }
"""

SECTION_DEFS = [
    ("politics", "🇨🇳", "国家大事", "politics"),
    ("world", "🌍", "世界大事", "world"),
    ("finance", "💰", "财经大事", "finance"),
    ("ai", "🤖", "AI 动态", "ai"),
]

SOURCE_NAME = {
    "chinanews.com.cn": "中国新闻网",
    "zaobao.com": "联合早报",
    "wallstreetcn.com": "华尔街见闻",
    "qbitai.com": "量子位",
}


def source_name(url):
    for k, v in SOURCE_NAME.items():
        if k in url:
            return v
    return "原文链接"


def esc(s):
    return html.escape(s or "", quote=True)


def render_section(sec_class, emoji, title, anchor, items, empty_note=""):
    head = (f'<div class="sec-head"><span class="emoji">{emoji}</span>'
            f'<h2>{title}</h2><span class="line"></span></div>')
    if not items:
        body = f'<div class="card"><p>{esc(empty_note or "本板块新闻源暂时抓取失败，请稍后查看。")}</p></div>'
        return f'<section class="sec-{sec_class}" id="{anchor}">{head}{body}</section>'
    cards = []
    for i, (t, u, d) in enumerate(items):
        date_tag = f'<span class="tag"> {esc(d)}</span>' if d else ""
        cards.append(
            f'<div class="card{" headline" if i == 0 else ""}">'
            f'<h3>{esc(t)}{date_tag}</h3>'
            f'<p class="src">来源：<a href="{esc(u)}" target="_blank" rel="noopener">{source_name(u)}</a></p>'
            f'</div>'
        )
    return f'<section class="sec-{sec_class}" id="{anchor}">{head}{"".join(cards)}</section>'


def render_page(date_str, weekday, issue, sections, prev_list, gen_time):
    nav = "".join(f'<a href="#{a}">{e} {t}</a>' for _, e, t, a in SECTION_DEFS)
    body = "".join(sections)
    prev_html = ""
    if prev_list:
        links = "<br>".join(f'<a href="archive/{esc(f)}">{esc(f[:-5])}</a>' for f in prev_list)
        prev_html = f"🗂 往期日报：<br>{links}<br>"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>每日日报 · {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    <span class="badge">每日日报 · DAILY BRIEFING</span>
    <h1>{date_str}</h1>
    <div class="meta">{weekday} · 第 {issue} 期 · 覆盖国家 / 世界 / 财经 / AI 大事 · 云端自动生成</div>
  </div>
</header>
<nav class="nav">{nav}</nav>
<main>
{body}
</main>
<footer>
  <div class="box">
    📌 本报由云端定时任务自动汇编自公开新闻源（中国新闻网 / 联合早报 / 华尔街见闻 / 量子位），内容以各来源原文为准。<br>
    {prev_html}🕐 数据截至 {gen_time}（北京时间）
  </div>
</footer>
</body>
</html>"""


def main():
    now = datetime.now(CN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    weekday = "星期" + "一二三四五六日"[now.weekday()]
    gen_time = now.strftime("%H:%M")

    sections_data = {}
    jobs = [("politics", src_politics), ("world", src_world),
            ("finance", src_finance), ("ai", src_ai)]
    for name, fn in jobs:
        try:
            sections_data[name] = fn(8)
            log(f"[ok] {name}: {len(sections_data[name])} items")
        except Exception as e:
            sections_data[name] = []
            log(f"[err] {name} failed: {e}")
        time.sleep(1)

    sections = []
    for key, emoji, title, anchor in SECTION_DEFS:
        sections.append(render_section(key, emoji, title, anchor, sections_data.get(key, [])))

    os.makedirs("archive", exist_ok=True)
    prev_files = sorted(f for f in os.listdir("archive") if re.match(r"^\d{4}-\d{2}-\d{2}\.html$", f))
    issue = len(prev_files) + 1

    page = render_page(date_str, weekday, issue, sections, prev_files, gen_time)

    with open(f"archive/{date_str}.html", "w", encoding="utf-8") as f:
        f.write(page)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)

    log(f"[done] {date_str} 第{issue}期 index.html + archive/{date_str}.html")
    log("[summary] " + ", ".join(f"{k}={len(v)}" for k, v in sections_data.items()))


if __name__ == "__main__":
    main()
