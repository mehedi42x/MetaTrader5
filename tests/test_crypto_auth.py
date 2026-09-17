"""Crypto + token tests. AES-128 is checked against the FIPS-197 vectors."""

from __future__ import annotations

import pytest


def test_aes_matches_fips197_vectors(isolated_env):
    from mt5web.crypto import _encrypt_block, _expand_key, _init_sbox

    _init_sbox()
    from mt5web import crypto

    sbox = crypto._SBOX
    assert sbox[:6] == [0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B]
    assert len(set(sbox)) == 256, "S-box must be a permutation"

    # FIPS-197 Appendix C.1: AES-128 encrypt of 00112233..eeff
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    rk = _expand_key(key)
    out = _encrypt_block(bytes.fromhex("00112233445566778899aabbccddeeff"), rk)
    assert out.hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"


def test_encrypt_decrypt_roundtrip_and_tamper(isolated_env):
    from mt5web.crypto import decrypt, encrypt

    secret = "MT5-password-ünïcode-123"
    token = encrypt(secret)
    assert token.startswith("v1.")
    assert secret not in token
    assert decrypt(token) == secret
    assert decrypt("") == ""
    assert decrypt("plaintext-value") == "plaintext-value"  # legacy values pass through

    tampered = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    with pytest.raises(ValueError):
        decrypt(tampered)


def test_passcodes_and_tokens(isolated_env):
    from mt5web import auth

    assert auth.needs_setup()
    auth.set_passcode("hunter-2")
    assert auth.verify_passcode("hunter-2")
    assert not auth.verify_passcode("hunter-3")

    tok = auth.make_token("owner", ttl=60)
    payload = auth.verify_token(tok)
    assert payload and payload["r"] == "owner"
    assert auth.verify_token(tok[:-2] + "zz") is None
    assert auth.verify_token("") is None

    expired = auth.make_token("owner", ttl=-5)
    assert auth.verify_token(expired) is None


def test_bridge_key_generation_and_rotation(isolated_env):
    from mt5web import auth

    key = auth.ensure_bridge_key()
    assert len(key) >= 16
    assert auth.verify_bridge_key(key)
    assert not auth.verify_bridge_key(key + "x")
    fresh = auth.rotate_bridge_key()
    assert fresh != key
    assert auth.verify_bridge_key(fresh)
