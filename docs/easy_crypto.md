# `modules/easy_crypto.py`

This is a byte-oriented Python 3 port of `easy_crypto.pyc`, with the tables recovered from the appliance. It is used only to obfuscate the password during login. **Do not modify it, especially the tables.**

> **Security note:** this is obfuscation, not encryption. The key table is fixed and included in this repository, so anyone who captures a login packet can recover the password. Keep encoder control ports on a trusted network or VPN.

## Constants

| Name | Value | Meaning |
|---|---|---|
| `NUM_SHUFFLE_SEQS` | 4 | Number of shuffle sequences. |
| `SHUFFLES_PER_SEQ` | 32 | Positions in each sequence, which is also the maximum password length. |
| `SHUFFLE_SEQS` | 4×32 table | Each row gives the byte positions (1–63) where the password characters go. |
| `ENCRYPT_KEY_XOR` | 2048 bytes | Key stream table. |
| `ENCRYPT_KEY_IDX_MASK` | 1023 | The first index wraps within 0–1023. |
| `ENCRYPT_KEY2_IDX` / `ENCRYPT_KEY2_MAX` | 1024 / 2048 | The second index runs from 1024 to 2047. |

## Functions

### `encode_shuffled_bytes(seq_idx, input_string, trash=b'') -> bytes`

Builds a 64-byte block:

1. Byte 0 is `seq_idx`.
2. Bytes 1–63 are `trash[1:64]`, padded with zeros.
3. Password byte *n* goes at position `SHUFFLE_SEQS[seq_idx][n]`, for up to 32 bytes.
4. If the password is shorter than 32 bytes, a `0` terminator goes at the next sequence position.

If the input is empty or `seq_idx` is out of range, it returns `b''`.

`easyplus_protocol` uses `b'ebawehtnielbmigdnaerygdidsevotyhtilsehtdnagillirbsawt'` as the trash. That is the start of *Jabberwocky* ("'twas brillig and the slithy toves did gyre and gimble in the wabe") written backwards.

### `decode_shuffled_bytes(encoded) -> bytes`

Does the reverse. It reads byte 0 for the sequence (falling back to 0 if invalid) and collects bytes until the first `0`.

### `xor_encrypt_data_bytes(idx, data) -> bytes`

Uses two indexes into the key table, `i = idx & 1023` and `j = i + 1024`. Each output byte is `b ^ KEY[i] ^ KEY[j]`. After each byte, `i` advances and wraps within 0–1023, and `j` advances and wraps within 1024–2047.

`xor_decrypt_data_bytes` is the same function, since XOR undoes itself.

## How login uses it

```
block   = encode_shuffled_bytes(randbelow(4), password, JABBERWOCKY_REVERSED)
payload = xor_encrypt_data_bytes(offset, block)   # offset = randbelow(512)
packet  = build_easyplus_cmd(offset | 0x8000, LOGON_CMD, 0, payload)
```

The encoder reads `offset` from the `user` field to undo the XOR.
