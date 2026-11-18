"""Read CAP XML and build SAME headers for EASyPLUS."""
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from easyplus_protocol import Alert, Audio

CAP_NAMESPACES = ['urn:oasis:names:tc:emergency:cap:1.2', 'urn:oasis:names:tc:emergency:cap:1.1']
ORIGINATORS = ['EAS', 'WXR', 'CIV', 'PEP']


class NotDeliverable(ValueError):
    """A CAP message that cannot be aired, such as Cancel, Ack, or Error."""


def parse_time(value):
    timestamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('sent/expires must include a UTC offset or Z')
    return timestamp.astimezone(timezone.utc)


def clean_text(text):
    # Keep the appliance's printable ASCII and comma handling.
    chars = []
    for char in unicodedata.normalize('NFKD', str(text)):
        if unicodedata.combining(char):
            continue
        if char == ',':
            chars.append('-')
        elif ' ' <= char <= '~':
            chars.append(char)
        else:
            chars.append(' ')
    return ''.join(chars)


def same_duration(sent, expires):
    # SAME purge time rounds up to 15 min steps under an hour, 30 min steps after
    minutes = math.ceil((expires - sent).total_seconds() / 60)
    step = 15 if minutes < 60 else 30
    minutes = math.ceil(minutes / step) * step
    if minutes > 99 * 60 + 30:
        raise ValueError('Alert duration exceeds SAME limit of 99:30')
    return f'{minutes // 60:02d}{minutes % 60:02d}'


def get_lang(code):
    code = code.lower()
    if code in ('en', 'en-us'):
        return 'en-us'
    if code in ('es', 'es-us'):
        return 'es-us'
    return None


def parse_cap(raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    # Reject DTDs and entity declarations before parsing the feed.
    upper_xml = raw.upper()
    if b'<!DOCTYPE' in upper_xml or b'<!ENTITY' in upper_xml:
        raise ValueError('CAP XML must not contain a DTD or entity declarations')

    root = ET.fromstring(raw)
    if root.tag not in [f'{{{namespace}}}alert' for namespace in CAP_NAMESPACES]:
        raise ValueError('Expected a CAP 1.1 or 1.2 alert element')
    ns = {'c': root.tag[1:].split('}')[0]}

    def text(el, tag, default=''):
        return el.findtext('c:' + tag, default, ns).strip()

    def findall(el, tag):
        return el.findall('c:' + tag, ns)

    def values(el, tag, name):
        return [text(node, 'value') for node in findall(el, tag) if text(node, 'valueName') == name]

    msg_type = text(root, 'msgType')
    if msg_type not in ('Alert', 'Update'):
        raise NotDeliverable(f'Only CAP Alert and Update messages can be delivered (got {msg_type or "none"!r})')

    english = None
    languages = {}
    for info in findall(root, 'info'):
        lang = get_lang(text(info, 'language', 'en-US'))
        if not lang or lang in languages:
            continue
        if lang == 'en-us':
            english = info

        parts = [text(info, tag) for tag in ('headline', 'description', 'instruction')]
        languages[lang] = {
            'alert_text': ' '.join(part for part in parts if part),
            'audio': get_audio_resources(info, text, findall),
        }
    if english is None:
        raise ValueError('CAP needs an English info block for SAME metadata')

    locations = []
    areas = []
    for area in findall(english, 'area'):
        area_desc = text(area, 'areaDesc')
        if area_desc:
            areas.append(area_desc)
        for same in values(area, 'geocode', 'SAME'):
            locations.extend(same.split())

    return {
        'identifier': text(root, 'identifier'),
        'sender': text(root, 'sender'),
        'sent': text(root, 'sent'),
        'cap_status': text(root, 'status'),
        'msg_type': msg_type,
        'event': text(english, 'event'),
        'event_code': (values(english, 'eventCode', 'SAME') or [''])[0],
        'eas_org': (values(english, 'parameter', 'EAS-ORG') or [''])[0],
        'block_channels': [v.upper() for v in values(english, 'parameter', 'BLOCKCHANNEL')],
        'area_desc': '; '.join(areas),
        'locations': locations,
        'expires': text(english, 'expires'),
        'languages': languages,
        'must_carry': False,
    }


def get_audio_resources(info, text, findall):
    resources = []
    for resource in findall(info, 'resource'):
        mime = text(resource, 'mimeType').lower()
        if not mime.startswith('audio/') or 'stream' in mime:
            continue
        resources.append({
            'desc': text(resource, 'resourceDesc'),
            'mime': mime,
            'uri': text(resource, 'uri'),
            'deref': text(resource, 'derefUri'),
        })
    resources.sort(key=lambda resource: resource['desc'].lower() != 'eas broadcast content')
    return resources


def load_cap(path):
    return parse_cap(Path(path).read_bytes())


def prepare_alert(data, call_sign='CAP', audio_en=None, audio_es=None, must_carry=None):
    """Check an alert dict and build the easyplus_protocol.Alert for it.

    audio_en/audio_es can be Audio objects or paths to 8kHz mono 16-bit WAVs.
    Raises ValueError (or KeyError for missing fields) if anything is off.
    """
    sent = parse_time(data['sent'])
    expires = parse_time(data['expires'])
    if expires <= sent:
        raise ValueError('expires must follow sent')

    event = str(data['event_code']).upper()
    org = str(data['eas_org']).upper()
    if not re.fullmatch('[A-Z0-9]{3}', event) or org not in ORIGINATORS:
        raise ValueError('A three-character SAME event and EAS/WXR/CIV/PEP originator are required')
    if event in ('EAN', 'EAT'):
        raise ValueError('EAN/EAT need the live-stream workflow, which this sender does not implement')

    locations = list(dict.fromkeys(str(x) for x in data['locations']))  # dedupe, keep order
    if not 1 <= len(locations) <= 31 or any(not re.fullmatch('[0-9]{6}', x) for x in locations):
        raise ValueError('Supply 1..31 unique six-digit SAME locations')

    # - and + would break the SAME header
    if not 1 <= len(call_sign) <= 8 or any(not 32 <= ord(c) <= 126 or c in '-+' for c in call_sign):
        raise ValueError('Source label must be 1..8 printable ASCII characters without - or +')

    # station ID is left blank (8 spaces), the encoder fills in its own
    same_locations = '-'.join(locations)
    duration = same_duration(sent, expires)
    header = f'ZCZC-{org}-{event}-{same_locations}+{duration}-{sent:%j%H%M}-        -'

    langs = data.get('languages', {})
    if must_carry is None:
        must_carry = bool(data.get('must_carry', False))

    alert = Alert(
        rx_time=int(sent.timestamp()),
        fsk_header=header,
        alert_text_en=clean_text(langs.get('en-us', {}).get('alert_text', '')),
        alert_text_es=clean_text(langs.get('es-us', {}).get('alert_text', '')),
        call_sign=call_sign.ljust(8),
        must_carry=must_carry,
        audio_en=load_audio(audio_en),
        audio_es=load_audio(audio_es),
    )
    alert.payload()  # catches oversized fields now instead of mid-send
    return alert


def load_audio(value):
    if value is None or isinstance(value, Audio):
        return value
    return Audio.from_wav(value)
