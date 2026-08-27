#!/usr/bin/env python3
"""Generate ChatTTS narration with per-line voice direction.

Input formats:

1. JSON list:
   [{"text": "...", "style": "hook"}, ...]

2. Plain text:
   [hook] 你以为，AI Agent 只是一个更聪明的聊天机器人？
   [short] 不。
   Lines without a marker use the default style.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import ChatTTS
import numpy as np
import soundfile as sf
import torch


@dataclass
class Segment:
    text: str
    style: str


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_segments(path: Path, default_style: str) -> list[Segment]:
    raw = path.read_text(encoding="utf-8").replace("\ufeff", "").strip()
    if not raw:
        return []
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        return [Segment(text=str(item["text"]).strip(), style=str(item.get("style", default_style))) for item in data]

    segments: list[Segment] = []
    marker = re.compile(r"^\[(?P<style>[a-zA-Z0-9_-]+)\]\s*(?P<text>.+)$")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        match = marker.match(line)
        if match:
            segments.append(Segment(text=match.group("text").strip(), style=match.group("style").strip()))
        else:
            segments.append(Segment(text=line, style=default_style))
    return segments


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def cache_key(text: str, style: str, style_config: dict, seed: int) -> str:
    payload = json.dumps(
        {"text": text, "style": style, "style_config": style_config, "seed": seed},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def normalize_peak(wav: np.ndarray, peak: float) -> np.ndarray:
    max_abs = float(np.max(np.abs(wav))) if wav.size else 0.0
    if max_abs > 0:
        wav = wav / max_abs * peak
    return wav.astype(np.float32)


def make_params(ChatTTS_module, speaker, style_config: dict, seed: int):
    params_refine = ChatTTS_module.Chat.RefineTextParams(
        prompt=style_config["refine_prompt"],
        temperature=float(style_config.get("temperature", 0.24)),
        top_P=float(style_config.get("top_P", 0.65)),
        top_K=int(style_config.get("top_K", 20)),
        manual_seed=seed,
        show_tqdm=False,
    )
    params_code = ChatTTS_module.Chat.InferCodeParams(
        prompt=style_config["infer_prompt"],
        spk_emb=speaker,
        temperature=float(style_config.get("temperature", 0.24)),
        top_P=float(style_config.get("top_P", 0.65)),
        top_K=int(style_config.get("top_K", 20)),
        manual_seed=seed,
        show_tqdm=False,
    )
    return params_refine, params_code


def write_caption_js(path: Path, window_name: str, cues: list[dict]) -> None:
    lines = [f"window.{window_name} = ["]
    for cue in cues:
        lines.append(
            f"  {{ start: {cue['start']}, duration: {cue['duration']}, style: {js_string(cue['style'])}, text: {js_string(cue['text'])} }},"
        )
    lines.append("];")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(path: Path, segments: list[Segment], cues: list[dict], duration: float, config_path: Path) -> None:
    lines = [
        "# Voice Director Report",
        "",
        f"- Config: `{config_path}`",
        f"- Duration: {duration:.3f}s",
        f"- Segments: {len(segments)}",
        "",
        "| # | Style | Start | Duration | Text |",
        "|---:|---|---:|---:|---|",
    ]
    for idx, cue in enumerate(cues, 1):
        lines.append(f"| {idx} | {cue['style']} | {cue['start']:.3f} | {cue['duration']:.3f} | {cue['text']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--config", type=Path, default=Path("../config/voice_director.json"))
    parser.add_argument("--out-wav", type=Path, default=Path("narration_directed.wav"))
    parser.add_argument("--out-js", type=Path, default=Path("captions_directed.js"))
    parser.add_argument("--out-report", type=Path, default=Path("voice_director_report.md"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".voice_cache"))
    parser.add_argument("--default-style", default="explain")
    args = parser.parse_args()

    config = load_config(args.config)
    sample_rate = int(config.get("sample_rate", 24000))
    seed = int(config.get("seed", 3179))
    peak = float(config.get("peak", 0.82))
    window_name = str(config.get("caption_window", "CAPTIONS_V3"))
    styles = config["styles"]
    segments = load_segments(args.input, args.default_style)
    if not segments:
        raise SystemExit("no segments")

    unknown = sorted({seg.style for seg in segments if seg.style not in styles})
    if unknown:
        raise SystemExit(f"unknown style(s): {', '.join(unknown)}")

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"segments={len(segments)}")

    chat = ChatTTS.Chat()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device={device}")
    chat.load(source="huggingface", compile=False, device=device)

    torch.manual_seed(int(config.get("speaker_seed", seed)))
    speaker = chat.sample_random_speaker()

    pieces: list[np.ndarray] = []
    cues: list[dict] = []
    cursor = 0.0

    for index, segment in enumerate(segments, 1):
        style_config = styles[segment.style]
        key = cache_key(segment.text, segment.style, style_config, seed)
        chunk_path = args.cache_dir / f"{index:03d}_{segment.style}_{key}.wav"
        print(f"[{index:02d}/{len(segments):02d}] {segment.style}: {segment.text[:36]}")

        if chunk_path.exists() and chunk_path.stat().st_size > 1024:
            wav, sr = sf.read(chunk_path, dtype="float32")
            if sr != sample_rate:
                raise RuntimeError(f"cache sample rate mismatch: {chunk_path}")
        else:
            params_refine, params_code = make_params(ChatTTS, speaker, style_config, seed)
            wavs = chat.infer(
                [segment.text],
                skip_refine_text=bool(style_config.get("skip_refine_text", False)),
                params_refine_text=params_refine,
                params_infer_code=params_code,
                split_text=False,
            )
            wav = np.asarray(wavs[0], dtype=np.float32)
            wav = normalize_peak(wav, peak)
            sf.write(chunk_path, wav, sample_rate)

        duration = wav.size / sample_rate
        caption_duration = max(
            float(style_config.get("caption_min_duration", 1.0)),
            duration + float(style_config.get("caption_extra", 0.08)),
        )
        cues.append(
            {
                "start": round(cursor, 3),
                "duration": round(caption_duration, 3),
                "text": segment.text,
                "style": segment.style,
            }
        )
        pieces.append(wav)
        cursor += duration

        pause_after = float(style_config.get("pause_after", 0.14))
        if pause_after > 0:
            silence = np.zeros(int(sample_rate * pause_after), dtype=np.float32)
            pieces.append(silence)
            cursor += pause_after

    audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
    sf.write(args.out_wav, audio, sample_rate)
    write_caption_js(args.out_js, window_name, cues)
    write_report(args.out_report, segments, cues, audio.size / sample_rate, args.config)

    print(f"wrote={args.out_wav} duration={audio.size / sample_rate:.3f}s")
    print(f"wrote={args.out_js}")
    print(f"wrote={args.out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
