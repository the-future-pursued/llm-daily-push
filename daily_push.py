#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每天把当天的所有计划推到微信（Server酱）。

按日期合并四条轨：
  · LLM 主计划    tasks.json         84 天，按"第几天"索引（起始 START_DATE）
  · LLM 补短板轨  supplement_28.json 28 天，同上
  · 数学竞赛冲刺  math.json          按日期索引（10/24–11/14）
  · 英语六级      cet6.json          按日期索引（10/24–12/12）

用法：
    python daily_push.py                 # 推送"今天"的任务
    python daily_push.py --dry-run       # 只看内容，不发
    python daily_push.py --date 2026-11-05
    python daily_push.py --day 12        # 只按 LLM 第几天算（调试用）
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------- 改这里就够了 ----------------
START_DATE = date(2026, 10, 23)   # LLM 第 1 天
GOAL_DATE = date(2027, 9, 1)      # 保研目标日
TOTAL_DAYS = 84                   # LLM 主计划天数
SUPPLEMENT_DEFAULT_HOURS = 0.75   # 补短板轨没有时长字段，按 45 分钟估算
# ---------------------------------------------

HERE = Path(__file__).resolve().parent
TASKS_FILE = HERE / "tasks.json"
SUPPLEMENT_FILE = HERE / "supplement_28.json"
CET6_FILE = HERE / "cet6.json"
MATH_FILE = HERE / "math.json"
API_TMPL = "https://sctapi.ftqq.com/{key}.send"

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
CIRCLED = "①②③④⑤⑥"
CUT_RULE = (
    "**时间不够的砍法**：按硬截止排——数学（11/14 考）→ 六级（12/12 考）→ "
    "LLM 主计划；补短板轨只做「要交出来」那一项。"
)


def beijing_today() -> date:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).date()
    except Exception:
        return datetime.now(timezone(timedelta(hours=8))).date()


def read_key() -> str:
    key = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if key.startswith("SCT") and len(key) >= 20:
        return key
    f = HERE / "key.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("SCT") and len(line) >= 20:
                return line
    return ""


def load_list(path: Path):
    """按 day 整除索引的列表（tasks.json / supplement_28.json）。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {int(r["day"]): r for r in json.load(f)}


def load_bydate(path: Path):
    """按日期索引（math.json / cet6.json）。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def hours_of(text: str) -> float:
    """把 '1.5h' / '2h' / '141 分钟' / '10′' 换成小时数。"""
    if not text:
        return 0.0
    t = text.replace("小时", "h").strip()
    num = "".join(ch for ch in t if ch.isdigit() or ch == ".")
    try:
        v = float(num)
    except ValueError:
        return 0.0
    if "分" in t or "′" in t or "'" in t:
        return v / 60
    return v


