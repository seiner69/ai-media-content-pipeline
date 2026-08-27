# GPT-SoVITS 接入方案

## 为什么换到 GPT-SoVITS

当前 ChatTTS 在发布级短视频口播里暴露了两个问题：

- 单字短句不稳定，例如 `不。` 会被吞掉。
- 开启文本 refine 后会口语化，可能多出 `感觉` 等原稿没有的字。

GPT-SoVITS 更适合做长期账号音色，因为它支持 5 秒参考音频 zero-shot，也支持 1 分钟数据 few-shot 微调。官方 README 说明它支持中文，并提供 WebUI、数据切片、ASR 标注、训练和推理工具。

官方仓库：[RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)

## 本项目落地方式

GPT-SoVITS 不直接写进 HyperFrames。它作为独立 TTS 服务运行：

```text
voiceover_directed_v5.json
  -> scripts/generate_gpt_sovits_tts.py
  -> GPT-SoVITS /tts API
  -> narration_gpt_sovits.wav + captions_gpt_sovits.js
  -> HyperFrames render
  -> ASR hard gate + 人工听审
```

## 已创建文件

- `config/gpt_sovits_voice.json`：GPT-SoVITS API、参考音频、生成参数。
- `scripts/generate_gpt_sovits_tts.py`：逐段调用 GPT-SoVITS API，拼接音频并生成字幕时间轴。
- `media/reference.wav`：用户自行准备、具有使用权的参考音频（不随仓库提供）。

## 安装 GPT-SoVITS

官方 Windows 推荐两条路。

### 路线 A：整合包

官方 README 推荐 Windows 用户下载整合包，然后双击 `go-webui.bat` 启动。这个最省事，适合先跑通。

### 路线 B：源码安装

官方 README 给出的 Windows 命令：

```powershell
conda create -n GPTSoVits python=3.10
conda activate GPTSoVits
pwsh -F install.ps1 --Device <CU126|CU128|CPU> --Source <HF|HF-Mirror|ModelScope> [--DownloadUVR5]
```

先根据自己的显卡、显存和驱动选择匹配的 CUDA 版本；不确定时可用 CPU/整合包验证，不建议一开始就做重训练。

## 启动 API

在 GPT-SoVITS 根目录启动：

```powershell
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

官方 `api_v2.py` 的 `/tts` 接口支持：

- `text`
- `text_lang`
- `ref_audio_path`
- `prompt_text`
- `prompt_lang`
- `speed_factor`
- `fragment_interval`
- `seed`
- `media_type`

## 生成本视频旁白

GPT-SoVITS API 启动后，在本项目执行：

```powershell
cd path\to\ai-media-content-pipeline
python scripts\generate_gpt_sovits_tts.py examples\voiceover.json --config config\gpt_sovits_voice.json --out-wav runs\narration_gpt_sovits.wav --out-js runs\captions_gpt_sovits.js --out-report runs\voice_gpt_sovits_report.md
ffmpeg -y -i runs\narration_gpt_sovits.wav -codec:a libmp3lame -b:a 192k runs\narration_gpt_sovits.mp3
```

然后把 `index.html` 里的引用切到：

```html
<script src="captions_gpt_sovits.js"></script>
<audio id="narration" data-start="0" data-track-index="30" src="narration_gpt_sovits.mp3" data-volume="1"></audio>
```

## 质检硬门槛

生成后必须跑：

```powershell
python scripts\asr_compare.py --audio runs\narration_gpt_sovits.mp3 --expected examples\voiceover.json --out-dir runs\asr_gpt_sovits --model tiny
```

注意：本机 `faster-whisper tiny` 只作为拦截器，不作为最终放行器。发布前对所有 `short` segment 强制人工听审，尤其是：

- `不。`
- `而是三件事。`
- `工具会一直变。`

## 后续升级

跑通 zero-shot 后，再准备 1-3 分钟稳定音色样本做 few-shot 微调，让账号声音统一。微调前先固定脚本风格和口播节奏，否则声音稳定了，内容节奏仍然会漂。
