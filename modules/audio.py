# gets IPAWS and TTS audio into what the EASyPLUS takes: 8kHz mono 16-bit PCM, 2 minutes max.
# anything not already in that format goes through ffmpeg, so it needs to be on PATH.

import base64
import io
import shutil
import subprocess
import urllib.request
import wave

from easyplus_protocol import AUDIO_LIMIT_FRAMES, Audio


class AudioError(Exception):
    pass


def to_audio(data):
    # if it's already an 8kHz mono 16-bit wav we can skip ffmpeg
    try:
        with wave.open(io.BytesIO(data), 'rb') as wav:
            if wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 8000:
                return Audio(wav.readframes(min(wav.getnframes(), AUDIO_LIMIT_FRAMES)))
    except (wave.Error, EOFError):
        pass
    return Audio(ffmpeg_convert(data))


def ffmpeg_convert(data):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise AudioError('ffmpeg is not installed or not on PATH, cannot convert audio')

    # -t 120 cuts it off at the encoder's 2 minute limit
    cmd = [ffmpeg, '-loglevel', 'error', '-i', 'pipe:0', '-t', '120',
           '-ac', '1', '-ar', '8000', '-f', 's16le', 'pipe:1']
    try:
        result = subprocess.run(cmd, input=data, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise AudioError('ffmpeg timed out')

    if result.returncode != 0 or not result.stdout:
        error = result.stderr.decode(errors='replace').strip()
        raise AudioError(f'ffmpeg could not convert audio: {error[:200]}')
    return result.stdout


def resource_bytes(resource, timeout=30):
    # CAP audio is either base64'd right in the alert (derefUri) or linked (uri)
    if resource.get('deref'):
        try:
            return base64.b64decode(resource['deref'])
        except ValueError as e:
            raise AudioError(f'Bad embedded audio: {e}')

    uri = resource.get('uri', '')
    # only follow web links, don't want a CAP pointing us at file:// on this machine
    if not uri.lower().startswith(('http://', 'https://')):
        raise AudioError(f'Unsupported audio URI: {uri[:80]!r}')

    try:
        req = urllib.request.Request(uri, headers={'User-Agent': 'EASyPyCAP'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(20 * 1024 * 1024 + 1)
    except OSError as e:
        raise AudioError(f'Could not download {uri}: {e}')
    if len(data) > 20 * 1024 * 1024:
        raise AudioError(f'Audio at {uri} is over 20 MB, skipping')
    return data


def seconds(audio):
    return len(audio.pcm) / 2 / 8000