def build(today: date, llm: dict, sup: dict, cet: dict, mathp: dict):
    dkey = today.isoformat()
    day = (today - START_DATE).days + 1
    left_goal = (GOAL_DATE - today).days

    blocks, title_bits, total_h = [], [], 0.0

    # ① LLM 主计划
    if 1 <= day <= TOTAL_DAYS and llm.get(day):
        t = llm[day]
        total_h += hours_of(t["time"])
        title_bits.append(f"LLM D{day}")
        blocks.append(
            f"**LLM 主计划 D{day}/84 · {t['time']}**\n"
            f"做：{t['task']}\n"
            f"交：{t['output']}"
        )

    # ② 补短板轨
    s = sup.get(day) if 1 <= day <= TOTAL_DAYS else None
    if s:
        total_h += SUPPLEMENT_DEFAULT_HOURS
        blocks.append(
            f"**LLM 补短板 D{day} · 30—60 分钟**\n"
            f"做：{s['task']}\n"
            f"交：{s['output']}"
        )

    # ③ 数学冲刺
    m = mathp.get(dkey)
    if m:
        total_h += hours_of(m.get("video", ""))
        title_bits.append(f"数学 {m['dnum']}")
        head = f"**数学冲刺 {m['dnum']}"
        if m.get("video"):
            head += f" · 视频 {m['video']}"
        head += "**"
        body = [head, f"做：{m['title']}"]
        if m.get("goal"):
            body.append(f"要点：{m['goal']}")
        if m.get("methods"):
            body.append("解法：" + "｜".join(f"{x['name']}（{x['q']}）" for x in m["methods"]))
        blocks.append("\n".join(body))

    # ④ 六级
    c = cet.get(dkey)
    if c:
        total_h += hours_of(c.get("time", ""))
        title_bits.append("六级")
        body = [f"**六级 · {c.get('time') or '—'}**"]
        body += [f"· {x}" for x in c.get("tasks", [])]
        blocks.append("\n".join(body))

    if not blocks:
        return (
            f"{today.month}月{today.day}日 · 无计划",
            f"这一天四条轨都没有排任务（LLM 第 {day} 天，数学/六级已结束或未开始）。\n"
            f"距保研 {left_goal} 天。",
        )

    title = f"{today.month}/{today.day} {WEEKDAYS[today.weekday()]} · " + " + ".join(title_bits)
    if len(title) > 34:
        title = f"{today.month}/{today.day} {WEEKDAYS[today.weekday()]} · 今日 {len(blocks)} 块"

    parts = [f"**{today.month}月{today.day}日 {WEEKDAYS[today.weekday()]} · 共 {len(blocks)} 块**", ""]
    for i, b in enumerate(blocks):
        parts.append(f"{CIRCLED[i]} {b}")
        parts.append("")
    parts.append(f"**今日合计约 {total_h:.1f} 小时**（数学只算视频，做题另计）")
    parts.append("")
    parts.append(CUT_RULE)
    parts.append("")
    parts.append(f"LLM 第 {day}/84 天 · 距保研 {left_goal} 天")
    return title, "\n".join(parts)


def send(key: str, title: str, desp: str) -> None:
    data = urllib.parse.urlencode({"title": title, "desp": desp}).encode("utf-8")
    req = urllib.request.Request(
        API_TMPL.format(key=key),
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", "replace")
    try:
        code = json.loads(body).get("code")
    except Exception:
        code = None
    if code != 0:
        raise RuntimeError(f"Server酱返回异常: {body}")
    print("推送成功:", body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不发送")
    ap.add_argument("--day", type=int, default=None, help="强制按 LLM 第几天算")
    ap.add_argument("--date", default=None, help="强制指定日期 YYYY-MM-DD")
    args = ap.parse_args()

    if args.day:
        today = START_DATE + timedelta(days=args.day - 1)
    else:
        today = date.fromisoformat(args.date) if args.date else beijing_today()

    llm = load_list(TASKS_FILE)
    if not llm:
        print("读不到 tasks.json，检查文件是否和脚本放一起。", file=sys.stderr)
        return 2
    sup = load_list(SUPPLEMENT_FILE)
    cet = load_bydate(CET6_FILE)
    mathp = load_bydate(MATH_FILE)
    for name, d in (("supplement_28.json", sup), ("cet6.json", cet), ("math.json", mathp)):
        if not d:
            print(f"提示：没有读到 {name}，这一块今天不推。", file=sys.stderr)

    title, desp = build(today, llm, sup, cet, mathp)

    if args.dry_run:
        print("=" * 50)
        print("标题:", title)
        print("-" * 50)
        print(desp)
        print("=" * 50)
        return 0

    key = read_key()
    if not key:
        print(
            "没读到 SendKey。两种填法任选其一：\n"
            "  1) 把 SCT... 那串粘进本目录的 key.txt（推荐）\n"
            "  2) PowerShell 里临时设置：$env:SERVERCHAN_SENDKEY='SCTxxxxx'\n"
            "GitHub 上跑的话，要在仓库 Settings → Secrets → Actions 里加同名 secret。",
            file=sys.stderr,
        )
        return 2

    send(key, title, desp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
