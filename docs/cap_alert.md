# `modules/cap_alert.py`

This module converts CAP 1.1/1.2 XML, or an appliance alert dict, into an `easyplus_protocol.Alert` that can be delivered to an encoder. It never touches the network.

The work happens in two stages:

1. **Parse:** `parse_cap(raw)` / `load_cap(path)` take CAP XML and return an **alert dict**.
2. **Prepare:** `prepare_alert(data, ...)` takes an alert dict and returns an `Alert`.

The alert dict is the same shape as the appliance's alert-object JSON, so either one can go into stage 2.

## Public API

### `parse_cap(raw) -> dict`

Parses CAP XML given as `bytes` or `str`. Use this one for feed data that is already in memory.

The checks run in this order. Each failure raises `ValueError`:

1. The input must not contain `<!DOCTYPE` or `<!ENTITY`. This guards against entity-expansion attacks.
2. The root must be a CAP 1.1 or 1.2 `<alert>` element.
3. `msgType` must be `Alert` or `Update`. `Cancel`, `Ack` and `Error` raise `NotDeliverable`, a subclass of `ValueError`, so callers can treat these as routine.
4. At least one `<info>` block must be in English. If an `<info>` has no `<language>`, it counts as `en-US`, which is the CAP default.

SAME fields are taken from the **first English `<info>` block** as follows:

| Alert dict key | CAP source |
|---|---|
| `event_code` | `<eventCode>` where `valueName` is `SAME` |
| `eas_org` | `<parameter>` where `valueName` is `EAS-ORG` |
| `locations` | Every `<area><geocode>` where `valueName` is `SAME`. Values separated by spaces are split. |
| `expires` | `<expires>` |
| `sent`, `identifier`, `sender`, `cap_status`, `msg_type` | From the `<alert>` root |
| `event` | `<event>`, the human-readable name such as "Tornado Warning" |
| `area_desc` | All `<areaDesc>` values joined with `; ` |
| `block_channels` | Every `<parameter>` named `BLOCKCHANNEL`, uppercased (IPAWS uses `EAS`, `NWEM`, `CMAS`). `main.py` skips an alert when this includes `EAS`. |

`languages` stores one entry each for `en-us` and `es-us`. Each entry's `alert_text` is `headline + description + instruction` joined with spaces. Each entry's `audio` is a list of that block's audio `<resource>`s, as `{desc, mime, uri, deref}`. The list puts `EAS Broadcast Content` first and leaves out streaming audio. If a language appears in more than one `<info>` block, the first block is used. Languages other than English and Spanish are ignored.

### `load_cap(path) -> dict`

Reads the file at `path` and calls `parse_cap` on it.

### `prepare_alert(data, call_sign='CAP', audio_en=None, audio_es=None, must_carry=None) -> Alert`

Validates the alert dict and builds an `Alert`:

| Check | Rule |
|---|---|
| Times | `sent` and `expires` must be ISO 8601 with an offset or `Z`, and `expires` must be later than `sent`. |
| Event | 3 characters, `[A-Z0-9]`, compared case-insensitively. `EAN` and `EAT` are rejected because they need the live-stream workflow, which this sender does not have. |
| Originator | One of `EAS`, `WXR`, `CIV` or `PEP`. |
| Locations | 1 to 31 six-digit codes after duplicates are removed. The original order is kept. |
| Source label (`call_sign`) | 1 to 8 printable ASCII characters, with no `-` or `+`. It is padded to 8 characters with spaces. |
| Duration | The SAME purge time can be at most `+9930`. |
| Audio | `audio_en` and `audio_es` can each be an `Audio` object, which is used as-is, or a path to a WAV file, which goes through `Audio.from_wav`. See [easyplus_protocol.md](easyplus_protocol.md#audio). |

`must_carry=None` uses `data['must_carry']`. Passing `True` or `False` overrides it.

A missing required key raises `KeyError`. Every other problem raises `ValueError`.

### Helpers

| Function | What it does |
|---|---|
| `parse_time(value)` | Parses an ISO 8601 string and returns an aware UTC `datetime`. A string with no offset is rejected. |
| `clean_text(value)` | Strips accents (NFKD), turns `,` into `-`, and replaces any other character outside printable ASCII with a space. Newlines therefore become spaces. |
| `same_duration(sent, expires)` | Returns the `TTTT` purge time, rounded **up**: to 15-minute steps below 1 hour, then to 30-minute steps (47 CFR 11.31). For example, 47 min gives `0100` and 61 min gives `0130`. |
| `load_audio(value)` | Returns an `Audio` unchanged, or loads a WAV path. `None` stays `None`. |

## The SAME header

```
ZCZC-WXR-TOR-026073-026000+0100-3211500-        -
     │   │   │             │    │       └ LLLLLLLL station ID: 8 spaces (the encoder fills it in)
     │   │   │             │    └ JJJHHMM: day of year + UTC hour and minute of `sent`
     │   │   │             └ +TTTT purge time
     │   │   └ PSSCCC locations
     │   └ event
     └ originator
```

## Behavior changes from the original version

The rewrite produces the same `Alert` and payload bytes for valid input. It differs in these ways:

- If a language appears in more than one `<info>` block, the **first** block's text is now used. The old code used the last one. This makes the text come from the same block as the SAME metadata.
- A source label containing DEL (`0x7f`) or non-ASCII characters now raises a clear `ValueError`. Before, DEL was accepted and non-ASCII raised a `UnicodeEncodeError`.
- `EAN`/`EAT` are now rejected before any WAV files are read.
- `parse_cap()` was added so feed data can be parsed without writing it to disk.
- The alert dict now has `msg_type`, `sender`, `event`, `area_desc` and `block_channels` keys.
- A non-deliverable `msgType` now raises `NotDeliverable`. It is still a `ValueError`.
- The unused `json` import was removed.
