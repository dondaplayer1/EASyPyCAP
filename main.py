#!/usr/bin/env python3
"""Relay IPAWS alerts to subscribed EASyPLUS encoders."""
import argparse
import json
import logging
import os
import shutil
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'modules'))

import tts_man
from audio import AudioError, resource_bytes, seconds, to_audio
from cap_alert import parse_time, prepare_alert
from easyplus_protocol import EasyPlusClient, ProtocolError
from ipaws import IpawsPoller

log = logging.getLogger('MAIN')

ALERT = 25
logging.addLevelName(ALERT, 'ALERT')


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: '\x1b[90m',
        logging.INFO: '\x1b[92m',
        ALERT: '\x1b[95m',
        logging.WARNING: '\x1b[93m',
        logging.ERROR: '\x1b[91m',
        logging.CRITICAL: '\x1b[91m',
    }

    def __init__(self, color=True):
        super().__init__('%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s', '%H:%M:%S')
        self.color = color

    def format(self, record):
        message = super().format(record)
        color = self.COLORS.get(record.levelno) if self.color else None
        if color:
            return f'{color}{message}\x1b[0m'
        return message


def setup_logging():
    color = sys.stdout.isatty() and not os.environ.get('NO_COLOR')
    if color and os.name == 'nt':
        os.system('')  # gets the windows console to handle color codes
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter(color))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def load_json(config_dir, name, required=True):
    path = Path(config_dir) / name
    if not required and not path.exists():
        return {}
    with path.open(encoding='utf-8-sig') as config_file:
        return json.load(config_file)


def zone_matches(zone, location):
    # SAME codes are PSSCCC. '*' or 000000 matches everything, and a statewide
    # code (SS000) matches every county in that state, either direction
    if zone == '*' or zone == '000000' or location == '000000':
        return True
    if zone[1:3] != location[1:3]:
        return False
    return zone[3:] == location[3:] or zone[3:] == '000' or location[3:] == '000'


def encoder_wants(encoder, alert):
    events = encoder.get('events', ['*'])
    if '*' not in events and alert['event_code'] not in events:
        return False
    for zone in encoder.get('counties', ['*']):
        for location in alert['locations']:
            if zone_matches(zone, location):
                return True
    return False


