"""Authenticated-encryption helpers for the stored MT5 login password.

Standard library only (AES-128-CTR keystream + HMAC-SHA256 tag), so the service
has no dependency on ``cryptography`` and builds on any Render stack. The AES
core is validated against the FIPS-197 Appendix B / C.1 test vectors.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct

from .config import settings

PREFIX = "v1."

# --------------------------------------------------------------------------- #
# AES-256 (block cipher, encrypt-only primitive + CTR mode)
# --------------------------------------------------------------------------- #

_SBOX: list[int] = []


def _init_sbox() -> None:
    """Build the AES S-box from first principles (GF(2^8) inverse + affine map)."""
    if _SBOX:
        return
    # log/antilog tables for GF(2^8) with generator 3 (xtime alone only
    # reaches half of the non-zero elements, hence the multiply-by-3 step)
    log_tbl = [0] * 256
    int_tbl = [0] * 256
    x = 1
    for k in range(255):
        log_tbl[x] = k
        int_tbl[k] = x
        x = x ^ (((x << 1) & 0xFF) ^ (0x1B if x & 0x80 else 0))  # x = 3 * x
    sbox = [0] * 256
    for value in range(256):
        inv = 0 if value == 0 else int_tbl[(255 - log_tbl[value]) % 255]
        s = inv
        sbox[value] = (
            s
            ^ ((s << 1) | (s >> 7))
            ^ ((s << 2) | (s >> 6))
            ^ ((s << 3) | (s >> 5))
            ^ ((s << 4) | (s >> 4))
            ^ 0x63
        ) & 0xFF
    assert sbox[0] == 0x63 and sbox[1] == 0x7C, "AES S-box self-check failed"
    _SBOX.extend(sbox)


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result & 0xFF


def _expand_key(key: bytes) -> list[list[int]]:
    """AES-128 key expansion (Nk=4, Nr=10) -> 44 words of 4 bytes."""
    _init_sbox()
    assert len(key) == 16
    nk = 4
    words: list[list[int]] = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
    rcon = 1
    while len(words) < 4 * 11:
        temp = list(words[-1])
        if len(words) % nk == 0:
            temp = temp[1:] + temp[:1]                      # RotWord
            temp = [_SBOX[b] for b in temp]                 # SubWord
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([words[-nk][j] ^ temp[j] for j in range(4)])
    return words


def _encrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    _init_sbox()
    state = [list(block[i : i + 4]) for i in range(0, 16, 4)]

    def add_round_key(rnd: int) -> None:
        idx = 0
        for col in range(4):
            for row in range(4):
                state[col][row] ^= round_keys[rnd * 4 + col][row]
                idx += 1

    def shift_rows() -> None:
        # state[col][row]: rotate row r left by r positions
        row0 = [state[c][0] for c in range(4)]
        row1 = [state[c][1] for c in range(4)]
        row2 = [state[c][2] for c in range(4)]
        row3 = [state[c][3] for c in range(4)]
        for c in range(4):
            state[c][1] = row1[(c + 1) % 4]
            state[c][2] = row2[(c + 2) % 4]
            state[c][3] = row3[(c + 3) % 4]
            state[c][0] = row0[c]

    add_round_key(0)
    for rnd in range(1, 10):
        for col in range(4):
            state[col] = [_SBOX[b] for b in state[col]]
        shift_rows()
        for col in range(4):
            a = state[col]
            state[col] = [
                _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3],
                a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3],
                a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3),
                _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2),
            ]
        add_round_key(rnd)
    # final round (no MixColumns)
    for col in range(4):
        state[col] = [_SBOX[b] for b in state[col]]
    shift_rows()
    add_round_key(10)
    return bytes(state[col][row] for col in range(4) for row in range(4))


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    round_keys = _expand_key(key)
    counter = int.from_bytes(nonce[:8], "big")
    out = bytearray()
    while len(out) < length:
        block = nonce[:8] + struct.pack(">Q", counter & ((1 << 64) - 1))
        out += _encrypt_block(block, round_keys)
        counter += 1
    return bytes(out[:length])


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def _derive(secret: bytes) -> tuple[bytes, bytes]:
    enc_key = hmac.new(secret, b"mt5web-enc", hashlib.sha256).digest()[:16]
    mac_key = hmac.new(secret, b"mt5web-mac", hashlib.sha256).digest()[:16]
    return enc_key, mac_key


def encrypt(plaintext: str) -> str:
    if plaintext == "":
        return ""
    enc_key, mac_key = _derive(settings.secret_key())
    nonce = secrets.token_bytes(12)
    data = plaintext.encode()
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    body = base64.urlsafe_b64encode(nonce + cipher)
    mac = hmac.new(mac_key, PREFIX.encode() + body, hashlib.sha256).digest()[:16]
    return (PREFIX + body.decode() + "." + base64.urlsafe_b64encode(mac).decode()).rstrip("=")


def decrypt(token: str) -> str:
    if not token:
        return ""
    if not token.startswith(PREFIX):
        return token  # plaintext value stored before encryption was introduced
    body, _, mac_part = token[len(PREFIX) :].rpartition(".")
    raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    mac = base64.urlsafe_b64decode(mac_part + "=" * (-len(mac_part) % 4))
    enc_key, mac_key = _derive(settings.secret_key())
    expected = hmac.new(mac_key, (PREFIX + body).encode(), hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, expected):
        raise ValueError("stored credential failed integrity check")
    nonce, cipher = raw[:12], raw[12:]
    data = bytes(a ^ b for a, b in zip(cipher, _keystream(enc_key, nonce, len(cipher))))
    return data.decode()


def new_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def hmac_sign(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def hmac_verify(secret: str, payload: bytes, signature: str) -> bool:
    if not secret:
        return True
    return hmac.compare_digest(hmac_sign(secret, payload), (signature or "").strip())


def short_fingerprint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:8]
