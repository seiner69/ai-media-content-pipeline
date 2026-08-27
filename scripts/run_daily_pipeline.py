#!/usr/bin/env python3
"""Daily AI self-media topic radar and content-pack generator."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


USER_AGENT = "CodexAIMediaSystem/0.1"


@dataclass
class Topic:
    source: str
    rank: int
    title: str
    url: str = ""
    hot_value: float = 0
    summary: str = ""
    raw_score: float = 0
    score: float = 0
    tags: list[str] | None = None
    reasons: list[str] | None = None
    hook: str = ""
    thesis: str = ""
    content_angle: str = ""


def fetch_json(url: str, timeout: int = 20) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def text_score(text: str, words: list[str], weight: float) -> tuple[float, list[str]]:
    matched = [w for w in words if w.lower() in text.lower()]
    if not matched:
        return 0, []
    return min(weight, weight * (0.35 + 0.18 * len(matched))), matched[:5]


def parse_hot_value(value: Any) -> float:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "")
    found = re.findall(r"\d+(?:\.\d+)?", text)
    if not found:
        return 0
    number = float(found[0])
    if "万" in text:
        number *= 10000
    if "亿" in text:
        number *= 100000000
    return number


def normalize_hotlist(source: str, payload: Any) -> list[Topic]:
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        for key in ("items", "list", "hot", "trends"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []

    topics: list[Topic] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name") or item.get("word") or item.get("keyword")
        if not title:
            continue
        topics.append(
            Topic(
                source=source,
                rank=int(item.get("rank") or index),
                title=str(title).strip(),
                url=str(item.get("url") or item.get("link") or item.get("mobile_url") or ""),
                hot_value=parse_hot_value(item.get("hot_value") or item.get("hot") or item.get("heat") or item.get("views")),
                summary=str(item.get("desc") or item.get("summary") or ""),
            )
        )
    return topics


def fetch_hotlists(config: dict[str, Any]) -> tuple[list[Topic], list[str]]:
    topics: list[Topic] = []
    errors: list[str] = []
    for source, url in config["sources"].get("hotlists", {}).items():
        try:
            topics.extend(normalize_hotlist(source, fetch_json(url)))
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    return topics, errors


def fetch_github(config: dict[str, Any], limit_per_query: int = 8) -> tuple[list[Topic], list[str]]:
    topics: list[Topic] = []
    errors: list[str] = []
    for query in config["sources"].get("github_search", []):
        encoded = urllib.parse.urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": str(limit_per_query)})
        url = f"https://api.github.com/search/repositories?{encoded}"
        try:
            payload = fetch_json(url)
            for index, item in enumerate(payload.get("items", []), 1):
                topics.append(
                    Topic(
                        source=f"github:{query}",
                        rank=index,
                        title=item.get("full_name", ""),
                        url=item.get("html_url", ""),
                        hot_value=float(item.get("stargazers_count") or 0),
                        summary=item.get("description") or "",
                    )
                )
            time.sleep(0.4)
        except Exception as exc:
            errors.append(f"github:{query}: {exc}")
    return topics, errors


def fetch_hackernews(config: dict[str, Any], limit_per_query: int = 8) -> tuple[list[Topic], list[str]]:
    topics: list[Topic] = []
    errors: list[str] = []
    for query in config["sources"].get("hackernews_queries", []):
        encoded = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": str(limit_per_query)})
        url = f"https://hn.algolia.com/api/v1/search_by_date?{encoded}"
        try:
            payload = fetch_json(url)
            for index, item in enumerate(payload.get("hits", []), 1):
                title = item.get("title") or item.get("story_title") or ""
                if not title:
                    continue
                topics.append(
                    Topic(
                        source=f"hn:{query}",
                        rank=index,
                        title=title,
                        url=item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}",
                        hot_value=float(item.get("points") or 0),
                        summary=f"comments={item.get('num_comments') or 0}",
                    )
                )
            time.sleep(0.2)
        except Exception as exc:
            errors.append(f"hn:{query}: {exc}")
    return topics, errors


def build_synthetic_topics(raw_topics: list[Topic]) -> list[Topic]:
    """Turn raw signals into creator-native story ideas.

    Raw trend items are often repo names or news titles. A media system needs a
    translation layer: many weak signals become one shootable topic.
    """
    text = "\n".join(f"{topic.title} {topic.summary}" for topic in raw_topics).lower()

    def count(*needles: str) -> int:
        return sum(text.count(needle.lower()) for needle in needles)

    agent_signals = count("agent", "智能体", "mcp", "coding agent")
    video_signals = count("video", "视频", "faceless", "shorts", "tiktok")
    content_signals = count("content", "social media", "自媒体", "automation", "calendar")
    news_signals = count("news", "briefing", "趋势", "trend")

    topics = [
        Topic(
            source="system:signal-cluster",
            rank=1,
            title="AI 自媒体真正拼的不是工具，而是一条稳定产线",
            url="docs/system-blueprint.md",
            hot_value=max(1, content_signals + news_signals + video_signals),
            summary="由内容自动化、趋势监控、AI 新闻简报、视频生成项目共同指向：稳定流程比单个工具更重要。",
        ),
        Topic(
            source="system:signal-cluster",
            rank=2,
            title="AI Agent 正在从聊天工具变成工作流入口",
            url="docs/system-blueprint.md",
            hot_value=max(1, agent_signals),
            summary="GitHub 和 HN 中 Agent、MCP、coding agent 相关信号持续出现，适合讲普通人如何从工具使用者变成流程设计者。",
        ),
        Topic(
            source="system:signal-cluster",
            rank=3,
            title="AI 视频生成让制作成本下降，真正稀缺的是选题系统",
            url="docs/system-blueprint.md",
            hot_value=max(1, video_signals),
            summary="AI video generator、faceless video、shorts 自动化项目说明制作门槛降低，创作者竞争会前移到选题和判断。",
        ),
        Topic(
            source="system:signal-cluster",
            rank=4,
            title="AI 资讯过载时代，个人创作者需要自己的选题雷达",
            url="docs/system-blueprint.md",
            hot_value=max(1, news_signals),
            summary="AI news briefing、trend monitor、research ops 类项目说明信息筛选本身正在成为生产力。",
        ),
    ]
    return topics


def dedupe(topics: list[Topic]) -> list[Topic]:
    seen: set[str] = set()
    result: list[Topic] = []
    for topic in topics:
        key = re.sub(r"\W+", "", topic.title.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(topic)
    return result


def score_topic(topic: Topic, config: dict[str, Any]) -> Topic:
    keywords = config["keywords"]
    weights = config["scoring"]
    text = f"{topic.title} {topic.summary}"
    reasons: list[str] = []
    tags: list[str] = []

    ai_score, ai_hits = text_score(text, keywords["ai_core"], weights["ai_relevance"])
    audience_score, audience_hits = text_score(
        text, keywords["ordinary_people"] + keywords["creator"], weights["audience_relevance"]
    )
    conflict_score, conflict_hits = text_score(text, keywords["conflict"], weights["conflict"])
    visual_score, visual_hits = text_score(text, keywords["visual"], weights["visual_evidence"])

    source_fit = 0
    if topic.source.startswith(("github", "hn")):
        source_fit += weights["format_fit"] * 0.65
        tags.append("AI行业信号")
    if topic.source in ("douyin", "weibo", "zhihu"):
        source_fit += weights["format_fit"] * 0.45
        tags.append("平台热度")
    if any(hit in text for hit in keywords["creator"]):
        source_fit += weights["format_fit"] * 0.35
        tags.append("创作者相关")
    if topic.source.startswith("system:"):
        source_fit = weights["format_fit"]
        tags.extend(["可直接拍摄", "系统命题"])
    source_fit = min(weights["format_fit"], source_fit)

    heat = 0
    if topic.hot_value > 0:
        heat = min(weights["timeliness"], math.log10(topic.hot_value + 10) / 8 * weights["timeliness"])
    rank_boost = max(0, 2.5 - topic.rank * 0.08)
    if topic.source.startswith("system:"):
        rank_boost += 18

    score = ai_score + audience_score + conflict_score + visual_score + source_fit + heat + rank_boost
    if ai_hits:
        reasons.append("AI相关：" + "、".join(ai_hits))
        tags.extend(ai_hits)
    if audience_hits:
        reasons.append("受众相关：" + "、".join(audience_hits))
        tags.extend(audience_hits)
    if conflict_hits:
        reasons.append("有冲突：" + "、".join(conflict_hits))
    if visual_hits:
        reasons.append("可视化：" + "、".join(visual_hits))
    if not reasons:
        reasons.append("低相关，仅作为泛热点观察")

    topic.score = round(score, 1)
    topic.raw_score = round(ai_score + audience_score + conflict_score + visual_score, 1)
    topic.reasons = reasons
    topic.tags = sorted(set(tags))[:8]
    topic.hook, topic.thesis, topic.content_angle = build_angle(topic)
    return topic


def build_angle(topic: Topic) -> tuple[str, str, str]:
    title = topic.title
    if "agent" in title.lower() or "智能体" in title:
        return (
            "你以为 AI Agent 只是一个新工具？真正变化是：它正在接管一整条工作流。",
            "AI Agent 的核心不是聊天，而是把任务从人手里拆出去、交给系统执行。",
            "讲清楚普通人如何从工具收藏者，变成流程设计者。",
        )
    if "video" in title.lower() or "视频" in title:
        return (
            "AI 视频真正冲击的不是剪辑软件，而是内容生产的成本结构。",
            "当视频生成变便宜，稀缺的会从制作能力转向选题、判断和审美。",
            "讲清楚 AI 视频时代创作者该补什么能力。",
        )
    if "news" in title.lower() or "brief" in title.lower() or "资讯" in title:
        return (
            "AI 资讯太多，真正值钱的不是知道更多，而是筛得更准。",
            "信息过载时代，个人创作者需要的是研究系统，不是更多收藏夹。",
            "讲清楚如何把资讯流变成选题雷达。",
        )
    if "content" in title.lower() or "自媒体" in title or "内容" in title:
        return (
            "自媒体最怕的不是没灵感，而是每次都从零开始。",
            "AI 自媒体的核心是一条可重复运行的内容产线。",
            "拆解从选题到发布复盘的稳定系统。",
        )
    return (
        f"今天这个信号别只看热闹：{title}",
        "真正值得拍的不是事件本身，而是它背后正在变化的生产规则。",
        "把热点翻译成普通人的 AI 行动建议。",
    )


def choose_primary(topics: list[Topic]) -> Topic:
    system_topics = [topic for topic in topics if topic.source.startswith("system:")]
    if system_topics:
        return system_topics[0]
    preferred = [
        topic
        for topic in topics
        if any(tag in (topic.tags or []) for tag in ("Agent", "智能体", "自媒体", "内容", "视频", "AI行业信号", "创作者相关"))
    ]
    return (preferred or topics)[0]


def render_shortlist(topics: list[Topic], run_date: str, errors: list[str]) -> str:
    lines = [
        f"# AI 自媒体每日选题短名单 {run_date}",
        "",
        "## 运行摘要",
        "",
        f"- 候选数：{len(topics)}",
        f"- 错误数：{len(errors)}",
        "",
    ]
    if errors:
        lines.extend(["## 抓取错误", ""])
        lines.extend(f"- {err}" for err in errors)
        lines.append("")
    lines.extend(["## Top 10", ""])
    for index, topic in enumerate(topics[:10], 1):
        lines.extend(
            [
                f"### {index}. {topic.title}",
                "",
                f"- Source: {topic.source} #{topic.rank}",
                f"- Score: {topic.score}",
                f"- Heat: {topic.hot_value:g}",
                f"- Link: {topic.url or 'N/A'}",
                f"- Tags: {'、'.join(topic.tags or [])}",
                f"- Why: {'；'.join(topic.reasons or [])}",
                f"- Hook: {topic.hook}",
                f"- Thesis: {topic.thesis}",
                f"- Angle: {topic.content_angle}",
                "",
            ]
        )
    return "\n".join(lines)


def render_content_pack(topic: Topic, config: dict[str, Any], run_date: str) -> str:
    title = topic.title
    account = config["account"]
    cover_title = "别再等灵感了"
    cover_subtitle = "AI 自媒体要靠产线"
    publish_title = "AI 自媒体真正拼的不是工具，而是这条稳定产线"
    publish_intro = "我参考了开源内容自动化、AI 新闻简报、趋势监控和视频生成项目，把 AI 自媒体拆成一套可复用流程：选题雷达、评分、文案、分镜、配音、画面、封面、标题、发布复盘。"
    tags = "#AI自媒体 #AI工具 #AI工作流 #短视频运营 #内容创作 #AI视频"
    if "agent" in title.lower() or "智能体" in title:
        cover_title = "Agent 不是工具"
        cover_subtitle = "它是下一代工作流入口"
        publish_title = "AI Agent不是聊天机器人，它正在变成工作流入口"
        publish_intro = "今天真正值得看的不是某个 AI Agent 工具，而是 Agent 正在把任务从人手里拆出去，变成一条可执行的工作流。普通人要补的不是收藏更多工具，而是学会设计流程、拆解任务、验收结果。"
        tags = "#AIAgent #智能体 #AI工作流 #AI工具 #普通人学AI #效率工具"
    elif "video" in title.lower() or "视频" in title:
        cover_title = "AI 视频来了"
        cover_subtitle = "创作者该补的不是剪辑"
        publish_title = "AI 视频生成越来越便宜，真正稀缺的是选题系统"
        publish_intro = "当 AI 视频生成降低制作成本，创作者的竞争会前移到选题、判断、审美和交付系统。会做视频不再够，能稳定发现值得拍的问题才更关键。"
        tags = "#AI视频 #AI自媒体 #内容创作 #短视频运营 #AI工具"

    return f"""# 内容包：{title}

