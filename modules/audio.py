"""Convert IPAWS and TTS audio to 8 kHz mono PCM."""
import base64
import io
import shutil
import subprocess
import urllib.request
import wave

from easyplus_protocol import AUDIO_LIMIT_FRAMES, FRAMES_PER_SECOND, Audio

SAMPLE_WIDTH = 2
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


class AudioError(Exception):
    pass


def to_audio(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as wav:
            wav_format = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            if wav_format == (1, SAMPLE_WIDTH, FRAMES_PER_SECOND):
                frames = min(wav.getnframes(), AUDIO_LIMIT_FRAMES)
                return Audio(wav.readframes(frames))
    except (wave.Error, EOFError):
        pass
    return Audio(ffmpeg_convert(data))


def ffmpeg_convert(data):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise AudioError('ffmpeg is not installed or not on PATH, cannot convert audio')

    limit_seconds = AUDIO_LIMIT_FRAMES // FRAMES_PER_SECOND
    command = [
        ffmpeg, '-loglevel', 'error', '-i', 'pipe:0',
        '-t', str(limit_seconds), '-ac', '1', '-ar', str(FRAMES_PER_SECOND),
        '-f', 's16le', 'pipe:1',
    ]
    try:
        result = subprocess.run(command, input=data, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise AudioError('ffmpeg timed out')

    if result.returncode != 0 or not result.stdout:
        error = result.stderr.decode(errors='replace').strip()
        raise AudioError(f'ffmpeg could not convert audio: {error[:200]}')
    return result.stdout


def resource_bytes(resource, timeout=30):
    embedded = resource.get('deref')
    if embedded:
        try:
            return base64.b64decode(embedded)
        except ValueError as error:
            raise AudioError(f'Bad embedded audio: {error}') from error

    uri = resource.get('uri', '')
    # CAP resources are fetched over HTTP(S) only.
    if not uri.lower().startswith(('http://', 'https://')):
        raise AudioError(f'Unsupported audio URI: {uri[:80]!r}')

    try:
        request = urllib.request.Request(uri, headers={'User-Agent': 'EASyPyCAP'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except OSError as error:
        raise AudioError(f'Could not download {uri}: {error}') from error
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise AudioError(f'Audio at {uri} is over 20 MB, skipping')
    return data


def seconds(audio):
    return len(audio.pcm) / SAMPLE_WIDTH / FRAMES_PER_SECOND
