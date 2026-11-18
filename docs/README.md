# EASyPyCAP documentation

EASyPyCAP relays CAP (Common Alerting Protocol) alerts from IPAWS to EASyPLUS-family EAS encoders over the network. It uses only the Python standard library and needs Python 3.10 or newer.

## Contents

| Doc | Covers |
|---|---|
| [main.md](main.md) | **Start here.** `main.py`: config files, how alerts are matched to encoders, logs. |
| [ipaws.md](ipaws.md) | The IPAWS feed poller thread. |
| [tts_man.md](tts_man.md) | Text-to-speech manager. Explains how to add a TTS engine. |
| [audio.md](audio.md) | Converts IPAWS and TTS audio into the encoder's format. |
| [cap_alert.md](cap_alert.md) | Reading CAP XML and turning it into an EASyPLUS `Alert`. Builds the SAME header. |
| [easyplus_protocol.md](easyplus_protocol.md) | The TCP client: login, sending the alert, uploading audio, EOM, logoff. |
| [easyplus_cmd.md](easyplus_cmd.md) | Command packet framing and checksums. |
| [easy_crypto.md](easy_crypto.md) | Password obfuscation used at login. |

`easyplus_protocol`, `easyplus_cmd` and `easy_crypto` are ports of the original appliance code. **Leave them as they are**, because their byte layouts must match what the encoder expects. `cap_alert`, `ipaws`, `audio`, `tts_man` and `main.py` are the project's own code and can be changed freely.

## How the pieces fit

```
 main.py  (reads config.json, encoders.json, sources.json)
   │
   ├── IpawsPoller thread per source ── polls feed every poll_dur s
   │        │ new CAP XML ─► cap_alert.parse_cap ─► alert dict
   │        ▼
   └── Relay.on_alert ── check each encoder's counties/events
            │ match ─► audio: IPAWS <resource> ─► else tts_man ─► else none
            │       ─► cap_alert.prepare_alert ─► EasyPlusClient.deliver
            ▼
        EASyPLUS  :59911 commands, :59919 audio
```

## Repository layout

| Path | Purpose |
|---|---|
| `main.py` | Runs everything. See [main.md](main.md). |
| `modules/` | `ipaws.py`, `cap_alert.py`, `audio.py`, `tts_man.py`, and the EASyPLUS protocol modules. |
| `config.json` | `callsign` and `tts` (`"gtts"` or `false`). |
| `encoders.json` | Encoders: IP, ports, password, subscribed counties and events. |
| `sources.json` | IPAWS feeds, each with its `poll_dur`. |
| `requirements.txt` | Optional Python packages (gTTS). |

## Requirements

- Python 3.10 or newer.
- **ffmpeg** on PATH. It is needed to convert MP3 audio (from IPAWS or gTTS) and any WAV that isn't already 8 kHz mono 16-bit.
- **gTTS** (`pip install -r requirements.txt`), only if `config.json` has `"tts": "gtts"`.

## Quick start

```powershell
python main.py --dry-run     # watch the feeds without contacting encoders
python main.py               # run for real
```
