"""Standalone Python 3 port of the EASyCAP EASyPLUS delivery path.

Uses the recovered command IDs, payload layout, login algorithm and audio
byte order. Does not depend on appliance daemons or native .so extensions.
"""
from dataclasses import dataclass
import secrets
import socket
import struct
import time
import wave

from easy_crypto import encode_shuffled_bytes, xor_encrypt_data_bytes
from easyplus_cmd import SYNC, build_easyplus_cmd, build_easynic_cmd

LOGON_CMD = 196609
LOGOFF_CMD = 196610
SET_CAP_ALERT_CMD = 65552
EOM_CMD = 65554
RECORD_NIC_AUDIO_CMD = 786443
QUERY_AVAILABLE_SPACE_CMD = 786445
ALERT_BUSY, ALERT_ACCEPTED, ALERT_REJECTED = 0, 1, 255
EN_AUDIO_FILE, ES_AUDIO_FILE, AUDIO_STREAM = 1, 2, 3
FRAMES_PER_SECOND = 8000
AUDIO_LIMIT_FRAMES = 120 * FRAMES_PER_SECOND


class ProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Audio:
    pcm: bytes

    @classmethod
    def from_wav(cls, path, limit=True):
        with wave.open(str(path), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                    wav.getcomptype()) != (1, 2, 8000, 'NONE'):
                raise ValueError('Audio must be uncompressed 8000 Hz, mono, 16-bit PCM WAV')
            frames = min(wav.getnframes(), AUDIO_LIMIT_FRAMES) if limit else wav.getnframes()
            pcm = wav.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError('Truncated WAV audio')
            return cls(pcm)

    def network_bytes(self):
        result = bytearray(len(self.pcm))
        result[0::2], result[1::2] = self.pcm[1::2], self.pcm[0::2]
        return bytes(result)


@dataclass(frozen=True)
class Alert:
    rx_time: int
    fsk_header: str
    alert_text_en: str = ''
    alert_text_es: str = ''
    call_sign: str = 'CAP     '
    must_carry: bool = False
    audio_en: Audio | None = None
    audio_es: Audio | None = None

    def payload(self):
        call = self.call_sign.encode('ascii')
        header = self.fsk_header.encode('ascii')
        en, es = self.alert_text_en.encode('ascii'), self.alert_text_es.encode('ascii')
        if not 1 <= len(call) <= 255 or any(len(x) > 65535 for x in (header, en, es)):
            raise ValueError('Call sign, SAME header or text exceeds protocol field size')
        return struct.pack('>IIIIBBHHH', 0, self.rx_time,
                           len(self.audio_en.pcm) if self.audio_en else 0,
                           len(self.audio_es.pcm) if self.audio_es else 0,
                           int(self.must_carry), len(call), len(header), len(en), len(es)
                           ) + call + header + en + es


