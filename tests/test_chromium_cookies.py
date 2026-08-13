# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Pure-crypto tests for core/chromium_cookies.py (no Windows APIs touched)."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

from core import chromium_cookies as cc


def _wrap(content: bytes) -> bytes:
    """Blob with an empty header and the given content."""
    return struct.pack("<I", 0) + struct.pack("<I", len(content)) + content


# --- parse_app_bound_key_blob -------------------------------------------------


def test_parse_raw_32_byte_key():
    key = bytes(range(32))
    parsed = cc.parse_app_bound_key_blob(_wrap(key))
    assert parsed["flag"] == 0
    assert parsed["raw_key"] == key


def test_parse_flag1_real_chrome_vector():
    # From runassu/chrome_v20_decryption README (Chrome 130, flag 1).
    header = b"\x02" + b"C:\\Program Files\\Google\\Chrome"
    assert len(header) == 31
    iv = bytes.fromhex("cabf17e5f2f447b0e81b641b")
    ct = bytes.fromhex("f27c224966e25ffcedd2e0cfc04e1f21f61bc2daa2eb6f532c47d39e7b50e67f")
    tag = bytes.fromhex("4d5c343fe6eed94358919ed23ad89630")
    content = b"\x01" + iv + ct + tag
    blob = struct.pack("<I", len(header)) + header + struct.pack("<I", len(content)) + content

    parsed = cc.parse_app_bound_key_blob(blob)
    assert parsed["flag"] == 1
    assert parsed["iv"] == iv
    assert parsed["ciphertext"] == ct
    assert parsed["tag"] == tag


def test_parse_flag2_and_flag3_layouts():
    content2 = b"\x02" + bytes(12) + bytes(32) + bytes(16)
    parsed2 = cc.parse_app_bound_key_blob(_wrap(content2))
    assert parsed2["flag"] == 2
    assert len(parsed2["iv"]) == 12
    assert len(parsed2["ciphertext"]) == 32
    assert len(parsed2["tag"]) == 16

    content3 = b"\x03" + bytes(32) + bytes(12) + bytes(32) + bytes(16)
    parsed3 = cc.parse_app_bound_key_blob(_wrap(content3))
    assert parsed3["flag"] == 3
    assert len(parsed3["encrypted_aes_key"]) == 32
    assert len(parsed3["iv"]) == 12


def test_parse_rejects_unknown_shapes():
    with pytest.raises(ValueError):
        cc.parse_app_bound_key_blob(b"\x00\x00\x00\x00" + b"\x02\x00\x00\x00" + b"\x04" + b"abcd")
    with pytest.raises(ValueError):
        cc.parse_app_bound_key_blob(_wrap(b"\x09" + bytes(60)))
    with pytest.raises(ValueError):
        cc.parse_app_bound_key_blob(_wrap(b"\x01" + bytes(40)))


# --- derive_v20_master_key ----------------------------------------------------


def test_derive_flag1_real_vector():
    iv = bytes.fromhex("cabf17e5f2f447b0e81b641b")
    ct = bytes.fromhex("f27c224966e25ffcedd2e0cfc04e1f21f61bc2daa2eb6f532c47d39e7b50e67f")
    tag = bytes.fromhex("4d5c343fe6eed94358919ed23ad89630")
    expected = bytes.fromhex("6d296ee57a29256e745e262515971e66c198cd322ca69ffd57de15738bedcd6c")
    key = cc.derive_v20_master_key({"flag": 1, "iv": iv, "ciphertext": ct, "tag": tag})
    assert key == expected


def test_derive_flag2_roundtrip():
    master = bytes(range(32))
    iv = bytes(range(12))
    wrapped = ChaCha20Poly1305(cc._CHACHA20_KEY).encrypt(iv, master, None)
    key = cc.derive_v20_master_key(
        {"flag": 2, "iv": iv, "ciphertext": wrapped[:-16], "tag": wrapped[-16:]}
    )
    assert key == master


def test_derive_flag3_roundtrip():
    master = bytes(range(32))
    aes_key = bytes(range(1, 33))
    iv = bytes(range(11, 23))
    # Simulate the CNG output: the real aes_key XORed with the static XOR key.
    cng_output = bytes(a ^ b for a, b in zip(aes_key, cc._XOR_KEY))
    wrapped = AESGCM(aes_key).encrypt(iv, master, None)
    parsed = {
        "flag": 3,
        "encrypted_aes_key": b"fake-cng-ciphertext",
        "iv": iv,
        "ciphertext": wrapped[:-16],
        "tag": wrapped[-16:],
    }
    key = cc.derive_v20_master_key(parsed, cng_decrypt=lambda _data: cng_output)
    assert key == master


def test_derive_raw_key_passthrough():
    key = bytes(range(32))
    assert cc.derive_v20_master_key({"flag": 0, "raw_key": key}) == key


def test_derive_flag3_requires_cng():
    with pytest.raises(ValueError):
        cc.derive_v20_master_key(
            {"flag": 3, "encrypted_aes_key": b"x" * 32, "iv": b"1" * 12, "ciphertext": b"2" * 32, "tag": b"3" * 16}
        )


# --- decrypt_cookie_value -----------------------------------------------------


def test_decrypt_v10_without_domain_hash():
    key = bytes(range(32))
    plain = b"session-token-123"
    iv = os.urandom(12)
    wrapped = AESGCM(key).encrypt(iv, plain, None)
    value = b"v10" + iv + wrapped
    assert cc.decrypt_cookie_value(value, v10_key=key, strip_domain_hash=False) == plain


def test_decrypt_v10_strips_domain_hash():
    key = bytes(range(32))
    plain = b"\x00" * 32 + b"real-value"
    iv = os.urandom(12)
    wrapped = AESGCM(key).encrypt(iv, plain, None)
    value = b"v10" + iv + wrapped
    assert cc.decrypt_cookie_value(value, v10_key=key, strip_domain_hash=True) == b"real-value"


def test_decrypt_v20_strips_domain_hash():
    key = bytes(range(32))
    plain = b"\x11" * 32 + b"the-value"
    iv = os.urandom(12)
    wrapped = AESGCM(key).encrypt(iv, plain, None)
    value = b"v20" + iv + wrapped
    assert cc.decrypt_cookie_value(value, v20_key=key, strip_domain_hash=True) == b"the-value"


def test_decrypt_unknown_prefix_and_missing_keys():
    assert cc.decrypt_cookie_value(b"v99" + os.urandom(32)) is None
    assert cc.decrypt_cookie_value(b"v10" + os.urandom(32), v20_key=bytes(32)) is None
    assert cc.decrypt_cookie_value(b"", v10_key=bytes(32)) == b""


def test_decrypt_bad_tag_returns_none():
    key = bytes(range(32))
    iv = os.urandom(12)
    value = b"v10" + iv + os.urandom(32)
    assert cc.decrypt_cookie_value(value, v10_key=key) is None


# --- key cache helpers (non-Windows: stored/loaded as plain base64) -----------


def test_key_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_keys_path", lambda: str(tmp_path / "keys.json"))
    fingerprint = "abc123"
    key = bytes(range(32))
    cc._store_cached_v20_key(fingerprint, key)
    assert cc._load_cached_v20_key(fingerprint) == key
    assert cc._load_cached_v20_key("missing") is None
