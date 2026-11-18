"""Python 3 port of the recovered Python 2.6 EASyPLUS packet builder."""
import struct

SYNC = b'\x9a\x45\x7a\x1b'
DEVICE_CLIENT = 4419
DEVICE_EASYPLUS = 17776
DEVICE_EASYNIC = 17784


def str_from_byte(value):
    return struct.pack('>B', value)


def str_from_short(value):
    return struct.pack('>H', value)


def str_from_long(value):
    return struct.pack('>I', value & 0xffffffff)


def word_str(word, checksum):
    data = str_from_long(word)
    return checksum - sum(data), data


def build_cmd(device, user, cmd, status, payload):
    # The appliance always adds 1..4 pad bytes, including when already aligned.
    payload = bytes(payload) + b'\0' * (4 - len(payload) % 4)
    fields = struct.pack('>6I', (DEVICE_CLIENT << 16) | device,
                         user, cmd, status, len(payload) // 4,
                         -sum(payload) & 0xffffffff)
    checksum = (-sum(SYNC) - sum(fields)) & 0xffffffff
    return SYNC + fields + str_from_long(checksum) + payload


def build_easyplus_cmd(user, cmd, status, payload):
    return build_cmd(DEVICE_EASYPLUS, user, cmd, status, payload)


def build_easynic_cmd(user, cmd, status, payload):
    return build_cmd(DEVICE_EASYNIC, user, cmd, status, payload)
