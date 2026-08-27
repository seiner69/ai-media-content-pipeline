#!/usr/bin/env python3
"""Record publish feedback so the media system can improve over time."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path


FIELDS = [
    "recorded_at",
    "date",
    "topic",
    "video",
    "views",
    "likes",
    "comments",
    "saves",
    "shares",
    "three_sec",
    "completion",
    "avg_watch",
    "comment_keywords",
    "notes",
]


def ratio(value: str | None) -> str:
    if value is None:
        return ""
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video", default="")
    parser.add_argument("--views", default="")
    parser.add_argument("--likes", default="")
    parser.add_argument("--comments", default="")
    parser.add_argument("--saves", default="")
    parser.add_argument("--shares", default="")
    parser.add_argument("--three-sec", default="")
    parser.add_argument("--completion", default="")
    parser.add_argument("--avg-watch", default="")
    parser.add_argument("--comment-keywords", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    base = Path(__file__).resolve().parents[1]
    log_path = base / "runs" / "feedback_log.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    row = {
        "recorded_at": dt.datetime.now().isoformat(timespec="seconds"),
        "date": args.date,
        "topic": args.topic,
        "video": args.video,
        "views": args.views,
        "likes": args.likes,
        "comments": args.comments,
        "saves": args.saves,
        "shares": args.shares,
        "three_sec": ratio(args.three_sec),
        "completion": ratio(args.completion),
        "avg_watch": args.avg_watch,
        "comment_keywords": args.comment_keywords,
        "notes": args.notes,
    }

    exists = log_path.exists()
    with log_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

    summary_path = base / "runs" / "feedback_summary.md"
    summary_path.write_text(render_summary(log_path), encoding="utf-8")
    print(f"feedback={log_path}")
    print(f"summary={summary_path}")
    return 0


def render_summary(log_path: Path) -> str:
    rows: list[dict[str, str]]
    with log_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    lines = ["# 发布反馈汇总", "", f"- Records: {len(rows)}", ""]
    if not rows:
        return "\n".join(lines)

    lines.extend(["## 最近记录", ""])
    for row in rows[-10:][::-1]:
        lines.extend(
            [
                f"### {row['date']} {row['topic']}",
                "",
                f"- Video: {row['video'] or 'N/A'}",
                f"- Views: {row['views'] or 'N/A'}",
                f"- Likes / Comments / Saves / Shares: {row['likes'] or 'N/A'} / {row['comments'] or 'N/A'} / {row['saves'] or 'N/A'} / {row['shares'] or 'N/A'}",
                f"- 3s / Completion / Avg watch: {row['three_sec'] or 'N/A'} / {row['completion'] or 'N/A'} / {row['avg_watch'] or 'N/A'}",
                f"- Comment keywords: {row['comment_keywords'] or 'N/A'}",
                f"- Notes: {row['notes'] or 'N/A'}",
                "",
            ]
        )
    lines.extend(
        [
            "## 下轮复盘问题",
            "",
            "- 开头 3 秒是否让人停下？",
            "- 中段是否过密或重复？",
            "- 评论里用户真正想继续问什么？",
            "- 哪类封面词带来点击，哪类只带来泛流量？",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