- Date: {run_date}
- Account: {account['name']}
- Source: {topic.source}
- Link: {topic.url or 'N/A'}
- Score: {topic.score}

## 核心判断

{topic.thesis}

## 为什么现在值得拍

{'; '.join(topic.reasons or [])}

这个选题适合账号定位：{account['positioning']}。

## 3 秒开头

{topic.hook}

## 60-90 秒文案骨架

1. 先打断直觉：观众以为这是一个工具/新闻/热点，其实是生产方式变化。
2. 给事实卡：引用来源、项目、趋势或平台热度。
3. 拆误区：普通人常见错误是收藏工具、追新闻、等教程。
4. 给新判断：未来更值钱的是流程设计、任务拆解、结果验收。
5. 给行动：今天就建一个小系统，先稳定跑通一条内容产线。

## 画面分镜

| 页 | 画面 | 屏幕主文案 | 功能 |
|---|---|---|---|
| 1 | 暗色技术网格 + 大标题 | 别再问今天拍什么 | 强钩子 |
| 2 | 信号源卡片 | 选题不是灵感，是雷达 | 建立系统感 |
| 3 | 两栏对比 | 旧创作者 vs 新创作者 | 制造反差 |
| 4 | 六项评分流程 | AI相关、普通人相关、冲突、证据、风格、时效 | 方法论 |
| 5 | 内容包卡片 | 文案、分镜、配音、画面、标题、封面 | 全流程 |
| 6 | 闭环图 | 发布后才是真正开始 | 复盘意识 |
| 7 | 行动页 | 先跑一条产线 | 收束 |

