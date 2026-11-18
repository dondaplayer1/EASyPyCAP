"""Generate alert audio with the configured TTS engine."""
import io
import json
import logging
import platform
import subprocess
import sys
from pathlib import Path

from audio import AudioError, to_audio
# Vendored from github.com/wagwan-piffting-blud/E2T-NG at 084440f.
from e2t_ng.python.EAS2Text_NG import E2T as E2T

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / 'config.json'
log = logging.getLogger('TTS')


class TTSError(Exception):
    pass


def gtts_audio(text, lang, *, zczc=None):
    try:
        from gtts import gTTS
    except ImportError:
        raise TTSError('gTTS is not installed (pip install gTTS)')
    mp3 = io.BytesIO()
    voice = 'es' if lang == 'es-us' else 'en'
    if zczc:
        text = f"{E2T(zczc, 'TRILITHIC8PLUS')} {text}".strip()
    log.info('gTTS (%s) text: %r', lang, text)
    gTTS(text, lang=voice).write_to_fp(mp3)
    return mp3.getvalue()

def dave_executable():
    system = platform.system()
    machine = platform.machine().lower()
    x86 = machine in ('x86', 'i386', 'i486', 'i586', 'i686')
    amd64 = machine in ('amd64', 'x86_64')

    if system == 'Darwin':
        names = ('loqdave-macos-universal',)
    elif system == 'Windows' and amd64:
        names = ('loqdave-windows-amd64.exe', 'loqdave-windows-x86.exe')
    elif system == 'Windows' and x86:
        names = ('loqdave-windows-x86.exe',)
    elif system == 'Linux' and amd64:
        names = ('loqdave-linux-amd64', 'loqdave-linux-x86')
    elif system == 'Linux' and x86:
        names = ('loqdave-linux-x86',)
    elif system == 'Linux' and machine in ('aarch64', 'arm64') and sys.maxsize > 2**32:
        names = ('loqdave-linux-arm64',)
    elif system == 'Linux' and machine in ('aarch64', 'arm64', 'armv7l', 'armv8l'):
        # 32-bit Raspberry Pi OS can report an aarch64 kernel.
        names = ('loqdave-linux-armv7', 'loqdave-linux-armv6')
    elif system == 'Linux' and machine == 'armv6l':
        names = ('loqdave-linux-armv6',)
    else:
        raise TTSError(f'No LoqDave release executable for {system} {machine}')

    for name in names:
        binary = ROOT / name
        if binary.is_file():
            return binary
    raise TTSError(f'Put {" or ".join(names)} in the project root ({ROOT})')


def blueboxtts(text, lang, *, zczc=None):
    binary = dave_executable()

    if zczc:
        text = f"{E2T(zczc, 'SAGE')} {text}".strip()
    log.info('Sage Digital (%s) text: %r', lang, text)

    # dave reads Latin-1. pipe the WAV back so concurrent alerts need no temp file.
    try:
        result = subprocess.run(
            [str(binary), '--file', '-', '--rate', '8000', '-o', '-', '--quiet'],
            input=text.encode('latin-1', errors='replace'),
            capture_output=True,
            check=True,
            timeout=60,
        )
    except OSError as error:
        raise TTSError(f'Could not run {binary.name}: {error}') from error
    except subprocess.TimeoutExpired as error:
        raise TTSError('loqdave timed out') from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors='replace').strip()
        raise TTSError(detail or f'loqdave exited with status {error.returncode}') from error
    if not result.stdout:
        raise TTSError('loqdave returned an empty WAV')
    return result.stdout

ENGINES = {
    'gtts': gtts_audio,
    'sagedigital': blueboxtts,
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


def synthesize(text, lang='en-us', config_path=None, *, zczc=None):
    """Return encoder audio when the configured engine has input."""
    name = configured_engine(config_path)
    if not name:
        return None
    if not text.strip() and not (name == 'sagedigital' and zczc):
        return None
    if name not in ENGINES:
        raise TTSError(f'Unknown tts engine {name!r} in config.json (known: {", ".join(ENGINES)})')

    try:
        engine = ENGINES[name]
        if name == 'sagedigital':
            return to_audio(engine(text, lang, zczc=zczc))
        if name == 'gtts' and zczc:
            return to_audio(engine(text, lang, zczc=zczc))
        return to_audio(engine(text, lang))
    except TTSError:
        raise
    except AudioError as error:
        raise TTSError(str(error)) from error
    except Exception as error:
        raise TTSError(f'{name} failed: {error}') from error
