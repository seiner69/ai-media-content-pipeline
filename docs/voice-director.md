# 配音导演模块

TTS 不直接读“阅读版文案”，而是读带语气标注的“播音版脚本”。

## 核心步骤

1. 把长文案改成短句。
2. 给每句标注 `style`。
3. 根据 `style` 使用不同 ChatTTS 参数、停顿和字幕时长。
4. 输出音频、字幕 JS、配音报告。
5. 视频页面按新字幕时间轴同步。

## Style

- `hook`：开头钩子，稍慢，压住反差。
- `short`：极短判断句，干脆，有留白。
- `explain`：解释句，稳定、略快。
- `emphasis`：关键判断，略慢，重读。
- `list`：列举句，短促清楚，方便和卡片同步。
- `ending`：结尾金句，慢一点，收束。

## 使用

```powershell
python ..\ai-media-system\scripts\generate_directed_chattts.py voiceover_directed.json --config ..\ai-media-system\config\voice_director.json --out-wav narration_v3.wav --out-js captions_v3.js --out-report voice_director_report.md
ffmpeg -y -i narration_v3.wav -codec:a libmp3lame -b:a 192k narration_v3.mp3
```

## 原则

- 英文尽量屏幕显示，旁白中文解释。
- 强判断句单独成句。
- 不是全局加速，而是钩子慢、解释快、结尾慢。
- 每次改文案后都重新生成字幕时间轴。
