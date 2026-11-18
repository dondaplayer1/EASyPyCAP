# EASyPyCAP

## About

EASyPyCAP relays alerts from FEMA's IPAWS feed to EASyPLUS-family EAS encoders over the network. Each encoder can subscribe to its own counties and event codes. The relay uses the audio attached to the alert when available and can fall back to text-to-speech.

At startup, it skips alerts that are already in the feed. It only forwards active alerts with CAP status `Actual` that are eligible for EAS broadcast.

## Setup

- Python 3.10 or newer.
- FFmpeg on your PATH if you need to convert audio such as MP3.
- For Google text-to-speech, install gTTS with `python -m pip install -r requirements.txt`.

## Configuration

Edit the JSON files in the project folder. Use `--config-dir path/to/config` to load them from another folder.

### `config.json`

```json
{
    "callsign": "EASyPy",
    "tts": false
}
```

- `callsign` is the source label shown on the encoder. Use 1–8 printable ASCII characters, excluding `+` and `-`. It defaults to `CAP`.
- Set `tts` to `"gtts"` to generate audio when IPAWS audio is missing or unusable. Use `false` to turn it off. This file is optional.

### `sources.json`

```json
{
    "sources": {
        "ipaws": {
            "IPAWS": {
                "enabled": true,
                "poll_dur": 15,
                "url": "https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/feed"
            }
        }
    }
}
```

Each entry under `sources.ipaws` needs a feed `url`. Set `poll_dur` to the time between polls in seconds (default 60). Set `enabled` to `false` to skip a feed. Keep at least one feed enabled.

### `encoders.json`

```json
{
    "encoders": {
        "Studio": {
            "enabled": false,
            "ip": "192.0.2.10",
            "password": "your-encoder-password",
            "command_port": 59911,
            "audio_port": 59919,
            "counties": ["026073"],
            "events": ["TOR", "SVR"]
        }
    }
}
```

- Replace the example IP and password with your encoder's settings. Set `enabled` to `true` to use the entry. The default TCP ports are `59911` for commands and `59919` for audio.
- Use six-digit SAME codes in `counties` and three-character SAME event codes in `events`. Keep county codes in quotes to preserve leading zeros. An alert must match both lists. Each list defaults to `["*"]`, which accepts all values for that filter.

## Running

```sh
python main.py --dry-run
```

Dry run polls your feeds and logs what it would send without contacting the encoders. To start sending alerts, run `python main.py`. Press Ctrl+C to stop.

See [the docs](docs/README.md) for more on alert filtering, audio, and the encoder protocol.