class Relay:
    def __init__(self, settings, encoders, dry_run=False, config_path=None):
        self.callsign = settings.get('callsign', 'CAP')
        self.encoders = {name: enc for name, enc in encoders.items() if enc.get('enabled', True)}
        self.dry_run = dry_run
        self.config_path = config_path
        self.source_openers = {}
        self.sent = set()
        self.lock = threading.Lock()
        self.encoder_locks = {name: threading.Lock() for name in self.encoders}

    def on_alert(self, source, alert):
        event_code = alert["event_code"] or "???"
        event = alert.get("event", "")
        area = alert.get("area_desc", "")
        status = alert.get("cap_status")
        log.log(ALERT, f'{event_code} {event} - {area} [{source}, {status}]')

        if status != 'Actual':
            log.info('Not an Actual alert, skipping')
            return
        if 'EAS' in alert.get('block_channels', []):
            log.info('BLOCKCHANNEL=EAS (not for broadcast), skipping')
            return
        try:
            if parse_time(alert['expires']) <= datetime.now(timezone.utc):
                log.info('Already expired, skipping')
                return
        except ValueError as error:
            log.warning(f'Bad expiry time: {error}')
            return

        alert_id = (alert.get('sender'), alert.get('identifier'), alert.get('sent'))
        targets = []
        for name, encoder in self.encoders.items():
            if not encoder_wants(encoder, alert):
                log.info(f'{name}: not subscribed')
                continue
            send_key = (name, alert_id)
            with self.lock:
                if send_key in self.sent:
                    log.info(f'{name}: already sent')
                    continue
                # Reserve the delivery before another feed can pick it up.
                self.sent.add(send_key)
            targets.append((name, encoder))

        if not targets:
            return
        try:
            prepared = prepare_alert(alert, self.callsign)
        except (ValueError, KeyError) as error:
            log.error(f'{source}: Cannot build alert: {error}')
            return

        audio = self.get_audio(alert, self.source_openers.get(source), zczc=prepared.fsk_header)
        prepared = replace(prepared, audio_en=audio.get('en-us'), audio_es=audio.get('es-us'))
        for name, encoder in targets:
            self.send(name, encoder, prepared, alert['event_code'])

    def get_audio(self, alert, open_request=None, *, zczc=None):
        audio = {}
        for lang, info in alert.get('languages', {}).items():
            audio[lang] = self.ipaws_audio(lang, info, open_request) or self.tts_audio(lang, info, zczc=zczc)
        return audio

    def ipaws_audio(self, lang, info, open_request=None):
        for resource in info.get('audio', []):
            try:
                audio = to_audio(resource_bytes(resource, open_request=open_request))
            except AudioError as error:
                log.warning(f'IPAWS audio ({lang}) unusable: {error}')
                continue
            log.info(f'Using IPAWS audio ({lang}, {seconds(audio):.1f}s)')
            return audio
        return None

    def tts_audio(self, lang, info, *, zczc=None):
        try:
            audio = tts_man.synthesize(info.get('alert_text', ''), lang, self.config_path, zczc=zczc)
        except tts_man.TTSError as error:
            log.warning(f'TTS ({lang}) failed: {error}, sending without audio')
            return None
        if audio:
            log.info(f'Generated TTS audio ({lang}, {seconds(audio):.1f}s)')
        return audio

    def send(self, name, encoder, alert, event_code):
        encoder_log = logging.getLogger(name)
        langs = ', '.join(lang for lang, audio in (('en-us', alert.audio_en), ('es-us', alert.audio_es)) if audio) or 'none'
        if self.dry_run:
            encoder_log.info(f'[dry run] would send {alert.fsk_header} (audio: {langs})')
            return

        encoder_log.info(f'Sending {alert.fsk_header} (audio: {langs})')
        client = EasyPlusClient(
            encoder['ip'], encoder['password'],
            cmd_port=int(encoder.get('command_port', 59911)),
            audio_port=int(encoder.get('audio_port', 59919)),
        )
        try:
            with self.encoder_locks[name]:
                client.deliver(alert)
        except (OSError, ProtocolError, ValueError) as error:
            # A retry could air the alert twice if the encoder already accepted it.
            encoder_log.error(f'Delivery failed: {error}')
            return
        encoder_log.info(f'Encoder accepted {event_code}')


def main():
    parser = argparse.ArgumentParser(description='Relay IPAWS alerts to EASyPLUS encoders')
    parser.add_argument('--dry-run', action='store_true', help="don't contact the encoders")
    parser.add_argument('--config-dir', type=Path, default=ROOT, help='folder with the .json config files')
    args = parser.parse_args()
    setup_logging()

    settings = load_json(args.config_dir, 'config.json', required=False)
    encoders = load_json(args.config_dir, 'encoders.json')['encoders']
    sources = load_json(args.config_dir, 'sources.json')['sources']
    config_path = args.config_dir / 'config.json'
    relay = Relay(settings, encoders, args.dry_run, config_path)

    log.info(f'Callsign {relay.callsign!r}, encoders: {", ".join(relay.encoders) or "none enabled"}')
    tts = tts_man.configured_engine(config_path)
    log.info(f'TTS: {tts or "off"}')
    if tts and tts not in tts_man.ENGINES:
        log.warning(f'Unknown tts engine {tts!r}, known: {", ".join(sorted(tts_man.ENGINES))}')
    if not shutil.which('ffmpeg'):
        log.warning('ffmpeg not found on PATH, mp3 audio (IPAWS or TTS) cannot be converted')
    if args.dry_run:
        log.warning('Dry run, encoder send disabled')

    stop_event = threading.Event()
    pollers = []
    for name, source in sources.get('ipaws', {}).items():
        if source.get('enabled', True):
            poller = IpawsPoller(
                name, source['url'], source.get('poll_dur', 60), relay.on_alert, stop_event,
                pin=source.get('pin'), verify_ssl=source.get('verify_ssl', True),
            )
            if poller.open_request:
                relay.source_openers[name] = poller.open_request
            pollers.append(poller)
    if not pollers:
        log.error('No enabled sources in sources.json')
        return 1
    for poller in pollers:
        poller.start()

    try:
        while any(poller.is_alive() for poller in pollers):
            stop_event.wait(1)
    except KeyboardInterrupt:
        log.info('Stopping...')
        stop_event.set()
        for poller in pollers:
            poller.join(5)
    return 0


if __name__ == '__main__':
    sys.exit(main())
