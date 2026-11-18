"""Generate alert audio with the configured TTS engine."""
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
    voice = 'es' if lang == 'es-us' else 'en'
    gTTS(text, lang=voice).write_to_fp(mp3)
    return mp3.getvalue()


ENGINES = {
    'gtts': gtts_audio,
}


def configured_engine(config_path=None):
    try:
        with open(config_path or CONFIG_PATH, encoding='utf-8-sig') as config_file:
            tts = json.load(config_file).get('tts')
    except FileNotFoundError:
        return None
    if not tts:
        return None
    name = str(tts).lower()
    if name in ('none', 'false', 'off'):
        return None
    return name


def synthesize(text, lang='en-us', config_path=None):
    """Return encoder audio, or None if TTS is off or the text is empty."""
    name = configured_engine(config_path)
    if not name or not text.strip():
        return None
    if name not in ENGINES:
        raise TTSError(f'Unknown tts engine {name!r} in config.json (known: {", ".join(ENGINES)})')

    try:
        return to_audio(ENGINES[name](text, lang))
    except TTSError:
        raise
    except AudioError as error:
        raise TTSError(str(error)) from error
    except Exception as error:
        raise TTSError(f'{name} failed: {error}') from error