class EasyPlusClient:
    def __init__(self, host, password, cmd_port=59911, audio_port=59919,
                 timeout=10.0, busy_timeout=60.0):
        if timeout <= 0 or busy_timeout <= 0:
            raise ValueError('Timeouts must be positive')
        self.host, self.password = host, password
        self.cmd_port, self.audio_port = cmd_port, audio_port
        self.timeout, self.busy_timeout = timeout, busy_timeout
        self.sock = None
        self.session_id = None

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _recv_exact(self, count):
        result = bytearray()
        while len(result) < count:
            part = self.sock.recv(count - len(result))
            if not part:
                raise ProtocolError('Device closed connection during reply')
            result.extend(part)
        return bytes(result)

    def issue_cmd(self, command, remaining=None):
        if self.sock is None:
            raise ProtocolError('No command connection')
        self.sock.settimeout(min(self.timeout, remaining) if remaining else self.timeout)
        try:
            self.sock.sendall(command)
            reply = self._recv_exact(32)
            if reply[:4] != SYNC:
                raise ProtocolError('Invalid command reply sync')
            # The original only reads these 32 bytes and returns word 4.
            return struct.unpack('>8I', reply)[4]
        except (OSError, ProtocolError) as exc:
            self.close()
            raise ProtocolError(f'Command failed; device state may be uncertain: {exc}') from exc

    def logon(self):
        if self.sock is not None:
            raise ProtocolError('Already connected')
        password = self.password.encode('ascii')
        if not 1 <= len(password) <= 32 or b'\0' in password:
            raise ValueError('Password must contain 1..32 ASCII bytes without NUL')
        self.sock = socket.create_connection((self.host, self.cmd_port), self.timeout)
        offset = secrets.randbelow(512)
        shuffled = encode_shuffled_bytes(secrets.randbelow(4), password,
            b'ebawehtnielbmigdnaerygdidsevotyhtilsehtdnagillirbsawt')
        try:
            session = self.issue_cmd(build_easyplus_cmd(offset | 32768, LOGON_CMD, 0,
                                    xor_encrypt_data_bytes(offset, shuffled)))
            if session == 0 or session & 0x80000000:
                raise ProtocolError('EASyPLUS rejected login')
            self.session_id = session
            return session
        except BaseException:
            self.close()
            raise

    def logoff(self):
        try:
            if self.sock is not None and self.session_id is not None:
                self.issue_cmd(build_easyplus_cmd(0, LOGOFF_CMD, self.session_id,
                                                 struct.pack('>I', self.session_id)))
        finally:
            self.session_id = None
            self.close()

    def _command(self, command, payload, nic=False, remaining=None):
        if self.session_id is None:
            raise ProtocolError('Not logged in')
        builder = build_easynic_cmd if nic else build_easyplus_cmd
        return self.issue_cmd(builder(0, command, self.session_id, payload), remaining)

    def _wait_accepted(self, command, payload, interval):
        deadline = time.monotonic() + self.busy_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError(f'Device remained busy for command {command:#x}')
            reply = self._command(command, payload, remaining=remaining)
            if reply == ALERT_ACCEPTED:
                return
            if reply != ALERT_BUSY:
                raise ProtocolError(f'Device rejected command {command:#x}: {reply:#x}')
            time.sleep(min(interval, max(0, deadline - time.monotonic())))

    def record_audio(self, file_type):
        return self._command(RECORD_NIC_AUDIO_CMD, struct.pack('>I', file_type), nic=True)

    def query_available_space(self, file_type):
        return self._command(QUERY_AVAILABLE_SPACE_CMD, struct.pack('>I', file_type))

    def load_audio_file(self, audio):
        # A separate TCP connection carries raw signed 16-bit, big-endian samples.
        with socket.create_connection((self.host, self.audio_port), self.timeout) as sock:
            sock.settimeout(self.timeout)
            pcm = audio.network_bytes()
            for offset in range(0, len(pcm), 4096):
                sock.sendall(pcm[offset:offset + 4096])
                time.sleep(.001)
            # Recovered file sender appends 250 ms silence at EOF. The silence
            # is not included in the declared voice length. At the 120s limit
            # it closes immediately instead.
            if len(audio.pcm) < AUDIO_LIMIT_FRAMES * 2:
                sock.sendall(b'\0' * 4000)

    def deliver(self, alert):
        payload = alert.payload()  # Validate before opening a connection.
        self.logon()
        error = None
        try:
            self._wait_accepted(SET_CAP_ALERT_CMD, payload, 5)
            if alert.fsk_header[9:12] in ('EAN', 'EAT'):
                time.sleep(12)  # Preserved from appliance delivery path.
            if alert.audio_en:
                self.load_audio_file(alert.audio_en)
            if alert.audio_es:
                reply = self.record_audio(ES_AUDIO_FILE)
                if reply != ALERT_ACCEPTED:
                    raise ProtocolError(f'Spanish audio selection rejected: {reply:#x}')
                self.load_audio_file(alert.audio_es)
            self._wait_accepted(EOM_CMD, struct.pack('>I', alert.rx_time), 1)
        except BaseException as exc:
            error = exc
            raise
        finally:
            try:
                self.logoff()
            except (OSError, ProtocolError):
                if error is None:
                    raise