## 配音风格

- 中文口播，短句，少英文。
- 语速略快，但每个判断句要有停顿。
- 避免把 GitHub、Agent 等英文连续堆在一句里。

## 封面

- 主标题：{cover_title}
- 副标题：{cover_subtitle}
- 视觉：沿用 v3 暗色科技风，青色信号线 + 金色重点卡。

## 标题

{publish_title}

## 简介

{publish_intro}

真正拉开差距的，不是你收藏了多少工具，而是你能不能稳定把一个想法做成一次交付。

你现在最卡的是选题、文案，还是视频制作？

## 标签

{tags}

## 发布后复盘

- 3 秒留存：开头是否足够反常识。
- 完播率：中段方法论是否过密。
- 评论关键词：用户最卡在哪一步。
- 收藏率：流程是否真的可执行。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/ai_niche.json")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()

    base = Path(__file__).resolve().parents[1]
    config_path = (base / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    errors: list[str] = []
    topics: list[Topic] = []
    for fetched, errs in (fetch_hotlists(config), fetch_github(config), fetch_hackernews(config)):
        topics.extend(fetched)
        errors.extend(errs)

    topics.extend(build_synthetic_topics(topics))
    topics = [score_topic(topic, config) for topic in dedupe(topics)]
    topics.sort(key=lambda item: item.score, reverse=True)
    topics = topics[: args.top]

    run_dir = base / "runs" / args.date
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "topics.json").write_text(
        json.dumps([asdict(topic) for topic in topics], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "shortlist.md").write_text(render_shortlist(topics, args.date, errors), encoding="utf-8")
    if topics:
        primary = choose_primary(topics)
        (run_dir / "content_pack.md").write_text(render_content_pack(primary, config, args.date), encoding="utf-8")

    log = {
        "date": args.date,
        "candidate_count": len(topics),
        "errors": errors,
        "primary_topic": choose_primary(topics).title if topics else None,
        "generated": ["topics.json", "shortlist.md", "content_pack.md"],
    }
    (run_dir / "run_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"run_dir={run_dir}")
    print(f"topics={len(topics)} errors={len(errors)}")
    if topics:
        print(f"top={topics[0].title} score={topics[0].score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
