#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台风警戒机器人 v2
数据源: JMA (西北太平洋)  NHC (大西洋/东太平洋)
推送:  webhook_lang = zh → 中文   ja → 日文
触发:  Windows 任务计划程序  08:40 / 14:40 北京时间
"""

import json, re, sys, math, urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT    = Path(__file__).parent
CONFIG  = ROOT / "config.json"
LOGFILE = ROOT / "logs" / "run-log.md"

WARN_KM = 500   # 台风中心距机场 ≤500km 视为"接近"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

JMA_URL    = "https://www.jma.go.jp/en/typh/"
NHC_AT_URL = "https://www.nhc.noaa.gov/index-at.xml"
NHC_EP_URL = "https://www.nhc.noaa.gov/index-ep.xml"

# ── 机场数据库 ─────────────────────────────────────────────────────────────
CN_AIRPORTS = [
    {"code": "PVG", "name": "上海浦东",   "name_ja": "上海浦東",   "lat": 31.14, "lon": 121.80},
    {"code": "SHA", "name": "上海虹桥",   "name_ja": "上海虹橋",   "lat": 31.20, "lon": 121.34},
    {"code": "PEK", "name": "北京首都",   "name_ja": "北京首都",   "lat": 40.08, "lon": 116.60},
    {"code": "PKX", "name": "北京大兴",   "name_ja": "北京大興",   "lat": 39.51, "lon": 116.41},
    {"code": "CAN", "name": "广州白云",   "name_ja": "広州白雲",   "lat": 23.39, "lon": 113.30},
    {"code": "SZX", "name": "深圳宝安",   "name_ja": "深圳宝安",   "lat": 22.64, "lon": 113.81},
    {"code": "XMN", "name": "厦门高崎",   "name_ja": "アモイ",     "lat": 24.54, "lon": 118.13},
    {"code": "FOC", "name": "福州长乐",   "name_ja": "福州",       "lat": 25.93, "lon": 119.66},
    {"code": "HGH", "name": "杭州萧山",   "name_ja": "杭州",       "lat": 30.23, "lon": 120.43},
    {"code": "NKG", "name": "南京禄口",   "name_ja": "南京",       "lat": 31.74, "lon": 118.86},
    {"code": "HAK", "name": "海口美兰",   "name_ja": "海口",       "lat": 20.00, "lon": 110.46},
    {"code": "SYX", "name": "三亚凤凰",   "name_ja": "三亜",       "lat": 18.31, "lon": 109.41},
    {"code": "HKG", "name": "香港",       "name_ja": "香港",       "lat": 22.31, "lon": 113.91},
    {"code": "MFM", "name": "澳门",       "name_ja": "マカオ",     "lat": 22.15, "lon": 113.59},
]

JP_AIRPORTS = [
    {"code": "NRT", "name": "东京成田",    "name_ja": "東京成田",   "lat": 35.77, "lon": 140.39},
    {"code": "HND", "name": "东京羽田",    "name_ja": "東京羽田",   "lat": 35.55, "lon": 139.78},
    {"code": "KIX", "name": "大阪关西",    "name_ja": "大阪関西",   "lat": 34.43, "lon": 135.24},
    {"code": "NGO", "name": "名古屋",      "name_ja": "名古屋",     "lat": 34.86, "lon": 136.81},
    {"code": "FUK", "name": "福冈",        "name_ja": "福岡",       "lat": 33.59, "lon": 130.45},
    {"code": "OKA", "name": "冲绳那霸",    "name_ja": "沖縄那覇",   "lat": 26.20, "lon": 127.65},
    {"code": "CTS", "name": "札幌新千岁",  "name_ja": "札幌新千歳", "lat": 42.78, "lon": 141.69},
    {"code": "KOJ", "name": "鹿儿岛",      "name_ja": "鹿児島",     "lat": 31.80, "lon": 130.72},
    {"code": "ISG", "name": "石垣岛",      "name_ja": "石垣島",     "lat": 24.40, "lon": 124.16},
]

# ── 强度等级 ──────────────────────────────────────────────────────────────
WARN_LEVEL = {
    "Tropical Depression":   0,
    "Tropical Storm":        0,
    "Severe Tropical Storm": 1,
    "Typhoon":               2,
    "Severe Typhoon":        2,
    "Super Typhoon":         3,
    "Hurricane":             2,
    "Major Hurricane":       3,
}

LV_LABEL_ZH = {1: "Lv.1", 2: "Lv.2（超标）", 3: "Lv.3（超标）"}
LV_LABEL_JA = {1: "Lv.1", 2: "Lv.2（基準超過）", 3: "Lv.3（基準超過）"}

TYPE_ZH = {
    "Tropical Storm":        "热带风暴",
    "Severe Tropical Storm": "强热带风暴",
    "Typhoon":               "台风",
    "Severe Typhoon":        "强台风",
    "Super Typhoon":         "超强台风",
    "Hurricane":             "飓风",
    "Major Hurricane":       "强飓风",
}

TYPE_JA = {
    "Tropical Storm":        "熱帯低気圧",
    "Severe Tropical Storm": "強熱帯低気圧",
    "Typhoon":               "台風",
    "Severe Typhoon":        "強台風",
    "Super Typhoon":         "猛烈な台風",
    "Hurricane":             "ハリケーン",
    "Major Hurricane":       "大型ハリケーン",
}


# ── 工具函数 ──────────────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [fetch error] {url}: {e}")
        return ""


def get_config():
    import os
    env_cfg = os.environ.get("BOT_CONFIG")
    if env_cfg:
        return json.loads(env_cfg)
    return json.loads(CONFIG.read_text(encoding="utf-8"))


# ── 数据解析 ──────────────────────────────────────────────────────────────
def parse_jma(html):
    """
    解析 JMA 西北太平洋台风页面。
    尽力提取当前位置坐标；无法解析时退化为无坐标记录（后续距离判断会跳过）。
    """
    if not html:
        return []

    storms = []
    seen   = set()

    # JMA 英文页用 <table> 行列出每个台风，每行含:
    #   编号、名称、等级、纬度(N)、经度(E)、方向、速度、气压、风速
    # 典型格式: "20.5N" "125.3E"  或  "20.5°N" "125.3°E"
    type_pat = re.compile(
        r'(Super Typhoon|Severe Typhoon|Typhoon|Severe Tropical Storm|Tropical Storm|Tropical Depression)',
        re.IGNORECASE
    )
    lat_pat = re.compile(r'(\d+\.?\d*)\s*[°]?\s*N', re.IGNORECASE)
    lon_pat = re.compile(r'(\d+\.?\d*)\s*[°]?\s*E', re.IGNORECASE)

    # 按 <tr> 分块
    for row in re.split(r'<tr[\s>]', html, flags=re.IGNORECASE):
        clean = re.sub(r'<[^>]+>', ' ', row)
        clean = re.sub(r'&[a-zA-Z0-9#]+;', ' ', clean)
        clean = ' '.join(clean.split())

        type_m = type_pat.search(clean)
        if not type_m:
            continue

        lat_m = lat_pat.search(clean)
        lon_m = lon_pat.search(clean)
        if not lat_m or not lon_m:
            continue

        lat = float(lat_m.group(1))
        lon = float(lon_m.group(1))

        # 忽略明显位于南半球或经度不在西北太平洋范围的噪声
        if not (0 < lat < 60 and 100 < lon < 180):
            continue

        name_m = re.search(r'\b([A-Z][a-z]{3,11})\b', clean)
        name   = name_m.group(1) if name_m else "Unknown"
        key    = (name.lower(), round(lat, 0))
        if key in seen:
            continue
        seen.add(key)

        stype = type_m.group(1).title()
        if WARN_LEVEL.get(stype, 0) < 1:
            continue

        storms.append({
            "name": name,
            "type": stype,
            "basin": "西北太平洋",
            "positions": [{"hour": 0, "lat": lat, "lon": lon}],
        })

    return storms


def parse_nhc_rss(rss_html, basin_label):
    """解析 NHC RSS，对每条活跃气旋跟进 advisory 页面提取 24h 预报坐标。"""
    if not rss_html:
        return []

    storms = []
    seen   = set()

    for item in re.findall(r'<item>(.*?)</item>', rss_html, re.DOTALL | re.IGNORECASE):
        title_m = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
        link_m  = re.search(r'<link>(.*?)</link>',  item, re.DOTALL)
        if not title_m or not link_m:
            continue

        title = re.sub(r'<[^>]+>|&[a-z]+;', ' ', title_m.group(1)).strip()
        link  = link_m.group(1).strip()

        if re.search(r'post.tropical|remnant|invest', title, re.IGNORECASE):
            continue

        m = re.match(
            r'(Major Hurricane|Hurricane|Tropical Storm|Tropical Depression|Subtropical Storm)\s+([A-Z]+)',
            title, re.IGNORECASE
        )
        if not m:
            continue

        stype = m.group(1).title()
        sname = m.group(2).capitalize()
        if WARN_LEVEL.get(stype, 0) < 1:
            continue
        if sname in seen:
            continue
        seen.add(sname)

        positions = fetch_nhc_positions(link)
        storms.append({
            "name":      sname,
            "type":      stype,
            "basin":     basin_label,
            "positions": positions,
        })

    return storms


def fetch_nhc_positions(page_url):
    """
    从 NHC advisory 页面提取当前位置和 12h/24h 预报坐标。
    NHC advisory 文本格式:
      LOCATION...20.3N  70.4W
      12 HR...21.5N  71.5W
      24 HR...23.0N  73.0W
    """
    positions = []
    html = fetch(page_url)
    if not html:
        return positions

    text = re.sub(r'<[^>]+>', ' ', html)

    # 当前位置
    loc = re.search(r'LOCATION\s*\.{2,}\s*(\d+\.?\d*)[NS]\s+(\d+\.?\d*)[EW]', text, re.IGNORECASE)
    if loc:
        lat_raw = re.search(r'LOCATION\s*\.{2,}\s*(\d+\.?\d*)([NS])', text, re.IGNORECASE)
        lon_raw = re.search(r'LOCATION\s*\.{2,}\s*\d+\.?\d*[NS]\s+(\d+\.?\d*)([EW])', text, re.IGNORECASE)
        if lat_raw and lon_raw:
            lat = float(lat_raw.group(1)) * (-1 if lat_raw.group(2).upper() == 'S' else 1)
            lon = float(lon_raw.group(1)) * (-1 if lon_raw.group(2).upper() == 'W' else 1)
            positions.append({"hour": 0, "lat": lat, "lon": lon})

    # 预报位置  "12 HR...21.5N  71.5W"  或  "FORECAST VALID 12Z...21.5N  71.5W"
    for m in re.finditer(
        r'(?:FORECAST VALID\s*\d+Z[^\n]*?|(\d+)\s*HR\s*\.{2,}\s*)(\d+\.?\d*)([NS])\s+(\d+\.?\d*)([EW])',
        text, re.IGNORECASE
    ):
        hr_m = re.search(r'(\d+)\s*HR', m.group(0), re.IGNORECASE)
        if not hr_m:
            continue
        hr = int(hr_m.group(1))
        if hr not in (12, 24):
            continue
        lat = float(m.group(2)) * (-1 if m.group(3).upper() == 'S' else 1)
        lon = float(m.group(4)) * (-1 if m.group(5).upper() == 'W' else 1)
        positions.append({"hour": hr, "lat": lat, "lon": lon})

    return positions


# ── 机场接近判断 ───────────────────────────────────────────────────────────
def find_affected_airports(storm, airports):
    """
    返回在 storm 未来 0-24h 轨迹 WARN_KM 范围内的机场列表，
    按最小距离升序排列: [(airport_dict, min_km), ...]
    """
    positions = [p for p in storm.get("positions", []) if p["hour"] <= 24]
    if not positions:
        return []

    result = []
    for apt in airports:
        min_dist = min(haversine(apt["lat"], apt["lon"], p["lat"], p["lon"]) for p in positions)
        if min_dist <= WARN_KM:
            result.append((apt, min_dist))

    return sorted(result, key=lambda x: x[1])


# ── 消息构建 ──────────────────────────────────────────────────────────────
def _storm_line(storm, apts, lang):
    """生成单条台风警告文本行。"""
    type_str = TYPE_JA.get(storm["type"], storm["type"]) if lang == "ja" \
               else TYPE_ZH.get(storm["type"], storm["type"])
    sep      = "・" if lang == "ja" else "、"
    name_key = "name_ja" if lang == "ja" else "name"

    apt_str = sep.join(f"{a['code']} {a[name_key]}" for a, _ in apts[:3])

    if lang == "ja":
        return f"🌀 *{apt_str}* — {type_str} {storm['name']} 接近中，建议关注航班动态"
    else:
        return f"🌀 *{apt_str}* — {type_str} {storm['name']} 接近，建议关注航班动态"


def build_payload(cn_alerts, jp_alerts, lang="zh", sections=None):
    """
    构建 Slack Webhook payload。
    使用传统 attachment text 字段（非 blocks）以确保彩色竖边栏正常显示。
    CN 区块附 Windy 链接，JP 区块附 JMA 链接。
    """
    cn_count = len(cn_alerts)
    jp_count = len(jp_alerts)

    if lang == "ja":
        cn_header = f"*CN 中国 · 今後24時間の警戒台風*　{cn_count}件"
        jp_header = f"*JP 日本 · 今後24時間の警戒台風*　{jp_count}件"
        cn_empty  = "✅ 今後24時間以内に警戒レベルの台風接近なし。各空港は通常運航。"
        jp_empty  = "✅ 今後24時間以内に警戒レベルの台風接近なし。各空港は通常運航。"
        cn_link   = "🌐 <https://www.windy.com/hurricanes|Windy 経路図>"
        jp_link   = "🌐 <https://www.jma.go.jp/en/typh/|JMA 台風情報>"
        note      = "自社警戒基準（強熱帯低気圧以上）超過のみ表示"
    else:
        cn_header = f"*CN 中国 · 未来 24h 超警戒台风*　{cn_count}件"
        jp_header = f"*JP 日本 · 未来 24h 超警戒台风*　{jp_count}件"
        cn_empty  = "✅ 未来 24 小时无可能影响航班的热带气旋，各机场正常。"
        jp_empty  = "✅ 未来 24 小时无可能影响航班的热带气旋，各机场正常。"
        cn_link   = "🌐 <https://www.windy.com/hurricanes|Windy 全球路径图>"
        jp_link   = "🌐 <https://www.jma.go.jp/en/typh/|JMA 台风情报>"
        note      = "显示强热带风暴及以上（明显影响航班）"

    if sections is None:
        sections = ["cn", "jp"]

    cn_body = "\n".join(_storm_line(s, a, lang) for s, a in cn_alerts) if cn_alerts else cn_empty
    jp_body = "\n".join(_storm_line(s, a, lang) for s, a in jp_alerts) if jp_alerts else jp_empty

    attachments = []
    if "cn" in sections:
        attachments.append({
            "color":     "#E53E3E" if cn_count > 0 else "#38A169",
            "text":      f"{cn_header}\n{cn_body}\n{cn_link}",
            "mrkdwn_in": ["text"],
        })
    if "jp" in sections:
        attachments.append({
            "color":     "#E53E3E" if jp_count > 0 else "#38A169",
            "text":      f"{jp_header}\n{jp_body}\n{jp_link}",
            "mrkdwn_in": ["text"],
        })
    attachments.append({
        "color":     "#718096",
        "text":      note,
        "mrkdwn_in": ["text"],
    })

    return {"username": "台風警戒 Bot", "attachments": attachments}


# ── 周报 ──────────────────────────────────────────────────────────────────
def _send_weekly_ok(cfg):
    webhooks     = cfg.get("webhooks", {})
    lang_map     = cfg.get("webhook_lang", {})
    sections_map = cfg.get("webhook_sections", {})

    for name, url in webhooks.items():
        lang     = lang_map.get(name, "zh")
        sections = sections_map.get(name, ["cn", "jp"])

        if lang == "ja":
            lines = []
            if "cn" in sections:
                lines.append("CN 中国　本週リスクなし ✅")
            if "jp" in sections:
                lines.append("JP 日本　本週リスクなし ✅")
            lines.append("🌐 <https://www.jma.go.jp/en/typh/|JMA 台風情報>")
            note = "週次システム確認 · 自動送信"
        else:
            lines = []
            if "cn" in sections:
                lines.append("CN 中国　本周无台风风险 ✅")
            if "jp" in sections:
                lines.append("JP 日本　本周无台风风险 ✅")
            lines.append("🌐 <https://www.windy.com/hurricanes|Windy 全球路径图>")
            note = "每周系统确认 · 自动推送"

        payload = {
            "username": "台風警戒 Bot",
            "attachments": [
                {
                    "color":     "#38A169",
                    "text":      "\n".join(lines),
                    "mrkdwn_in": ["text"],
                },
                {
                    "color":     "#718096",
                    "text":      note,
                    "mrkdwn_in": ["text"],
                },
            ]
        }
        print(f"  📤 {name} (周报)...")
        post_slack(url, payload)


# ── 推送 / 日志 ───────────────────────────────────────────────────────────
def post_slack(webhook_url, payload):
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(webhook_url, data=data,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"  Slack → {r.read().decode()}")
    except Exception as e:
        print(f"  Slack error: {e}")


def log_run(note):
    LOGFILE.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        existing = LOGFILE.read_text(encoding="utf-8") if LOGFILE.exists() else ""
        marker   = "| --- | --- | --- | --- | --- |\n"
        new_row  = f"| {ts} | — | — | — | {note} |\n"
        updated  = existing.replace(marker, marker + new_row, 1) if marker in existing else existing + new_row
        LOGFILE.write_text(updated, encoding="utf-8")
    except Exception as e:
        print(f"  [log error] {e}")


# ── 主流程 ────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"🌀 台风警戒机器人 v2  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'='*50}")

    cfg = get_config()

    # 抓取三个数据源
    print("📡 西北太平洋 (JMA)...")
    wp = parse_jma(fetch(JMA_URL))
    print(f"  → {len(wp)} 个" if wp else "  → 无")

    print("📡 大西洋 (NHC)...")
    at = parse_nhc_rss(fetch(NHC_AT_URL), "大西洋")
    print(f"  → {len(at)} 个" if at else "  → 无")

    print("📡 东太平洋 (NHC)...")
    ep = parse_nhc_rss(fetch(NHC_EP_URL), "东太平洋")
    print(f"  → {len(ep)} 个" if ep else "  → 无")

    # 合并并过滤强度低于警戒线的
    all_storms = [s for s in (wp + at + ep) if WARN_LEVEL.get(s.get("type", ""), 0) >= 1]
    print(f"\n📊 达到警戒线气旋: {len(all_storms)} 个")

    # 判断各机场是否在 24h 路径范围内
    cn_alerts, jp_alerts = [], []
    for storm in all_storms:
        cn_hit = find_affected_airports(storm, CN_AIRPORTS)
        if cn_hit:
            cn_alerts.append((storm, cn_hit))
            print(f"  ⚠️  CN: {storm['name']} → {', '.join(a['code'] for a, _ in cn_hit)}")

        jp_hit = find_affected_airports(storm, JP_AIRPORTS)
        if jp_hit:
            jp_alerts.append((storm, jp_hit))
            print(f"  ⚠️  JP: {storm['name']} → {', '.join(a['code'] for a, _ in jp_hit)}")

    now       = datetime.now()
    is_friday = now.weekday() == 4   # 0=周一 … 4=周五
    is_morning = now.hour < 12

    # 无台风：仅周五上午发一次系统确认，其余全部静默
    if not cn_alerts and not jp_alerts:
        if is_friday and is_morning:
            print("📅 周五系统确认推送...")
            _send_weekly_ok(cfg)
            log_run("周五系统确认")
        else:
            print("ℹ️  无警戒，静默退出。")
            log_run("无警戒（静默）")
        return

    webhooks     = cfg.get("webhooks", {})
    lang_map     = cfg.get("webhook_lang", {})
    sections_map = cfg.get("webhook_sections", {})
    for name, url in webhooks.items():
        lang     = lang_map.get(name, "zh")
        sections = sections_map.get(name, ["cn", "jp"])
        payload  = build_payload(cn_alerts, jp_alerts, lang=lang, sections=sections)
        print(f"  📤 {name} ({lang}, {sections})...")
        post_slack(url, payload)

    note = "推送: " + ", ".join(s["name"] for s in all_storms) if all_storms else "无活跃台风"
    log_run(note)
    print("✅ 完成")


if __name__ == "__main__":
    main()
