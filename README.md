# AI Media Content Pipeline

一套面向 AI 知识类短视频账号的可复现内容流水线：从公开热点源发现选题、评分与去重，生成带证据线索的内容包，再记录发布反馈，为下一轮选题提供数据。

项目刻意把“选题与内容包”放在视频渲染之前。输出是可检查的 JSON 和 Markdown，不会自动发布内容，也不会绕过人工事实核验。

## 主要能力

- 从公开热榜、GitHub Search 和 Hacker News 汇总候选选题。
- 按 AI 相关性、受众相关性、冲突性、视觉证据、格式适配和时效性评分。
- 生成候选清单、主选题内容包和机器可读运行日志。
- 用 CSV 记录播放、互动、完播率和复盘笔记。
- 可选接入 ChatTTS 或本地 GPT-SoVITS 服务生成分段旁白。
- 用 ASR 对照原稿，按插入/删除数量执行发布硬门槛。

## 前置条件

核心选题流水线只需要：

- Python 3.10+
- 可访问配置中公开数据源的网络连接

可选能力需要额外依赖：

- `faster-whisper` 或 SenseVoice：ASR 对照
- `numpy`、`soundfile`、`torch`、`ChatTTS`：ChatTTS 分段配音
- 本地运行的 GPT-SoVITS `/tts` 服务，以及 `numpy`、`soundfile`：GPT-SoVITS 配音
- FFmpeg：音频转码或后续视频制作

核心流水线不需要 API key。公开接口可能限流或临时不可用；错误会写入运行日志，不能把抓取结果直接当作已核实事实。

## 快速开始

```powershell
python scripts\run_daily_pipeline.py --config config\ai_niche.json --top 20
```

输出写入：

```text
runs/YYYY-MM-DD/
  topics.json
  shortlist.md
  content_pack.md
  run_log.json
```

发布后记录反馈：

```powershell
python scripts\record_feedback.py `
  --date 2026-08-27 `
  --topic "Example AI workflow topic" `
  --video "outputs/example.mp4" `
  --views 10000 --likes 500 --comments 80 --saves 120 --shares 60 `
  --three-sec 0.72 --completion 0.38 `
  --notes "Strong opening; simplify the middle section"
```

检测旁白是否忠于原稿：

```powershell
python scripts\asr_compare.py `
  --engine faster-whisper --model small `
  --audio media\narration.wav `
  --expected examples\voiceover.json `
  --out-dir runs\asr-review
```

发布硬门槛是 `insert/delete = 0`：相似度高但出现多字或少字时仍然阻断，最后还需要人工听审。

最终判定以**严格比较**为准：JSON 的 `publish_gate` 与终端的 `PUBLISH_GATE` 是统一入口，原有 `publish_gate_strict` 和 `publish_gate_tolerant` 字段仍保留。宽容比较会替换错听词、忽略“然后”等口头词，只能辅助定位问题，不能把严格失败改成通过。不等长替换按每个替换块的长度差计入增删字，不跨块抵消；等长替换仍需人工复核，不代表文本正确。

进程退出码为 0 只表示报告生成成功，不代表旁白通过校验。严格比较会忽略布局、标点、大小写和约定的方括号控制标签；逐字语义与真实发音仍应人工核对。

## 配置

编辑 `config/ai_niche.json` 可调整：

- 账号定位与目标受众
- 热榜、GitHub 和 Hacker News 数据源
- 关键词组
- 六项评分权重
- 目标视频时长与视觉语言

`config/gpt_sovits_voice.json` 是安全的本地服务示例。使用前把 `ref_audio_path` 改成你有权使用的参考音频，并确认本地 GPT-SoVITS 服务地址。

## 目录结构

```text
config/       选题、声音与配音参数
docs/         系统蓝图、运行节奏和语音接入说明
examples/     可直接复制修改的旁白输入
scripts/      选题、反馈、TTS 与 ASR 工具
templates/    内容包和反馈模板
tests/        不访问网络的核心逻辑测试
runs/         运行时生成，默认不提交
```

## 验证

```powershell
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
python scripts\run_daily_pipeline.py --config config\ai_niche.json --date 2099-01-01 --top 5
```

最后一条是联网烟雾测试。公开数据源失败时要检查 `runs/2099-01-01/run_log.json`，不能仅凭进程退出码判断所有来源都正常。

离线回归覆盖不等长替换、不同替换块的增删字不能抵消、宽容匹配不能覆盖严格失败，以及模拟转录下 JSON／终端／报告判定一致；不会下载模型或调用真实语音服务。

## 已知限制

- 热度分是启发式排序，不代表真实传播量或商业价值。
- 数据源结构变化可能导致解析失败。
- GitHub Search 未认证请求受较低限流约束。
- 内容包只提供研究起点；发布前必须打开原始来源并复核日期、主体和上下文。
- TTS 和 ASR 模型需要用户自行安装，本仓库不包含模型或声音样本。
- 项目不执行平台登录、自动发布或抓取私人账号数据。

## 来源与公开快照

该流水线来自 2026-06-11 至 2026-06-13 的 Codex 项目工作，并在 2026-08-27 制作公开快照。公开副本删除了历史运行输出、本机路径和声音样本，只保留可复现的代码、配置、文档与模板。

`docs/github-references.md` 记录了架构层面的公开项目启发。仓库没有复制这些项目的代码。

## 许可证

本仓库当前没有附加开源许可证。公开可见不等于授予复制、修改或再分发权；如需开放授权，应由仓库所有者另行选择并添加许可证。
