#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每天把 LLM 计划当天的任务推到微信（Server酱）。

两条轨同时推：
  · 84 天主计划（tasks.json，从 LLM学习计划_12周.html 抽的）
  · 28 天补短板轨（supplement_28.json，从 前四周LLM补短板每日计划.md 抽的，只到第 28 天）

用法：
    python daily_push.py                 # 推送"今天"的任务
    python daily_push.py --dry-run       # 只看内容，不发
    python daily_push.py --day 12        # 假装今天是第 12 天
    python daily_push.py --date 2026-11-05

SendKey 从环境变量 SERVERCHAN_SENDKEY 读，不要写死在代码里。
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
START_DATE = date(2026, 10, 23)   # 第 1 天是哪天
GOAL_DATE = date(2027, 9, 1)      # 保研目标日，用来算倒计时
TOTAL_DAYS = 84                   # 主计划多少天
# ---------------------------------------------

HERE = Path(__file__).resolve().parent
TASKS_FILE = HERE / "tasks.json"
SUPPLEMENT_FILE = HERE / "supplement_28.json"
API_TMPL = "https://sctapi.ftqq.com/{key}.send"


def beijing_today() -> date:
    """取北京时间的今天。GitHub 的服务器走 UTC，必须显式换算，否则会差一天。"""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).date()
    except Exception:
        return datetime.now(timezone(timedelta(hours=8))).date()


def load_json(path: Path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        rows = json.load(f)
    return {int(r["day"]): r for r in rows}


def build(day: int, today: date, tasks, sup) -> tuple:
    """返回 (title, desp)。"""
    total = min(day, TOTAL_DAYS)
    left_goal = (GOAL_DATE - today).days
    left_plan = TOTAL_DAYS - day

    t = tasks.get(total)
    if t is None:
        return f"计划已到第 {day} 天", "任务表里没有这一天的内容了，去改 tasks.json。"

    title = f"D{day:02d} · {t['course']} {t['range']}"

    lines = [
        f"**第 {t['week']} 周 · 第 {day}/84 天 · 预计 {t['time']}**",
        "",
        f"**今天做**：{t['task']}",
        "",
        f"**要交出来**：{t['output']}",
    ]

    s = sup.get(day)
    if s:
        lines += [
            "",
            f"**补短板轨 D{day}（30—60 分钟）**",
            f"今天做：{s['task']}",
            f"要交出来：{s['output']}",
            "",
            "**时间不够的砍法**：只做补短板轨那条——84 天主计划 D8 的 RAG 要用 Python，"
            "这条是地基；主计划当天没做完，顺延到周末复盘日补。",
        ]
    else:
        lines += [
            "",
            "**时间不够的砍法**：只完成上面「要交出来」那一项，剩下的记到本周复盘日补。",
        ]

    if day == 29:
        lines += ["", "补短板轨 28 天已走完，从今天起只推 84 天主计划。"]

    lines += ["", f"进度 {day}/84（还剩 {left_plan} 天） · 距保研 {left_goal} 天"]
    return title, "\n".join(lines)


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
    ap.add_argument("--day", type=int, default=None, help="强制指定第几天")
    ap.add_argument("--date", default=None, help="强制指定日期 YYYY-MM-DD")
    args = ap.parse_args()

    if args.day:
        # 强制第 N 天时，把日期也一起算成那天，免得进度和倒计时对不上
        day = args.day
        today = START_DATE + timedelta(days=day - 1)
    else:
        today = date.fromisoformat(args.date) if args.date else beijing_today()
        day = (today - START_DATE).days + 1

    if day < 1:
        print(f"计划还没开始（第 1 天是 {START_DATE}），今天 {today}。")
        return 0

    tasks = load_json(TASKS_FILE)
    sup = load_json(SUPPLEMENT_FILE)
    if not tasks:
        print("读不到 tasks.json，检查文件是否和脚本放一起。", file=sys.stderr)
        return 2
    if not sup:
        print("提示：没有 supplement_28.json，今天只推 84 天主计划。", file=sys.stderr)

    title, desp = build(day, today, tasks, sup)

    if args.dry_run:
        print("=" * 46)
        print("标题:", title)
        print("-" * 46)
        print(desp)
        print("=" * 46)
        return 0

    key = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not key:
        print(
            "缺少 SERVERCHAN_SENDKEY。\n"
            "本地：$env:SERVERCHAN_SENDKEY='SCTxxxxx'\n"
            "GitHub：仓库 Settings → Secrets → Actions 里加同名 secret。",
            file=sys.stderr,
        )
        return 2

    send(key, title, desp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
