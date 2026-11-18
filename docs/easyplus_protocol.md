# `modules/easyplus_protocol.py`

This is a standalone Python 3 port of the EASyCAP code path that delivers alerts to an EASyPLUS. It uses the command IDs, payload layout, login algorithm and audio byte order recovered from the appliance. **Do not modify it.** The byte layouts have to match the encoder.

It depends on [easyplus_cmd](easyplus_cmd.md) for packet framing and on [easy_crypto](easy_crypto.md) for login obfuscation.

## Constants

| Name | Value | Meaning |
|---|---|---|
| `LOGON_CMD` | `0x30001` | Login. The reply carries the session ID. |
| `LOGOFF_CMD` | `0x30002` | Logout. |
| `SET_CAP_ALERT_CMD` | `0x10010` | Sends the alert metadata and text (see payload below). |
| `EOM_CMD` | `0x10012` | End of message, which completes the alert. |
| `RECORD_NIC_AUDIO_CMD` | `0xC000B` | Picks which audio slot comes next. Sent as an **EASyNIC** device command. |
| `QUERY_AVAILABLE_SPACE_CMD` | `0xC000D` | Asks how much audio space is free. Defined but not used in delivery. |
| `ALERT_BUSY` / `ALERT_ACCEPTED` / `ALERT_REJECTED` | `0` / `1` / `255` | Reply codes. |
| `EN_AUDIO_FILE` / `ES_AUDIO_FILE` / `AUDIO_STREAM` | `1` / `2` / `3` | Audio slot types. |
| `FRAMES_PER_SECOND` | 8000 | |
| `AUDIO_LIMIT_FRAMES` | 960000 | 120 seconds. |

## Classes

### `ProtocolError(RuntimeError)`

Raised for a protocol failure, a rejected command, or a busy timeout. If a command fails partway, the connection is closed and the error message warns that the device state may be uncertain.

### `Audio` (frozen dataclass)

- `pcm: bytes` holds little-endian 16-bit mono samples, as stored in a WAV file.
- `Audio.from_wav(path, limit=True)` only accepts **uncompressed 8000 Hz mono 16-bit** WAV. With `limit=True`, it keeps only the first 120 seconds. A truncated file raises `ValueError`.
- `network_bytes()` byte-swaps every sample to **big-endian** before it is sent.

### `Alert` (frozen dataclass)

| Field | Type | Notes |
|---|---|---|
| `rx_time` | int | Unix time of the CAP `sent` field. It is also the alert's ID in `EOM_CMD`. |
| `fsk_header` | str | The full SAME `ZCZC-...` header. |
| `alert_text_en`, `alert_text_es` | str | ASCII only. 65535 bytes maximum each. |
| `call_sign` | str | The source label, padded to 8 characters by `cap_alert`. |
| `must_carry` | bool | |
| `audio_en`, `audio_es` | `Audio` or `None` | |

`payload()` returns the body of `SET_CAP_ALERT_CMD`. All values are big-endian:

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | Reserved, always 0 |
| 4 | 4 | `rx_time` |
| 8 | 4 | English audio length in bytes. The trailing silence is not counted. |
| 12 | 4 | Spanish audio length in bytes |
| 16 | 1 | must-carry (0/1) |
| 17 | 1 | Length of the call sign |
| 18 | 2 | Length of the SAME header |
| 20 | 2 | Length of the English text |
| 22 | 2 | Length of the Spanish text |
| 24 | … | The call sign, header, English text and Spanish text, one after another, not NUL-terminated |

### `EasyPlusClient(host, password, cmd_port=59911, audio_port=59919, timeout=10.0, busy_timeout=60.0)`

| Method | What it does |
|---|---|
| `deliver(alert)` | **Main entry point.** Runs the full sequence below. It always logs off, even after an error. |
| `logon()` | Opens the command socket and logs in. Returns the session ID. |
| `logoff()` | Sends `LOGOFF_CMD` and closes the socket. |
| `issue_cmd(packet, remaining=None)` | Sends one packet, reads the 32-byte reply, and returns reply word 4, which is the result. |
| `record_audio(file_type)` | Sends `RECORD_NIC_AUDIO_CMD` through the EASyNIC device. |
| `query_available_space(file_type)` | Sends `QUERY_AVAILABLE_SPACE_CMD`. |
| `load_audio_file(audio)` | Streams the PCM over a **separate** TCP connection to `audio_port`. |
| `close()` | Closes the command socket. |

## Delivery sequence (`deliver`)

```
1. payload = alert.payload()                    validate before connecting
2. logon()                                      TCP to cmd_port
3. SET_CAP_ALERT_CMD(payload)                   repeat every 5 s while BUSY, up to busy_timeout
4. if event is EAN/EAT: sleep 12 s              kept from the original; cap_alert blocks these
5. if audio_en: load_audio_file(audio_en)       the English slot is the implied default
6. if audio_es: record_audio(ES_AUDIO_FILE)     must return ACCEPTED
               load_audio_file(audio_es)
7. EOM_CMD(rx_time)                             repeat every 1 s while BUSY, up to busy_timeout
8. logoff()                                     in `finally`; a logoff error is raised only if
                                                 nothing earlier failed
```

Any reply other than `BUSY` or `ACCEPTED` raises `ProtocolError`.

## Login

1. Generate a random `offset` from 0 to 511 and a random shuffle sequence from 0 to 3.
2. Shuffle the password (1–32 ASCII bytes, no NUL) into a 64-byte block padded with "trash" bytes. See `encode_shuffled_bytes`.
3. XOR the block with the key stream starting at `offset`. See `xor_encrypt_data_bytes`.
4. Send `LOGON_CMD` with `user = offset | 0x8000` and `status = 0`.
5. The reply word is the session ID. A value of `0`, or one with the high bit set, means the login was rejected.

Each later command carries the session ID in the packet's `status` field.

## Audio

- Format on the wire: raw signed 16-bit **big-endian** mono at 8 kHz, with no header.
- It is sent in 4096-byte chunks with a 1 ms sleep between chunks.
- After the samples, 4000 zero bytes (250 ms of silence) are added, except when the clip is at the full 120-second limit. This silence is **not** counted in the length declared in the alert payload.
