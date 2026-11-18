# `modules/tts_man.py`

`tts_man.py` is the text-to-speech manager. It is the **only** file you need to edit to add a new TTS engine.

## Config

`config.json`:

```json
{ "tts": "gtts" }
```

| Value | Result |
|---|---|
| `"gtts"` | Google Translate TTS. Needs `pip install gTTS`, internet access, and ffmpeg, because gTTS outputs MP3. |
| `false`, `null`, `""`, `"none"`, `"off"`, or the key left out | TTS is off. |
| anything else | Treated as an engine name. If no engine has that name, `synthesize` raises `TTSError` and `main.py` logs it. |

Upper and lower case are treated the same. The file is re-read on **every** request, so changing it takes effect on the next alert without a restart.

## API

| Function | What it does |
|---|---|
| `synthesize(text, lang='en-us', config_path=None)` | Returns an `Audio` ready for the encoder, or `None` if TTS is off. Raises `TTSError` if TTS is on but fails. `lang` is `'en-us'` or `'es-us'`. |
| `configured_engine(config_path=None)` | Returns the engine name from the config, or `None`. |
| `ENGINES` | A dict of the available engines: name → function. |

By default the config is read from `config.json` in the project root. `main.py` passes in the path given by its `--config-dir` option.

## Adding an engine

Write a function that takes `(text, lang)` and returns audio bytes in **any format ffmpeg can read**. Then add it to the `ENGINES` dict:

```python
def espeak_audio(text, lang):
    voice = 'es' if lang == 'es-us' else 'en-us'
    return subprocess.run(['espeak-ng', '-v', voice, '--stdout', text],
                          capture_output=True, check=True).stdout   # WAV bytes


ENGINES = {
    'gtts': gtts_audio,
    'espeak': espeak_audio,
}
```

Then set `"tts": "espeak"` in `config.json`. You don't need to convert the audio to 8 kHz or trim it to 120 seconds; `audio.to_audio` does both. Any exception your function raises is turned into a `TTSError`, so `main.py` logs a warning and sends the alert without audio.
