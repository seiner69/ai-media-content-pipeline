#!/usr/bin/env python3
"""Generate narration through a running GPT-SoVITS API server.

Start GPT-SoVITS first, for example:

    python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml

Then run this script against a JSON voiceover file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import soundfile as sf


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

    marker = re.compile(r"^\[(?P<style>[a-zA-Z0-9_-]+)\]\s*(?P<text>.+)$")
    segments: list[Segment] = []
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


def nested_value(config: dict, key: str, style: str, fallback: float) -> float:
    values = config.get(key, {})
    if not isinstance(values, dict):
        return float(values)
    return float(values.get(style, values.get("default", fallback)))


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_caption_js(path: Path, window_name: str, cues: list[dict]) -> None:
    lines = [f"window.{window_name} = ["]
    for cue in cues:
        lines.append(
            f"  {{ start: {cue['start']}, duration: {cue['duration']}, style: {js_string(cue['style'])}, text: {js_string(cue['text'])} }},"
        )
    lines.append("];")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(path: Path, config_path: Path, cues: list[dict], duration: float) -> None:
    lines = [
        "# GPT-SoVITS Voice Report",
        "",
        f"- Config: `{config_path}`",
        f"- Duration: {duration:.3f}s",
        f"- Segments: {len(cues)}",
        "",
        "| # | Style | Start | Duration | Text |",
        "|---:|---|---:|---:|---|",
    ]
    for idx, cue in enumerate(cues, 1):
        lines.append(f"| {idx} | {cue['style']} | {cue['start']:.3f} | {cue['duration']:.3f} | {cue['text']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cache_key(segment: Segment, config: dict) -> str:
    relevant = {
        "text": segment.text,
        "style": segment.style,
        "api_url": config.get("api_url"),
        "text_lang": config.get("text_lang"),
        "prompt_lang": config.get("prompt_lang"),
        "ref_audio_path": config.get("ref_audio_path"),
        "prompt_text": config.get("prompt_text"),
        "speed_factor": config.get("speed_factor"),
        "fragment_interval": config.get("fragment_interval"),
        "seed": config.get("seed"),
        "top_k": config.get("top_k"),
        "top_p": config.get("top_p"),
        "temperature": config.get("temperature"),
    }
    payload = json.dumps(relevant, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def request_tts(segment: Segment, config: dict, timeout: int) -> bytes:
    payload = {
        "text": segment.text,
        "text_lang": config.get("text_lang", "zh"),
        "ref_audio_path": config["ref_audio_path"],
        "prompt_text": config.get("prompt_text", ""),
        "prompt_lang": config.get("prompt_lang", "zh"),
        "top_k": int(config.get("top_k", 15)),
        "top_p": float(config.get("top_p", 1.0)),
        "temperature": float(config.get("temperature", 1.0)),
        "text_split_method": config.get("text_split_method", "cut5"),
        "batch_size": int(config.get("batch_size", 1)),
        "speed_factor": float(config.get("speed_factor", 1.0)),
        "fragment_interval": float(config.get("fragment_interval", 0.3)),
        "seed": int(config.get("seed", -1)),
        "media_type": config.get("media_type", "wav"),
        "streaming_mode": False,
        "parallel_infer": bool(config.get("parallel_infer", True)),
        "repetition_penalty": float(config.get("repetition_penalty", 1.35)),
        "sample_steps": int(config.get("sample_steps", 32)),
        "super_sampling": bool(config.get("super_sampling", False)),
    }
    if config.get("aux_ref_audio_paths"):
        payload["aux_ref_audio_paths"] = config["aux_ref_audio_paths"]

    req = Request(
        str(config["api_url"]),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GPT-SoVITS HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"GPT-SoVITS API unavailable: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--config", type=Path, default=Path("../config/gpt_sovits_voice.json"))
    parser.add_argument("--out-wav", type=Path, default=Path("narration_gpt_sovits.wav"))
    parser.add_argument("--out-js", type=Path, default=Path("captions_gpt_sovits.js"))
    parser.add_argument("--out-report", type=Path, default=Path("voice_gpt_sovits_report.md"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".gpt_sovits_cache"))
    parser.add_argument("--default-style", default="explain")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--speed-factor", type=float, default=None)
    parser.add_argument("--pause-scale", type=float, default=1.0)
    args = parser.parse_args()

    config = load_config(args.config)
    if args.speed_factor is not None:
        config["speed_factor"] = args.speed_factor
    segments = load_segments(args.input, args.default_style)
    if not segments:
        raise SystemExit("no segments")
    ref_audio = Path(str(config["ref_audio_path"]))
    if not ref_audio.exists():
        raise SystemExit(f"missing ref_audio_path: {ref_audio}")

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    pieces: list[np.ndarray] = []
    cues: list[dict] = []
    cursor = 0.0
    sample_rate: int | None = None
    window_name = str(config.get("caption_window", "CAPTIONS_V3"))

    for index, segment in enumerate(segments, 1):
        key = cache_key(segment, config)
        chunk_path = args.cache_dir / f"{index:03d}_{segment.style}_{key}.wav"
        print(f"[{index:02d}/{len(segments):02d}] {segment.style}: {segment.text[:48]}")
        if not chunk_path.exists():
            audio_bytes = request_tts(segment, config, args.timeout)
            chunk_path.write_bytes(audio_bytes)
            time.sleep(0.05)

        wav, sr = sf.read(chunk_path, dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        if sample_rate is None:
            sample_rate = int(sr)
        elif int(sr) != sample_rate:
            raise RuntimeError(f"sample rate mismatch: {chunk_path}={sr}, expected={sample_rate}")

        duration = wav.size / sample_rate
        caption_duration = max(
            nested_value(config, "caption_min_duration", segment.style, 1.0),
            duration + nested_value(config, "caption_extra", segment.style, 0.1),
        )
        cues.append(
            {
                "start": round(cursor, 3),
                "duration": round(caption_duration, 3),
                "style": segment.style,
                "text": segment.text,
            }
        )
        pieces.append(wav)
        cursor += duration

        pause_after = nested_value(config, "pause_after", segment.style, 0.18) * max(args.pause_scale, 0.0)
        if pause_after > 0:
            pieces.append(np.zeros(int(sample_rate * pause_after), dtype=np.float32))
            cursor += pause_after

    if sample_rate is None:
        raise SystemExit("no audio")

    audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
    sf.write(args.out_wav, audio, sample_rate)
    write_caption_js(args.out_js, window_name, cues)
    write_report(args.out_report, args.config, cues, audio.size / sample_rate)
    print(f"wrote={args.out_wav} duration={audio.size / sample_rate:.3f}s")
    print(f"wrote={args.out_js}")
    print(f"wrote={args.out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
