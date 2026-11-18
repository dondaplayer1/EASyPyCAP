# `main.py`

`main.py` is the entry point. It loads the config files, starts one `IpawsPoller` thread for each enabled source, and relays new alerts to the encoders that are subscribed to them.

```powershell
python main.py             # run until Ctrl+C
python main.py --dry-run   # log what would be sent; don't contact any encoder
```

`--config-dir DIR` reads the JSON files from another folder. By default they are read from the project root.

## Config files

**`config.json`** is optional.

- `callsign` is the source label shown on the encoder. It must be 1–8 characters, with no `-` or `+`.
- `tts` picks the text-to-speech engine: `"gtts"`, or `false` to turn TTS off. [tts_man](tts_man.md) reads it every time audio is needed, so you can change it while `main.py` is running.

**`sources.json`**: every enabled entry under `"ipaws"` gets a poller thread. That thread checks `url` every `poll_dur` seconds; the default is 60.

**`encoders.json`**: every enabled encoder is a possible destination.

| Key | Meaning |
|---|---|
| `ip`, `password` | Required. |
| `command_port`, `audio_port` | Optional. Default to 59911 and 59919. |
| `counties` | SAME codes this encoder is subscribed to, or `*` for all. |
| `events` | Event codes this encoder is subscribed to, or `*` for all. |

## What happens when an alert comes in (`Relay.on_alert`)

1. An `ALERT` line is logged.
2. The alert is skipped if any of these is true:
   - its CAP status is not `Actual`
   - IPAWS marked it `BLOCKCHANNEL=EAS`
   - it has already expired
3. Each enabled encoder is checked in turn. If it is subscribed to the alert's event, and one of its `counties` covers one of the alert's locations, the alert is sent to it.
4. The same alert, identified by sender, identifier and sent time, is never sent twice to the same encoder. This holds even when it arrives from two sources, such as IPAWS and the TDL.

### Zone matching (`zone_matches`)

Zone codes have the form `PSSCCC`.

- `*` or `000000` matches everything.
- The state digits (`SS`) must be equal.
- The counties (`CCC`) must be equal, unless either side is `000`. A statewide subscription receives every county in that state, and a county subscription also receives statewide alerts.
- The subdivision digit (`P`) is ignored, so `026073` also matches `126073`.

### Audio

Audio is worked out **once per alert**, and only if at least one encoder is going to receive it. All matching encoders then get the same audio. English and Spanish are handled separately:

1. **IPAWS audio.** If the CAP `<info>` block for that language has an audio `<resource>`, it is used. The resource can be embedded as base64 (`<derefUri>`) or linked by an http(s) `<uri>`. It is converted with [audio.to_audio](audio.md).
2. **TTS.** If there is no IPAWS audio, or it can't be downloaded or converted, `tts_man.synthesize()` speaks the alert text (headline, description and instruction).
3. **Text only.** If TTS is off, the alert is sent without audio for that language. If TTS fails, a warning is logged first.

The startup log shows `TTS: gtts` or `TTS: off`. It also warns if ffmpeg is missing.

### Sending

- `prepare_alert` builds the protocol alert, using `callsign` as the source label and adding the English and Spanish audio.
- `EasyPlusClient.deliver` sends it.
- Only one delivery to a given encoder runs at a time.
- A failed delivery is logged as an error and is **not** retried. If the encoder had already accepted the alert, a retry could make it air twice.

## Logs

Each line looks like `22:11:14 | ALERT    | [MAIN] TOR Tornado Warning - Isabella [IPAWS, Actual]`. The tag in brackets is the source or encoder name, or `MAIN`. The whole line is colored by level:

| Level | Color | Meaning |
|---|---|---|
| INFO | green | Normal operation, including "Encoder accepted ..." |
| ALERT | magenta | A new alert came in |
| WARNING | yellow | Something to look at |
| ERROR | red | A delivery failed |

Color turns off when output is not a terminal, or when the `NO_COLOR` environment variable is set.
