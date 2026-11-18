# `modules/easyplus_cmd.py`

This is a Python 3 port of the recovered Python 2.6 packet builder for EASyPLUS commands. **Do not modify it.**

## Constants

| Name | Value | Meaning |
|---|---|---|
| `SYNC` | `9A 45 7A 1B` | Marks the start of every command and reply. |
| `DEVICE_CLIENT` | `0x1143` (4419) | ID of the sending side. Goes in the high 16 bits of word 0. |
| `DEVICE_EASYPLUS` | `0x4570` (`"Ep"`) | Target ID for the encoder itself. |
| `DEVICE_EASYNIC` | `0x4578` (`"Ex"`) | Target ID for the network/audio card (EASyNIC). |

## Packet layout

The header is 32 bytes, followed by the padded payload. All words are big-endian 32-bit:

| Offset | Field |
|---|---|
| 0 | `SYNC` |
| 4 | `(DEVICE_CLIENT << 16) \| device` |
| 8 | `user`: 0 normally. At login it is `offset \| 0x8000`. |
| 12 | `cmd`: the command ID |
| 16 | `status`: the session ID after login, otherwise 0 |
| 20 | Payload length in **32-bit words**, after padding |
| 24 | Payload checksum: `-(sum of payload bytes) mod 2³²` |
| 28 | Header checksum: `-(sum of bytes 0–23) mod 2³²` |
| 32 | Payload |

**Padding:** the payload is always padded with 1 to 4 zero bytes, even when its length is already a multiple of 4. A 4-byte payload is therefore sent as 8 bytes. The appliance expects this, so do not "fix" it.

The checksums are sums of **bytes**, not of words.

Replies are also 32 bytes and start with `SYNC`. `easyplus_protocol` takes word 4 (offset 16) as the result value.

## Functions

| Function | What it does |
|---|---|
| `build_cmd(device, user, cmd, status, payload)` | Builds the full packet described above. |
| `build_easyplus_cmd(user, cmd, status, payload)` | `build_cmd` with `DEVICE_EASYPLUS`. |
| `build_easynic_cmd(user, cmd, status, payload)` | `build_cmd` with `DEVICE_EASYNIC`. |
| `str_from_byte` / `str_from_short` / `str_from_long` | Pack an unsigned big-endian 8-, 16- or 32-bit value. The names come from Python 2. |
| `word_str(word, checksum)` | Returns `(checksum - bytesum(word), packed_word)`. Left over from the original, nothing uses it. |
