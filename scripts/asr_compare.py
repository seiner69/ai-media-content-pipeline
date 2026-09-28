#!/usr/bin/env python3
"""Transcribe generated narration and compare it with the intended script."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class DiffChunk:
    tag: str
    expected: str
    actual: str


@dataclass
class EditStats:
    inserted_chars: int = 0
    deleted_chars: int = 0
    replaced_expected_chars: int = 0
    replaced_actual_chars: int = 0


ASR_ALIASES = {
    "邏輯": "逻辑",
    "爱见": "agent",
    "而击气感觉": "机器人",
    "聊天而击气": "聊天机器人",
    "直线": "执行",
    "一万年而": "一个按钮",
    "资量": "资料",
    "变建": "边界",
    "布着": "步骤",
    "中点": "中间",
    "学的": "学的",
    "觉得其实": "学的",
    "有收藏": "又收藏",
    "三点事": "三件事",
    "只想到这些": "执行的",
    "给组": "给足",
    "实在": "时代",
    "之前": "值钱",
    "产现": "产线",
    "想提": "选题",
    "交本": "脚本",
    "方面": "封面",
    "复办": "复盘",
    "每部": "每步",
    "不复的": "不复杂",
    "联系了": "连起来",
    "不在室那个": "不再是",
    "直前": "值钱",
}


def normalize_for_compare(text: str, tolerant: bool = False) -> str:
    text = text.replace("\ufeff", "")
    text = re.sub(r"\[[a-zA-Z0-9_-]+\]", "", text)
    if tolerant:
        for src, dst in ASR_ALIASES.items():
            text = text.replace(src, dst)
        text = re.sub(r"[他她它]", "它", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？、,.!?；;：“”\"'（）()《》<>【】\[\]—…·`~]", "", text)
    text = text.lower()
    if tolerant:
        text = text.replace("然后", "")
        text = text.replace("就是", "")
    replacements = {
        "aiagent": "aiagent",
        "ai": "ai",
        "agent": "agent",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def load_expected(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").replace("\ufeff", "").strip()
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if isinstance(data, list):
            return "\n".join(str(item.get("text", "")).strip() for item in data if str(item.get("text", "")).strip())
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^\[[a-zA-Z0-9_-]+\]\s*", "", line)
        lines.append(line)
    return "\n".join(lines)


def transcribe_faster_whisper(audio: Path, model_name: str, language: str, local_files_only: bool) -> tuple[str, list[dict]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=local_files_only)
    segments, info = model.transcribe(
        str(audio),
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350},
        initial_prompt="这是一段中文短视频口播，主题包括 AI Agent、工作流、普通人、任务拆解、上下文、验收标准、个人生产系统。",
    )
    rows: list[dict] = []
    texts: list[str] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        rows.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": text})
        texts.append(text)
    return "\n".join(texts), rows


def transcribe_sensevoice(audio: Path, model_name: str, language: str) -> tuple[str, list[dict]]:
    from funasr import AutoModel

    model = AutoModel(model=model_name, trust_remote_code=True, disable_update=False)
    result = model.generate(input=str(audio), language=language, use_itn=True, batch_size_s=60)
    texts: list[str] = []
    for item in result:
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        text = re.sub(r"<\|.*?\|>", "", text).strip()
        if text:
            texts.append(text)
    transcript = "\n".join(texts)
    return transcript, [{"start": 0.0, "end": 0.0, "text": line} for line in texts]


def ratio(expected_norm: str, actual_norm: str) -> float:
    if not expected_norm and not actual_norm:
        return 1.0
    return difflib.SequenceMatcher(a=expected_norm, b=actual_norm).ratio()


def make_diff(expected_norm: str, actual_norm: str, max_chunks: int = 30) -> list[DiffChunk]:
    matcher = difflib.SequenceMatcher(a=expected_norm, b=actual_norm)
    chunks: list[DiffChunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        chunks.append(DiffChunk(tag=tag, expected=expected_norm[i1:i2], actual=actual_norm[j1:j2]))
        if len(chunks) >= max_chunks:
            break
    return chunks


def edit_stats(expected_norm: str, actual_norm: str) -> EditStats:
    matcher = difflib.SequenceMatcher(a=expected_norm, b=actual_norm)
    stats = EditStats()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            stats.inserted_chars += j2 - j1
        elif tag == "delete":
            stats.deleted_chars += i2 - i1
        elif tag == "replace":
            expected_count = i2 - i1
            actual_count = j2 - j1
            paired_count = min(expected_count, actual_count)
            stats.replaced_expected_chars += paired_count
            stats.replaced_actual_chars += paired_count
            # A replace opcode may hide extra or missing characters.
            # Account per block, so opposite surpluses cannot cancel out.
            stats.inserted_chars += max(0, actual_count - expected_count)
            stats.deleted_chars += max(0, expected_count - actual_count)
    return stats


def publish_gate(stats: EditStats) -> str:
    if stats.inserted_chars or stats.deleted_chars:
        return "fail_extra_or_missing"
    if stats.replaced_expected_chars or stats.replaced_actual_chars:
        return "review_typo_only"
    return "pass_exact"


def risk_level(similarity: float) -> str:
    if similarity >= 0.92:
        return "low"
    if similarity >= 0.84:
        return "medium"
    return "high"


def render_report(
    audio: Path,
    expected_path: Path,
    transcript: str,
    segments: list[dict],
    expected_text: str,
    similarity: float,
    tolerant_similarity: float,
    diffs: list[DiffChunk],
    strict_stats: EditStats,
    tolerant_stats: EditStats,
    engine: str,
    model_name: str,
) -> str:
    expected_norm = normalize_for_compare(expected_text)
    actual_norm = normalize_for_compare(transcript)
    expected_tolerant_norm = normalize_for_compare(expected_text, tolerant=True)
    actual_tolerant_norm = normalize_for_compare(transcript, tolerant=True)
    lines = [
        "# ASR 文案一致性检测",
        "",
        f"- Audio: `{audio}`",
        f"- Expected: `{expected_path}`",
        f"- ASR engine: `{engine}`",
        f"- ASR model: `{model_name}`",
        f"- Strict similarity: {similarity:.4f}",
        f"- Tolerant similarity: {tolerant_similarity:.4f}",
        f"- Risk: {risk_level(tolerant_similarity)}",
        f"- Publish gate(final, strict): `{publish_gate(strict_stats)}`",
        f"- Publish gate(strict): `{publish_gate(strict_stats)}`",
        f"- Publish gate(tolerant): `{publish_gate(tolerant_stats)}`",
        f"- Strict inserted chars: {strict_stats.inserted_chars}",
        f"- Strict deleted chars: {strict_stats.deleted_chars}",
        f"- Strict replaced chars: {strict_stats.replaced_expected_chars} -> {strict_stats.replaced_actual_chars}",
        f"- Tolerant inserted chars: {tolerant_stats.inserted_chars}",
        f"- Tolerant deleted chars: {tolerant_stats.deleted_chars}",
        f"- Tolerant replaced chars: {tolerant_stats.replaced_expected_chars} -> {tolerant_stats.replaced_actual_chars}",
        f"- Expected chars(normalized): {len(expected_norm)}",
        f"- Actual chars(normalized): {len(actual_norm)}",
        f"- Expected chars(tolerant): {len(expected_tolerant_norm)}",
        f"- Actual chars(tolerant): {len(actual_tolerant_norm)}",
        f"- Segments: {len(segments)}",
        "",
        "## 结论",
        "",
    ]
    lines.append("发布硬门槛以严格比较为准：`insert/delete = 0` 才能通过；等长 `replace` 只作为错别字或 ASR 错听候选进入人工复核。宽容比较仅用于辅助诊断，不能覆盖严格失败。")
    if publish_gate(strict_stats) == "fail_extra_or_missing":
        lines.append("当前不通过发布硬门槛：识别结果里仍存在多字或少字，需要换更高精度 ASR/人工听审/重新生成音频后再放行。")
    elif publish_gate(strict_stats) == "review_typo_only":
        lines.append("当前没有发现多字或少字，但存在替换字，需要人工确认是否只是错别字或 ASR 错听。")
    else:
        lines.append("当前通过发布硬门槛：未发现多字、少字或替换字。")
    lines.append("")
    if tolerant_similarity >= 0.92:
        lines.append("辅助判断：整体相似度较高，主要风险集中在多字/少字硬门槛。")
    elif tolerant_similarity >= 0.84:
        lines.append("辅助判断：整体存在中等差异，建议重点复核差异片段。")
    else:
        lines.append("辅助判断：整体差异较大，不建议继续使用该音频。")
    lines.append("")
    lines.append("说明：严格比较仅归一化布局、标点、大小写及约定的方括号控制标签，不使用词语别名。宽容比较还会替换常见错听并忽略部分口头词，因此不作为放行依据。不等长替换按每块长度差计入增删字；机器差异不能代替人工听审。")

    lines.extend(["", "## ASR 识别稿", "", transcript or "(empty)", "", "## 差异片段", ""])
    if not diffs:
        lines.append("未发现明显差异。")
    else:
        lines.append("| # | Type | Expected | Actual |")
        lines.append("|---:|---|---|---|")
        for idx, chunk in enumerate(diffs, 1):
            exp = chunk.expected[:80] if chunk.expected else ""
            act = chunk.actual[:80] if chunk.actual else ""
            lines.append(f"| {idx} | {chunk.tag} | {exp} | {act} |")

    lines.extend(["", "## 分段识别", "", "| # | Start | End | Text |", "|---:|---:|---:|---|"])
    for idx, row in enumerate(segments, 1):
        lines.append(f"| {idx} | {row['start']:.3f} | {row['end']:.3f} | {row['text']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--engine", choices=["faster-whisper", "sensevoice"], default="faster-whisper")
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    expected_text = load_expected(args.expected)
    if args.engine == "sensevoice":
        transcript, segments = transcribe_sensevoice(args.audio, args.model, args.language)
    else:
        transcript, segments = transcribe_faster_whisper(
            args.audio,
            args.model,
            args.language,
            local_files_only=not args.allow_download,
        )
    expected_norm = normalize_for_compare(expected_text)
    actual_norm = normalize_for_compare(transcript)
    similarity = ratio(expected_norm, actual_norm)
    expected_tolerant_norm = normalize_for_compare(expected_text, tolerant=True)
    actual_tolerant_norm = normalize_for_compare(transcript, tolerant=True)
    tolerant_similarity = ratio(expected_tolerant_norm, actual_tolerant_norm)
    strict_stats = edit_stats(expected_norm, actual_norm)
    tolerant_stats = edit_stats(expected_tolerant_norm, actual_tolerant_norm)
    diffs = make_diff(expected_norm, actual_norm)

    stem = args.audio.stem
    txt_path = args.out_dir / f"{stem}.asr.txt"
    json_path = args.out_dir / f"{stem}.asr_compare.json"
    md_path = args.out_dir / f"{stem}.asr_compare.md"
    txt_path.write_text(transcript + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "audio": str(args.audio),
                "expected": str(args.expected),
                "engine": args.engine,
                "model": args.model,
                "similarity": similarity,
                "tolerant_similarity": tolerant_similarity,
                "risk": risk_level(tolerant_similarity),
                "publish_gate": publish_gate(strict_stats),
                "publish_gate_strict": publish_gate(strict_stats),
                "publish_gate_tolerant": publish_gate(tolerant_stats),
                "strict_edit_stats": asdict(strict_stats),
                "tolerant_edit_stats": asdict(tolerant_stats),
                "segments": segments,
                "diffs": [asdict(item) for item in diffs],
                "expected_normalized": expected_norm,
                "actual_normalized": actual_norm,
                "expected_tolerant_normalized": expected_tolerant_norm,
                "actual_tolerant_normalized": actual_tolerant_norm,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(
        render_report(
            args.audio,
            args.expected,
            transcript,
            segments,
            expected_text,
            similarity,
            tolerant_similarity,
            diffs,
            strict_stats,
            tolerant_stats,
            args.engine,
            args.model,
        ),
        encoding="utf-8",
    )
    print(f"TXT={txt_path}")
    print(f"JSON={json_path}")
    print(f"MD={md_path}")
    print(f"SIMILARITY={similarity:.4f}")
    print(f"TOLERANT_SIMILARITY={tolerant_similarity:.4f}")
    print(f"RISK={risk_level(tolerant_similarity)}")
    print(f"PUBLISH_GATE={publish_gate(strict_stats)}")
    print(f"PUBLISH_GATE_STRICT={publish_gate(strict_stats)}")
    print(f"PUBLISH_GATE_TOLERANT={publish_gate(tolerant_stats)}")
    print(f"STRICT_INSERTED={strict_stats.inserted_chars}")
    print(f"STRICT_DELETED={strict_stats.deleted_chars}")
    print(f"TOLERANT_INSERTED={tolerant_stats.inserted_chars}")
    print(f"TOLERANT_DELETED={tolerant_stats.deleted_chars}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
