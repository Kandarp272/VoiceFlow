# VoiceFlow 🎙

**Offline-first AI voice dictation for any app — browser, IDE, Word, Slack, anywhere.**

Press a hotkey. Speak. Your words appear wherever your cursor is — instantly, privately, offline.

[![CI](https://github.com/yourusername/voiceflow/actions/workflows/ci.yml/badge.svg)](https://github.com/yourusername/voiceflow/actions)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)]()

---

## ✨ Features

| Feature | Details |
|---------|---------|
| 🔒 **100% Offline** | Runs entirely on your machine with faster-whisper |
| ⚡ **Any App** | Browser, IDEs, Word, Slack, Discord, Notion — anywhere |
| 🌐 **NVIDIA NIM** | Optional cloud ASR via Parakeet-TDT or Canary |
| 🔄 **Auto-fallback** | NIM fails → silently switches to local |
| 🎨 **Animated Orb** | Beautiful floating orb shows recording state |
| ⌨️ **Hotkeys** | Global system-wide hotkeys — works in any active window |
| 🤖 **AI Polish** | Optional LLM cleanup via Ollama / OpenRouter / NIM |
| 🗣️ **Voice Commands** | "new line", "period", "delete that", "cancel" |
| 🏎️ **Fast** | < 1.5s latency on CPU with the `small` model |
| 🆓 **Free** | No subscriptions, no usage limits, no data harvesting |

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/voiceflow.git
cd voiceflow
python install.py
```

The installer will:
- Install all dependencies
- Let you pick a Whisper model (recommended: `small`)
- Download the model (~466 MB)
- Create a `config.yaml` and launch script

### 2. Start VoiceFlow

```bash
# Windows
VoiceFlow.bat            # with console
VoiceFlow_silent.vbs     # no console window

# Linux / macOS
./voiceflow.sh

# Any platform
python main.py
```

### 3. Dictate

1. Click into any text field (browser, IDE, Word, etc.)
2. Press **Alt + Space** to start recording
3. Speak naturally
4. Press **Alt + Space** again (or pause for 0.6s) — text appears at your cursor

---

## ⌨️ Hotkeys

| Hotkey | Action |
|--------|--------|
| `Alt + Space` | Toggle dictation on/off |
| `Alt + Shift + Space` | Push-to-talk (hold while speaking) |
| `Ctrl + Alt + B` | Cycle ASR backend (local → nim → auto) |
| `Ctrl + Alt + Q` | Quit VoiceFlow |

All hotkeys are configurable in `config.yaml`.

---

## 🗣️ Voice Commands

Say these phrases as standalone utterances to trigger formatting:

| Say | Result |
|-----|--------|
| `"new line"` | `↵` |
| `"new paragraph"` | `↵↵` |
| `"period"` / `"full stop"` | `.` |
| `"comma"` | `,` |
| `"exclamation"` | `!` |
| `"question mark"` | `?` |
| `"open paren"` | `(` |
| `"close paren"` | `)` |
| `"delete that"` | Undo last injection |
| `"cancel"` | Abort current dictation |

---

## 🤖 AI Backends

### Local (Offline) — faster-whisper

The default. Runs entirely on your CPU (or NVIDIA GPU if available).

```yaml
asr:
  backend: local
  local:
    model: small          # tiny | base | small | medium | large-v3
    compute_type: auto    # auto | int8 | float16 | float32
    device: auto          # auto | cpu | cuda
```

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| `tiny` | 75 MB | ⚡⚡⚡⚡ | ★★☆☆ |
| `base` | 145 MB | ⚡⚡⚡ | ★★★☆ |
| `small` | 466 MB | ⚡⚡⚡ | ★★★★ ← recommended |
| `medium` | 1.5 GB | ⚡⚡ | ★★★★ |
| `large-v3` | 3.1 GB | ⚡ | ★★★★★ |

### NVIDIA NIM

Uses NVIDIA's hosted Parakeet-TDT or Canary models. Requires an API key and internet.

```yaml
asr:
  backend: nim
  nim:
    api_key: "nvapi-..."          # get from build.nvidia.com
    model: nvidia/parakeet-tdt-1.1b
```

Get a free API key at [build.nvidia.com](https://build.nvidia.com).

Or set via environment variable:
```bash
export VOICEFLOW_NIM_API_KEY="nvapi-..."
```

### Self-Hosted NIM (RTX 3080+)

```bash
docker run --gpus all -p 9000:9000 \
  nvcr.io/nim/nvidia/parakeet-tdt-1.1b:latest
```

```yaml
asr:
  nim:
    endpoint: "http://localhost:9000"
    api_key: "any-string"
```

### Auto Mode

Tries local first, falls back to NIM on error. Shows a toast notification when switching.

```yaml
asr:
  backend: auto
```

---

## ✨ AI Polish (Optional)

Removes filler words and fixes grammar via an LLM.

```yaml
polish:
  enabled: true
  backend: ollama     # ollama | openrouter | nim
```

**Ollama (local, free):**
```bash
# Install Ollama from https://ollama.ai
ollama pull llama3.2
```

**OpenRouter (free tier):**
```yaml
polish:
  backend: openrouter
  openrouter:
    api_key: "sk-or-..."
    model: "qwen/qwen-2.5-7b-instruct:free"
```

**NVIDIA NIM:**
```yaml
polish:
  backend: nim
  nim:
    api_key: "nvapi-..."
    model: "meta/llama-3.1-8b-instruct"
```

---

## 🎨 Orb States

The floating orb shows what VoiceFlow is doing:

| State | Visual | Meaning |
|-------|--------|---------|
| Idle | Tiny grey dot | Ready, waiting |
| Listening | 🔴 Pulsing red orb | Recording your speech |
| Processing | 🔵 Spinning blue arc | Transcribing |
| Done | 🟢 Green flash | Text injected |
| Error | 🟠 Orange flash | Something went wrong |

**Drag** the orb to reposition it anywhere on screen.

---

## ⚙️ Configuration Reference

Full `config.yaml` with all options:

```yaml
asr:
  backend: local            # local | nim | auto
  local:
    model: small            # tiny | base | small | medium | large-v3
    compute_type: auto      # auto | int8 | float16 | float32
    device: auto            # auto | cpu | cuda
  nim:
    api_key: ""
    endpoint: "https://integrate.api.nvidia.com/v1"
    model: "nvidia/parakeet-tdt-1.1b"
    timeout: 10

hotkeys:
  toggle: "<alt>+<space>"
  push_to_talk: "<alt>+<shift>+<space>"
  switch_backend: "<ctrl>+<alt>+b"
  quit: "<ctrl>+<alt>+q"

injection:
  method: clipboard         # clipboard | type
  restore_clipboard: true
  paste_delay: 0.05

polish:
  enabled: false
  backend: ollama
  ollama:
    endpoint: "http://localhost:11434"
    model: "llama3.2"
  openrouter:
    api_key: ""
    model: "qwen/qwen-2.5-7b-instruct:free"
  nim:
    api_key: ""
    model: "meta/llama-3.1-8b-instruct"

ui:
  orb:
    size: 64
    position: bottom-right  # bottom-right | bottom-left | top-right | top-left
    margin: 24
    opacity: 0.95

audio:
  sample_rate: 16000
  chunk_ms: 30
  vad_aggressiveness: 2     # 0 (permissive) to 3 (strict)
  silence_duration: 0.6
  max_recording: 30
```

---

## 🏗️ Architecture

```
voiceflow/
├── main.py                 # Entry point
├── install.py              # One-command installer
├── config.yaml             # User configuration
├── requirements.txt
├── pyproject.toml
│
└── voiceflow/
    ├── core.py             # Central orchestrator
    │
    ├── config/
    │   └── settings.py     # Typed config loader
    │
    ├── audio/
    │   ├── capture.py      # Mic capture (sounddevice + WASAPI)
    │   └── vad.py          # Voice activity detection (webrtcvad)
    │
    ├── asr/
    │   ├── base.py         # Abstract ASR interface
    │   ├── local.py        # faster-whisper backend
    │   ├── nim.py          # NVIDIA NIM REST backend
    │   └── manager.py      # Backend selection + auto-fallback
    │
    ├── hotkeys/
    │   └── manager.py      # Global hotkey registration (pynput)
    │
    ├── inject/
    │   └── typer.py        # Text injection (clipboard + keyboard)
    │
    ├── ui/
    │   └── orb.py          # Animated floating orb (tkinter)
    │
    └── polish/
        └── llm.py          # LLM post-processing
```

### Data Flow

```
Hotkey press
    │
    ▼
AudioCapture (sounddevice WASAPI)
    │ 30ms chunks
    ▼
VADFilter (webrtcvad / energy)
    │ speech-gated PCM
    ▼
ASRManager ──── LocalASR (faster-whisper)
    │       └── NIMASR (NVIDIA NIM REST)
    │ text
    ▼
VoiceCommands (rule-based)
    │
    ▼
LLMPolish (optional: Ollama / OpenRouter / NIM)
    │
    ▼
TextTyper (clipboard paste → Ctrl+V in active window)
    │
    ▼
Text appears in browser / IDE / Word / Slack / anywhere ✓
```

---

## 📋 Requirements

- Python 3.9+
- Windows 10/11, Linux, or macOS
- Microphone
- ~500 MB disk space (for the `small` model)
- Internet connection only if using NVIDIA NIM backend

**Linux additional deps:**
```bash
sudo apt install portaudio19-dev python3-tk xdotool xclip
```

---

## 🔒 Privacy

- **Zero telemetry** — no usage data is ever sent anywhere
- **Audio never stored** — processed in-memory, discarded immediately
- **Local by default** — nothing leaves your machine unless you enable NIM
- **NIM mode** — audio is sent only to NVIDIA's API (under their privacy policy)
- **Open source** — audit the code yourself

---

## 🛠️ Development

```bash
# Clone
git clone https://github.com/yourusername/voiceflow.git
cd voiceflow

# Set up dev environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check .
black --check .

# Build standalone executable (Windows)
pip install pyinstaller
pyinstaller --onefile --windowed --name VoiceFlow main.py
```

---

## 🗺️ Roadmap

- [x] Local faster-whisper ASR
- [x] NVIDIA NIM ASR
- [x] Global hotkey dictation
- [x] Text injection (clipboard + keyboard)
- [x] Animated orb UI
- [x] Voice command layer
- [x] AI polish (Ollama / OpenRouter / NIM)
- [ ] Per-app injection overrides
- [ ] Real-time streaming ASR (word-by-word)
- [ ] Multi-language model auto-selection
- [ ] Dictation history & replay
- [ ] Custom vocabulary / hotwords
- [ ] One-click local NIM setup

---

## 📄 License

MIT — free for personal and commercial use. See [LICENSE](LICENSE).

---

## 🙏 Credits

Built on top of:
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 Whisper
- [pynput](https://github.com/moses-palmer/pynput) — global hotkeys
- [sounddevice](https://python-sounddevice.readthedocs.io/) — audio capture
- [NVIDIA NIM](https://build.nvidia.com/) — cloud ASR
- [webrtcvad](https://github.com/wiseman/py-webrtcvad) — voice activity detection
