# `modules/audio.py`

`audio.py` converts audio from any source into the format the EASyPLUS accepts: **8000 Hz, mono, 16-bit PCM, at most 120 seconds**.

| Function | What it does |
|---|---|
| `to_audio(data)` | Takes audio bytes and returns an `easyplus_protocol.Audio`. A WAV that is already 8 kHz mono 16-bit is used directly. Everything else (MP3, 44.1 kHz, stereo, …) is converted through `ffmpeg`, and anything past 120 seconds is cut off. Raises `AudioError` if ffmpeg is missing or can't read the data. |
| `resource_bytes(resource, timeout=30)` | Gets the bytes of a CAP audio resource dict from `cap_alert`. If the audio is embedded as base64 (`deref`), it is decoded. Otherwise it is downloaded from `uri`, which must be **http or https**; other schemes such as `file://` are refused. Downloads are capped at 20 MB. |
| `seconds(audio)` | Returns the length of an `Audio` in seconds. |

ffmpeg must be on PATH. `main.py` warns at startup if it can't find it.

Python 3.13 removed the `audioop` module, so the standard library can't resample audio on its own. That is why ffmpeg is used.

## IPAWS audio

IPAWS attaches broadcast audio to a CAP `<info>` block as a resource like this:

```xml
<resource>
  <resourceDesc>EAS Broadcast Content</resourceDesc>
  <mimeType>audio/x-ipaws-audio-mp3</mimeType>
  <derefUri>SUQzBAAAAAAA...</derefUri>   <!-- base64; or <uri>https://...</uri> -->
</resource>
```

`cap_alert.parse_cap` collects these resources for each language. `main.py` then tries each one in turn with `resource_bytes` and `to_audio`.
