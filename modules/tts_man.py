# TTS manager. checks "tts" in config.json every time audio is requested,
# so nothing else in the project needs to know which engine is in use.
#
# to add an engine: write a function that takes (text, lang) and returns audio
# bytes (any format ffmpeg can read), then add it to ENGINES at the bottom.
# lang is either 'en-us' or 'es-us'.

import io
import json
from pathlib import Path

from audio import AudioError, to_audio

CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config.json'


class TTSError(Exception):
    pass


def gtts_audio(text, lang):
    try:
        from gtts import gTTS
    except ImportError:
        raise TTSError('gTTS is not installed (pip install gTTS)')
    mp3 = io.BytesIO()
    gTTS(text, lang='es' if lang == 'es-us' else 'en').write_to_fp(mp3)
    return mp3.getvalue()


ENGINES = {
    'gtts': gtts_audio,
}


def configured_engine(config_path=None):
    # engine name from config.json, or None if tts is off
    try:
        with open(config_path or CONFIG_PATH, encoding='utf-8-sig') as f:
            tts = json.load(f).get('tts')
    except FileNotFoundError:
        return None
    if not tts or str(tts).lower() in ('none', 'false', 'off'):
        return None
    return str(tts).lower()


def synthesize(text, lang='en-us', config_path=None):
    # returns Audio, or None if tts is off. raises TTSError if it's on but something breaks
    name = configured_engine(config_path)
    if not name or not text.strip():
        return None
    if name not in ENGINES:
        raise TTSError(f'Unknown tts engine {name!r} in config.json (known: {", ".join(ENGINES)})')

    try:
        return to_audio(ENGINES[name](text, lang))
    except TTSError:
        raise
    except AudioError as e:
        raise TTSError(str(e))
    except Exception as e:  # tts libraries can throw pretty much anything (network errors etc)
        raise TTSError(f'{name} failed: {e}')
