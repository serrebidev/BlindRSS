# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Harvest cookies from Chromium-family browsers, including App-Bound (v20).

Chromium keeps cookies in a per-profile SQLite database (``Network/Cookies``)
whose values are encrypted. There are two encryption generations:

* **v10** (the pre-2024 default) — AES-256-GCM with a key stored in the
  profile's ``Local State`` under ``os_crypt.encrypted_key``. On Windows that
  key is itself DPAPI-encrypted under the *user's* account, so reading it
  needs no special privilege. On macOS it derives from the Keychain and on
  Linux from the ``peanuts`` fallback password.

* **v20** (App-Bound Encryption, Chromium 127+) — AES-256-GCM with a key
  bound to the browser *and the machine*. The ``app_bound_encrypted_key`` in
  ``Local State`` is encrypted twice: once with the **SYSTEM** DPAPI key and
  once with the **user's** DPAPI key, and on Chrome the inner blob is wrapped
  once more (flag 1/2/3, see below). Decrypting it therefore requires running
  as SYSTEM for the first DPAPI step — which Windows only allows after a UAC
  elevation. BlindRSS performs that step once per key rotation in a short-lived
  elevated helper process, caches the resulting 32-byte master key
  re-encrypted under the user's DPAPI, and then decrypts cookies with no
  further prompts. All keys needing derivation are batched into a single
  elevation, so a machine with several Chromium browsers prompts exactly once.

The elevation itself is made silent after a one-time setup: a scheduled task
(``--blindrss-elevated-helper``, "BlindRSS Elevated Helper") is registered
with RunLevel=Highest on first use (one UAC prompt) and thereafter run with no
prompt. The same helper reads a running browser's exclusively-locked
``Cookies`` database via a Volume Shadow Copy snapshot (``--blindrss-chromium-vss-copy`` is the prompting runas fallback).

The wire format (Chromium ``elevation_service`` ``DecryptData``/``EncryptData``)
is::

    [uint32 path_len][path_bytes][uint32 content_len][content]

After the double DPAPI unwrap, ``content`` is one of:

* 32 raw bytes — non-Google-Chrome Chromium builds (Edge, Brave, Opera,
  Vivaldi) return the master key directly (no ``PostProcessData`` step).
* 61 bytes ``[flag=1|iv(12)|ciphertext(32)|tag(16)]`` — Chrome 127-132,
  unwrapped with a static AES-256-GCM key.
* 61 bytes ``[flag=2|iv(12)|ciphertext(32)|tag(16)]`` — Chrome 133+ on
  non-domain-joined hosts, unwrapped with a static ChaCha20-Poly1305 key.
* 93 bytes ``[flag=3|encrypted_aes_key(32)|iv(12)|ciphertext(32)|tag(16)]`` —
  Chrome 137+ on domain-joined hosts. ``encrypted_aes_key`` is decrypted with
  the machine CNG key ``Google Chromekey1`` (as SYSTEM), XORed with a static
  key, then used to AES-GCM-unwrap the master key.

Cookie values are ``"v10"|"v20" + iv(12) + ciphertext + tag(16)``. Since DB
version 24 the plaintext carries a 32-byte SHA-256(domain) prefix that must be
stripped after decryption (always for v20, and for v10 on modern DBs).

The crypto is pure and unit-testable (``parse_app_bound_key_blob``,
``derive_v20_master_key`` and ``decrypt_cookie_value`` touch no OS API); the
DPAPI/CNG/impersonation/elevation machinery is Windows-only and guarded at call
time.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time

log = logging.getLogger(__name__)

# --- Static keys (from Chromium elevation_service / PostProcessData) ---------

_AES_GCM_KEY = bytes.fromhex(
    "B31C6E241AC846728DA9C1FAC4936651CFFB944D143AB816276BCC6DA0284787"
)
_CHACHA20_KEY = bytes.fromhex(
    "E98F37D7F4E1FA433D19304DC2258042090E2D1D7EEA7670D41F738D08729660"
)
_XOR_KEY = bytes.fromhex(
    "CCF8A1CEC56605B8517552BA1A2D061C03A29E90274FB2FCF59BA4B75C392390"
)
_CNG_KEY_NAME = "Google Chromekey1"
_CNG_PROVIDER_NAME = "Microsoft Software Key Storage Provider"

# 1601-01-01 (NT epoch) -> 1970-01-01 (Unix epoch), in seconds.
_NT_TO_UNIX_OFFSET = 11644473600

_DOMAIN_HASH_LEN = 32

# Hide the console of child console apps (schtasks/powershell/icacls) so no
# cmd window flashes when BlindRSS itself has no console. 0 on POSIX.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_HELPER_FLAG = "--blindrss-chromium-key-helper"
_VSS_HELPER_FLAG = "--blindrss-chromium-vss-copy"
_ELEVATED_HELPER_FLAG = "--blindrss-elevated-helper"

# ---------------------------------------------------------------------------
# Pure crypto (no OS calls)
# ---------------------------------------------------------------------------


def _aesgcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key)


def _chacha20(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    return ChaCha20Poly1305(key)


def parse_app_bound_key_blob(blob: bytes) -> dict:
    """Parse a double-DPAPI-decrypted app-bound key blob.

    Returns a dict with keys ``flag``, ``iv``, ``ciphertext``, ``tag``,
    ``encrypted_aes_key`` (flag 3 only) and ``raw_key`` (non-Chrome only).
    Raises ValueError for anything that does not match a known layout, so a
    future Chromium format change fails loudly instead of producing garbage.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise ValueError("app-bound key blob is not bytes")
    blob = bytes(blob)
    if len(blob) < 8:
        raise ValueError("app-bound key blob too short")
    header_len = struct.unpack("<I", blob[0:4])[0]
    if header_len > len(blob) - 8:
        raise ValueError("app-bound key blob header length overflows")
    content_off = 4 + header_len
    content_len = struct.unpack("<I", blob[content_off:content_off + 4])[0]
    content = blob[content_off + 4:content_off + 4 + content_len]
    if header_len + content_len + 8 != len(blob):
        raise ValueError("app-bound key blob length mismatch")

    if len(content) == 32:
        # Non-Google-Chrome Chromium: the master key itself.
        return {"flag": 0, "raw_key": content}

    if not content:
        raise ValueError("app-bound key blob has empty content")
    flag = content[0]
    if flag in (1, 2):
        if len(content) != 61:
            raise ValueError(
                f"app-bound key flag {flag} content is {len(content)} bytes, expected 61"
            )
        return {
            "flag": flag,
            "iv": content[1:13],
            "ciphertext": content[13:45],
            "tag": content[45:61],
        }
    if flag == 3:
        if len(content) != 93:
            raise ValueError(
                f"app-bound key flag 3 content is {len(content)} bytes, expected 93"
            )
        return {
            "flag": flag,
            "encrypted_aes_key": content[1:33],
            "iv": content[33:45],
            "ciphertext": content[45:77],
            "tag": content[77:93],
        }
    raise ValueError(f"unsupported app-bound key flag {flag}")


def derive_v20_master_key(parsed: dict, cng_decrypt=None) -> bytes:
    """Derive the 32-byte v20 master key from a parsed app-bound key blob.

    ``cng_decrypt`` is a callable ``bytes -> bytes`` that decrypts the flag-3
    ``encrypted_aes_key`` with the machine CNG key (must run as SYSTEM). It is
    only required for flag 3.
    """
    if parsed.get("flag") == 0:
        key = parsed.get("raw_key") or b""
        if len(key) != 32:
            raise ValueError("raw app-bound master key is not 32 bytes")
        return key
    flag = parsed.get("flag")
    iv = parsed.get("iv")
    ciphertext = parsed.get("ciphertext")
    tag = parsed.get("tag")
    if not iv or not ciphertext or not tag:
        raise ValueError("incomplete app-bound key blob")
    if flag == 1:
        return _aesgcm(_AES_GCM_KEY).decrypt(iv, ciphertext + tag, None)
    if flag == 2:
        return _chacha20(_CHACHA20_KEY).decrypt(iv, ciphertext + tag, None)
    if flag == 3:
        if cng_decrypt is None:
            raise ValueError("CNG decryption is required for flag-3 app-bound keys")
        encrypted_aes_key = parsed.get("encrypted_aes_key")
        if not encrypted_aes_key:
            raise ValueError("missing encrypted_aes_key")
        decrypted_aes_key = bytes(cng_decrypt(encrypted_aes_key))
        xored = bytes(a ^ b for a, b in zip(decrypted_aes_key, _XOR_KEY))
        if len(xored) != 32:
            raise ValueError(f"CNG-derived AES key is {len(xored)} bytes, expected 32")
        return _aesgcm(xored).decrypt(iv, ciphertext + tag, None)
    raise ValueError(f"unsupported app-bound key flag {flag}")


def decrypt_cookie_value(
    encrypted_value: bytes,
    *,
    v10_key=None,
    v20_key=None,
    strip_domain_hash: bool = True,
):
    """Decrypt one Chromium ``encrypted_value`` blob; returns bytes or None.

    Returns None when the value cannot be decrypted (unknown prefix, missing
    key, bad tag), so callers can skip the row rather than crash. When
    ``strip_domain_hash`` is true the 32-byte SHA-256(domain) prefix added by
    cookie-DB version 24 is dropped from the plaintext.
    """
    if not encrypted_value:
        return b""
    prefix = encrypted_value[:3]
    if prefix not in (b"v10", b"v20"):
        return None
    if len(encrypted_value) < 3 + 12 + 16 + 1:
        return None
    iv = encrypted_value[3:15]
    ciphertext = encrypted_value[15:-16]
    tag = encrypted_value[-16:]
    try:
        if prefix == b"v10":
            if not v10_key:
                return None
            plain = _aesgcm(v10_key).decrypt(iv, ciphertext + tag, None)
        else:
            if not v20_key:
                return None
            plain = _aesgcm(v20_key).decrypt(iv, ciphertext + tag, None)
    except Exception:
        log.debug("Cookie decryption failed (tag mismatch or bad key)", exc_info=True)
        return None
    if strip_domain_hash and len(plain) > _DOMAIN_HASH_LEN:
        plain = plain[_DOMAIN_HASH_LEN:]
    return plain


# ---------------------------------------------------------------------------
# Windows OS plumbing (DPAPI, SYSTEM impersonation, CNG, elevation)
# ---------------------------------------------------------------------------


def _is_windows() -> bool:
    return sys.platform.startswith("win")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _crypt32():
    lib = ctypes.windll.crypt32
    if not getattr(lib.CryptUnprotectData, "_blindrss_argtypes", False):
        lib.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        lib.CryptUnprotectData.restype = ctypes.wintypes.BOOL
        lib.CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            ctypes.c_wchar_p,
            ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        lib.CryptProtectData.restype = ctypes.wintypes.BOOL
        lib.CryptUnprotectData._blindrss_argtypes = True
    return lib


def _kernel32():
    lib = ctypes.windll.kernel32
    if not getattr(lib.LocalFree, "_blindrss_argtypes", False):
        HANDLE = ctypes.c_void_p
        wintypes = ctypes.wintypes
        lib.LocalFree.argtypes = [HANDLE]
        lib.LocalFree.restype = HANDLE
        lib.CloseHandle.argtypes = [HANDLE]
        lib.CloseHandle.restype = wintypes.BOOL
        # Handle-returning APIs default to a 32-bit c_int restype in ctypes, so
        # on 64-bit Windows a snapshot/process handle above 2**32 is silently
        # truncated. Fix the signatures once so every caller is safe.
        lib.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        lib.OpenProcess.restype = HANDLE
        lib.GetCurrentProcess.restype = HANDLE
        lib.WaitForSingleObject.argtypes = [HANDLE, wintypes.DWORD]
        lib.WaitForSingleObject.restype = wintypes.DWORD
        lib.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        lib.CreateToolhelp32Snapshot.restype = HANDLE
        lib.LocalFree._blindrss_argtypes = True
    return lib


def _dpapi_unprotect(blob: bytes) -> bytes:
    """CryptUnprotectData under the current thread's token (user or SYSTEM)."""
    if not _is_windows():
        raise OSError("DPAPI is Windows-only")
    crypt32 = _crypt32()
    kernel32 = _kernel32()
    in_blob = _DATA_BLOB(
        len(blob),
        ctypes.cast(ctypes.create_string_buffer(blob), ctypes.POINTER(ctypes.c_char)),
    )
    out_blob = _DATA_BLOB()
    desc = ctypes.c_wchar_p()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), ctypes.byref(desc), None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError(f"DPAPI CryptUnprotectData failed ({ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _dpapi_protect(blob: bytes, description: str = "") -> bytes:
    """CryptProtectData under the current user (for at-rest key caching)."""
    if not _is_windows():
        return blob
    crypt32 = _crypt32()
    kernel32 = _kernel32()
    in_blob = _DATA_BLOB(
        len(blob),
        ctypes.cast(ctypes.create_string_buffer(blob), ctypes.POINTER(ctypes.c_char)),
    )
    out_blob = _DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), description or None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError(f"DPAPI CryptProtectData failed ({ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


# Token/privilege access-right constants.
_SE_DEBUG_NAME = "SeDebugPrivilege"
_TOKEN_ADJUST_PRIVILEGES = 0x0020
_TOKEN_QUERY = 0x0008
_TOKEN_DUPLICATE = 0x0002
_TOKEN_IMPERSONATE = 0x0004
_SE_PRIVILEGE_ENABLED = 0x00000002
_PROCESS_QUERY_INFORMATION = 0x0400
_MAXIMUM_ALLOWED = 0x02000000
_SECURITY_IMPERSONATION = 2
_TOKEN_IMPERSONATION = 2
_TH32CS_SNAPPROCESS = 0x00000002


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.wintypes.DWORD), ("HighPart", ctypes.c_long)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", _LUID), ("Attributes", ctypes.wintypes.DWORD)]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [
        ("PrivilegeCount", ctypes.wintypes.DWORD),
        ("Privileges", _LUID_AND_ATTRIBUTES * 1),
    ]


class _PROCESSENTRY32(ctypes.Structure):
    """PROCESSENTRY32W — matches the wide Process32FirstW/NextW calls below."""

    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _advapi32():
    """advapi32 with 64-bit-safe handle signatures (see ``_kernel32`` note)."""
    lib = ctypes.windll.advapi32
    if not getattr(lib.OpenProcessToken, "_blindrss_argtypes", False):
        HANDLE = ctypes.c_void_p
        lib.OpenProcessToken.argtypes = [
            HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        ]
        lib.OpenProcessToken.restype = ctypes.wintypes.BOOL
        lib.LookupPrivilegeValueW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(_LUID),
        ]
        lib.LookupPrivilegeValueW.restype = ctypes.wintypes.BOOL
        lib.AdjustTokenPrivileges.argtypes = [
            HANDLE,
            ctypes.wintypes.BOOL,
            ctypes.POINTER(_TOKEN_PRIVILEGES),
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.AdjustTokenPrivileges.restype = ctypes.wintypes.BOOL
        lib.DuplicateTokenEx.argtypes = [
            HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        ]
        lib.DuplicateTokenEx.restype = ctypes.wintypes.BOOL
        lib.SetThreadToken.argtypes = [
            ctypes.POINTER(ctypes.wintypes.HANDLE),
            HANDLE,
        ]
        lib.SetThreadToken.restype = ctypes.wintypes.BOOL
        lib.GetTokenInformation.argtypes = [
            HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        lib.GetTokenInformation.restype = ctypes.wintypes.BOOL
        lib.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.ConvertSidToStringSidW.restype = ctypes.wintypes.BOOL
        lib.OpenProcessToken._blindrss_argtypes = True
    return lib


def _list_processes():
    """Yield ``(pid, exe_name)`` for every running process."""
    kernel32 = _kernel32()
    if not getattr(kernel32.Process32FirstW, "_blindrss_argtypes", False):
        kernel32.Process32FirstW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_PROCESSENTRY32),
        ]
        kernel32.Process32FirstW.restype = ctypes.wintypes.BOOL
        kernel32.Process32NextW.argtypes = kernel32.Process32FirstW.argtypes
        kernel32.Process32NextW.restype = ctypes.wintypes.BOOL
        kernel32.Process32FirstW._blindrss_argtypes = True
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                yield int(entry.th32ProcessID), str(entry.szExeFile or "")
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)


# TOKEN_INFORMATION_CLASS TokenUser.
_TOKEN_USER = 1
_SYSTEM_SID = "S-1-5-18"


def _token_is_system(token) -> bool:
    """True when ``token`` belongs to the local SYSTEM account (S-1-5-18)."""
    advapi32 = _advapi32()
    kernel32 = _kernel32()
    needed = ctypes.wintypes.DWORD(0)
    advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
    if not needed.value:
        return False
    buf = ctypes.create_string_buffer(needed.value)
    if not advapi32.GetTokenInformation(token, _TOKEN_USER, buf, needed.value, ctypes.byref(needed)):
        return False
    # TOKEN_USER begins with SID_AND_ATTRIBUTES { PSID Sid; DWORD Attributes; }.
    sid_addr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_size_t)).contents.value
    if not sid_addr:
        return False
    sid_ptr = ctypes.c_void_p()
    if not advapi32.ConvertSidToStringSidW(sid_addr, ctypes.byref(sid_ptr)):
        return False
    try:
        return ctypes.wstring_at(sid_ptr.value) == _SYSTEM_SID
    finally:
        kernel32.LocalFree(sid_ptr)


def _open_system_dup_token():
    """Return ``(dup_token_handle, source_name, source_pid)`` for a SYSTEM
    impersonation token, or raise OSError.

    lsass.exe/csrss.exe are PPL-protected on modern Windows, so
    ``SeDebugPrivilege`` alone cannot open them; we prefer the non-protected
    SYSTEM processes (winlogon, services, spoolsv, svchost) and verify the SID
    before duplicating.
    """
    kernel32 = _kernel32()
    advapi32 = _advapi32()
    priority = (
        "winlogon.exe",
        "services.exe",
        "spoolsv.exe",
        "svchost.exe",
        "lsass.exe",
        "csrss.exe",
        "wininit.exe",
        "fontdrvhost.exe",
    )
    procs = list(_list_processes())
    by_name = {}
    for pid, name in procs:
        by_name.setdefault(name.lower(), []).append(pid)
    ordered = []
    for name in priority:
        ordered.extend((name, pid) for pid in by_name.pop(name.lower(), []))
    # Any remaining process as a last resort (the SID check keeps it SYSTEM-only).
    ordered.extend((name, pid) for pid, name in procs if name.lower() in by_name)

    errors = []
    for name, pid in ordered:
        h = kernel32.OpenProcess(_PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            errors.append(f"{name}:{pid} open err {ctypes.GetLastError()}")
            continue
        token = ctypes.wintypes.HANDLE()
        try:
            if not advapi32.OpenProcessToken(
                h,
                _TOKEN_DUPLICATE | _TOKEN_QUERY | _TOKEN_IMPERSONATE,
                ctypes.byref(token),
            ):
                errors.append(f"{name}:{pid} token err {ctypes.GetLastError()}")
                continue
            if not _token_is_system(token):
                errors.append(f"{name}:{pid} not SYSTEM")
                continue
            dup = ctypes.wintypes.HANDLE()
            if not advapi32.DuplicateTokenEx(
                token,
                _MAXIMUM_ALLOWED,
                None,
                _SECURITY_IMPERSONATION,
                _TOKEN_IMPERSONATION,
                ctypes.byref(dup),
            ):
                errors.append(f"{name}:{pid} dup err {ctypes.GetLastError()}")
                continue
            return dup, name, pid
        finally:
            if token:
                kernel32.CloseHandle(token)
            kernel32.CloseHandle(h)
    raise OSError(
        "Could not obtain a SYSTEM token from any process: " + "; ".join(errors[:8])
    )


class _SystemImpersonation:
    """Context manager that impersonates a SYSTEM token.

    Requires an elevated (admin) process so SeDebugPrivilege can be enabled.
    Used for the SYSTEM DPAPI step and the flag-3 CNG decryption, matching how
    the browser's own elevation service reaches the SYSTEM key store.
    """

    def __init__(self):
        self._dup_token = None
        self._handles = []

    def __enter__(self):
        if not _is_windows():
            return self
        try:
            self._enter_impl()
        except Exception:
            # A failure mid-dance must not leave the thread impersonating SYSTEM.
            self._revert()
            raise
        return self

    def _enter_impl(self):
        kernel32 = _kernel32()
        advapi32 = _advapi32()

        current = ctypes.wintypes.HANDLE()
        advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            _TOKEN_ADJUST_PRIVILEGES | _TOKEN_QUERY,
            ctypes.byref(current),
        )
        self._handles.append(current)
        luid = _LUID()
        if advapi32.LookupPrivilegeValueW(None, _SE_DEBUG_NAME, ctypes.byref(luid)):
            tp = _TOKEN_PRIVILEGES()
            tp.PrivilegeCount = 1
            tp.Privileges[0].Luid = luid
            tp.Privileges[0].Attributes = _SE_PRIVILEGE_ENABLED
            advapi32.AdjustTokenPrivileges(current, False, ctypes.byref(tp), 0, None, None)

        dup, source_name, source_pid = _open_system_dup_token()
        self._handles.append(dup)
        self._dup_token = dup
        log.debug("Impersonating SYSTEM via %s (pid %s)", source_name, source_pid)

        if not advapi32.SetThreadToken(None, dup):
            raise OSError(f"SetThreadToken failed ({ctypes.GetLastError()})")

    def _revert(self):
        advapi32 = _advapi32()
        kernel32 = _kernel32()
        try:
            advapi32.SetThreadToken(None, None)
        except Exception:
            pass
        for handle in self._handles:
            if handle:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
        self._handles = []
        self._dup_token = None

    def __exit__(self, exc_type, exc, tb):
        if not _is_windows():
            return False
        self._revert()
        return False


def _cng_decrypt(encrypted_aes_key: bytes) -> bytes:
    """NCryptDecrypt the flag-3 ``encrypted_aes_key`` with ``Google Chromekey1``."""
    if not _is_windows():
        raise OSError("CNG is Windows-only")
    ncrypt = ctypes.WinDLL("ncrypt.dll")
    ncrypt.NCryptOpenStorageProvider.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_wchar_p,
        ctypes.wintypes.DWORD,
    ]
    ncrypt.NCryptOpenStorageProvider.restype = ctypes.c_long
    ncrypt.NCryptOpenKey.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_wchar_p,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
    ]
    ncrypt.NCryptOpenKey.restype = ctypes.c_long
    ncrypt.NCryptDecrypt.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.wintypes.DWORD,
    ]
    ncrypt.NCryptDecrypt.restype = ctypes.c_long
    ncrypt.NCryptFreeObject.argtypes = [ctypes.c_void_p]
    ncrypt.NCryptFreeObject.restype = ctypes.c_long

    provider = ctypes.c_void_p()
    status = ncrypt.NCryptOpenStorageProvider(ctypes.byref(provider), _CNG_PROVIDER_NAME, 0)
    if status != 0:
        raise OSError(f"NCryptOpenStorageProvider failed ({status:#x})")
    key = ctypes.c_void_p()
    try:
        status = ncrypt.NCryptOpenKey(provider, ctypes.byref(key), _CNG_KEY_NAME, 0, 0)
        if status != 0:
            raise OSError(f"NCryptOpenKey('{_CNG_KEY_NAME}') failed ({status:#x})")
        try:
            in_buf = (ctypes.c_ubyte * len(encrypted_aes_key)).from_buffer_copy(encrypted_aes_key)
            result_len = ctypes.wintypes.DWORD(0)
            # NCRYPT_SILENT_FLAG = 0x40 (no UI).
            status = ncrypt.NCryptDecrypt(
                key, in_buf, len(in_buf), None, None, 0, ctypes.byref(result_len), 0x40
            )
            if status != 0:
                raise OSError(f"NCryptDecrypt (size) failed ({status:#x})")
            out_buf = (ctypes.c_ubyte * result_len.value)()
            status = ncrypt.NCryptDecrypt(
                key, in_buf, len(in_buf), None, out_buf, len(out_buf), ctypes.byref(result_len), 0x40
            )
            if status != 0:
                raise OSError(f"NCryptDecrypt failed ({status:#x})")
            return bytes(out_buf[: result_len.value])
        finally:
            ncrypt.NCryptFreeObject(key)
    finally:
        ncrypt.NCryptFreeObject(provider)


def derive_master_key_from_app_bound_key(app_bound_key_b64: str) -> bytes:
    """Derive the v20 master key from a base64 ``app_bound_encrypted_key``.

    Runs the SYSTEM DPAPI step (and flag-3 CNG) under a SYSTEM impersonation,
    the user DPAPI step under the user token. Windows-only.
    """
    if not _is_windows():
        raise OSError("App-Bound Encryption is Windows-only")
    raw = base64.b64decode(app_bound_key_b64)
    if raw[:4] != b"APPB":
        raise ValueError("app-bound key does not begin with the APPB marker")
    encrypted = raw[4:]

    with _SystemImpersonation():
        system_decrypted = _dpapi_unprotect(encrypted)
    user_decrypted = _dpapi_unprotect(system_decrypted)

    parsed = parse_app_bound_key_blob(user_decrypted)

    def _cng(data):
        with _SystemImpersonation():
            return _cng_decrypt(data)

    return derive_v20_master_key(parsed, cng_decrypt=_cng)


# --- Elevation -----------------------------------------------------------------


class _SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.wintypes.HWND),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
    ]


_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
_ERROR_CANCELLED = 1223


def _run_elevated_helper_batch_runas(app_bound_keys_b64: list) -> list:
    """Runas fallback: launch this app elevated once to derive v20 master keys.

    ``app_bound_keys_b64`` are base64 ``app_bound_encrypted_key`` values, one
    per line in the helper's input file. Returns a list of master-key bytes in
    the same order (or None for a key the helper could not derive). Raises
    OSError when the UAC prompt is cancelled or the helper fails outright.
    """
    if not app_bound_keys_b64:
        return []
    if not _is_windows():
        raise OSError("Elevation is Windows-only")

    exe = _no_console_interpreter()
    args = [_HELPER_FLAG]
    if not getattr(sys, "frozen", False):
        # `sys.executable` is the interpreter, so the script must come first:
        # `python main.py --blindrss-chromium-key-helper ...` (a flag placed
        # before the script would be parsed as an interpreter option).
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
        )
        args.insert(0, script)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", prefix="blindrss-abk-", delete=False, encoding="ascii"
    ) as fh:
        fh.write("\n".join(app_bound_keys_b64))
        input_path = fh.name
    output_fd, output_path = tempfile.mkstemp(prefix="blindrss-v20-", suffix=".txt")
    os.close(output_fd)
    try:
        args += ["--input", input_path, "--output", output_path]
        params = subprocess.list2cmdline([str(a) for a in args])

        shell32 = ctypes.windll.shell32
        kernel32 = _kernel32()
        sei = _SHELLEXECUTEINFO()
        sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFO)
        sei.fMask = _SEE_MASK_NOCLOSEPROCESS
        sei.lpVerb = "runas"
        sei.lpFile = exe
        sei.lpParameters = params
        sei.nShow = _SW_HIDE
        ctypes.set_last_error(0)
        ok = shell32.ShellExecuteExW(ctypes.byref(sei))
        if not ok:
            code = ctypes.get_last_error() or ctypes.GetLastError()
            if code == _ERROR_CANCELLED:
                raise OSError("User cancelled the permission prompt", _ERROR_CANCELLED)
            raise OSError(f"ShellExecuteEx runas failed ({code})")
        h_process = sei.hProcess
        deadline = time.monotonic() + 120.0
        # Some Windows versions do not return a usable hProcess for "runas", so
        # poll the output file as well instead of relying on the wait alone.
        while time.monotonic() < deadline:
            if h_process and kernel32.WaitForSingleObject(h_process, 1000) == 0x00000000:
                break
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                break
            time.sleep(0.25)
        if h_process:
            try:
                kernel32.CloseHandle(h_process)
            except Exception:
                pass

        try:
            with open(output_path, "r", encoding="ascii") as fh:
                lines = [line.rstrip("\n") for line in fh.read().splitlines()]
        except OSError as exc:
            raise OSError(f"Elevated helper produced no result: {exc}") from exc

        results = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("ERROR:"):
                results.append(None)
                continue
            try:
                key = base64.b64decode(line)
            except Exception:
                results.append(None)
                continue
            results.append(key if len(key) == 32 else None)
        # Pad/truncate so the length always matches the request count.
        if len(results) < len(app_bound_keys_b64):
            results.extend([None] * (len(app_bound_keys_b64) - len(results)))
        return results[: len(app_bound_keys_b64)]
    finally:
        for path in (input_path, output_path):
            try:
                os.remove(path)
            except OSError:
                pass


def _is_locked_file(path: str) -> bool:
    """True when the file exists but cannot be opened for reading — the
    exclusive ``dwShareMode=0`` lock a running Chromium browser holds on its
    ``Cookies`` database."""
    if not path:
        return False
    try:
        with open(path, "rb") as fh:
            fh.read(1)
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _run_elevated_vss_copy_runas(copy_paths):
    """Runas fallback: copy locked files out via Volume Shadow Copy.

    Returns ``(staged_map, staging_dir)`` where ``staged_map`` is
    ``{index: staged_path}`` and ``staging_dir`` must be removed by the caller
    once the staged files have been consumed. Raises OSError when the UAC
    prompt is cancelled or the helper fails outright.
    """
    if not copy_paths or not _is_windows():
        return {}, None
    exe = _no_console_interpreter()
    args = [_VSS_HELPER_FLAG]
    if not getattr(sys, "frozen", False):
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
        )
        args.insert(0, script)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", prefix="blindrss-vss-src-", delete=False, encoding="utf-8"
    ) as fh:
        fh.write("\n".join(copy_paths))
        input_path = fh.name
    staging_dir = tempfile.mkdtemp(prefix="blindrss-vss-stage-")
    manifest_path = os.path.join(staging_dir, "manifest.txt")
    try:
        args += ["--input", input_path, "--output-dir", staging_dir, "--manifest", manifest_path]
        params = subprocess.list2cmdline([str(a) for a in args])

        shell32 = ctypes.windll.shell32
        kernel32 = _kernel32()
        sei = _SHELLEXECUTEINFO()
        sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFO)
        sei.fMask = _SEE_MASK_NOCLOSEPROCESS
        sei.lpVerb = "runas"
        sei.lpFile = exe
        sei.lpParameters = params
        sei.nShow = _SW_HIDE
        ctypes.set_last_error(0)
        ok = shell32.ShellExecuteExW(ctypes.byref(sei))
        if not ok:
            code = ctypes.get_last_error() or ctypes.GetLastError()
            if code == _ERROR_CANCELLED:
                raise OSError("User cancelled the permission prompt", _ERROR_CANCELLED)
            raise OSError(f"ShellExecuteEx runas failed ({code})")
        h_process = sei.hProcess
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline:
            if h_process and kernel32.WaitForSingleObject(h_process, 1000) == 0x00000000:
                break
            if os.path.isfile(manifest_path) and os.path.getsize(manifest_path) > 0:
                break
            time.sleep(0.25)
        if h_process:
            try:
                kernel32.CloseHandle(h_process)
            except Exception:
                pass

        staged_map = {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                for index, line in enumerate(fh.read().splitlines()):
                    line = line.strip()
                    if line and not line.startswith("ERROR:"):
                        staged_map[index] = line
        except OSError as exc:
            raise OSError(f"Elevated VSS helper produced no result: {exc}") from exc
        return staged_map, staging_dir
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    finally:
        try:
            os.remove(input_path)
        except OSError:
            pass


def run_key_helper_cli(argv) -> int:
    """Entry point for the elevated ``--blindrss-chromium-key-helper`` process.

    Reads base64 app-bound keys (one per line) from ``--input`` and writes one
    base64 master key (or ``ERROR:...``) per line to ``--output``.
    """
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args, _unknown = parser.parse_known_args(argv)
    try:
        with open(args.input, "r", encoding="ascii") as fh:
            keys = [line.strip() for line in fh.read().splitlines() if line.strip()]
        results = []
        for app_bound_key_b64 in keys:
            try:
                master_key = derive_master_key_from_app_bound_key(app_bound_key_b64)
                results.append(base64.b64encode(master_key).decode("ascii"))
            except Exception as exc:
                log.error("Could not derive one Chromium v20 key: %s", exc)
                results.append("ERROR:" + str(exc))
        with open(args.output, "w", encoding="ascii") as fh:
            fh.write("\n".join(results))
        return 0
    except Exception as exc:
        try:
            with open(args.output, "w", encoding="ascii") as fh:
                fh.write("ERROR:" + str(exc))
        except OSError:
            pass
        log.error("Chromium v20 key helper failed: %s", exc)
        return 1


# --- Volume Shadow Copy fallback for locked cookie DBs -----------------------


def _vss_copy_files(source_paths, dest_dir):
    """Copy (possibly locked) files out via Volume Shadow Copy snapshots.

    Runs elevated. Creates a ``ClientAccessible`` snapshot per source drive and
    copies the files from it — all inside one PowerShell process, because a
    ClientAccessible snapshot is only visible to the process that created it
    and is deleted when that process exits (``Persistent`` shadows are often
    unsupported when no shadow storage area is configured; ``vssadmin create
    shadow`` was removed from modern Windows).

    The copies made by the elevated PowerShell carry the elevated token's
    "protected administrator" DACL (owner = Administrators), which the
    non-elevated app cannot read. ``icacls`` is therefore used to grant the
    user's group full control on the staged files so the caller can read and
    later delete them. Returns a list of staged file paths, one per source
    (empty = not copied).
    """
    os.makedirs(dest_dir, exist_ok=True)
    staged = [""] * len(source_paths)
    if not source_paths:
        return staged

    fd, src_list = tempfile.mkstemp(prefix="blindrss-vss-list-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(source_paths))
    try:
        ps = (
            "$ErrorActionPreference = 'Stop'; "
            f"$srcList = '{src_list}'; "
            f"$destDir = '{dest_dir}'; "
            "$class = Get-WmiObject -List Win32_ShadowCopy; "
            "$shadows = @{}; "
            "$idx = 0; "
            "foreach ($src in (Get-Content -LiteralPath $srcList)) { "
            "  $src = $src.Trim(); if (-not $src) { continue }; "
            "  $root = [System.IO.Path]::GetPathRoot($src).TrimEnd('\\'); "
            "  $rel = $src.Substring($root.Length).TrimStart('\\'); "
            "  if (-not $shadows.ContainsKey($root)) { "
            "    $r = $class.Create($root + '\\', 'ClientAccessible'); "
            "    if ($r.ReturnValue -ne 0) { throw ('VSS Create returned ' + $r.ReturnValue) }; "
            "    $s = Get-WmiObject Win32_ShadowCopy | Where-Object { $_.ID -eq $r.ShadowID }; "
            "    if (-not $s) { throw 'shadow copy not found after create' }; "
            "    $shadows[$root] = $s.DeviceObject; "
            "  }; "
            "  $shadowSrc = $shadows[$root].TrimEnd('\\') + '\\' + $rel; "
            "  $dst = Join-Path $destDir ($idx.ToString() + '.cookies'); "
            "  if (Test-Path -LiteralPath $shadowSrc) { Copy-Item -LiteralPath $shadowSrc -Destination $dst -Force }; "
            "  foreach ($sfx in @('-wal','-shm')) { "
            "    if (Test-Path -LiteralPath ($shadowSrc + $sfx)) { Copy-Item -LiteralPath ($shadowSrc + $sfx) -Destination ($dst + $sfx) -Force } "
            "  }; "
            "  $idx++ "
            "}"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle Hidden", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=_CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-300:]
            log.warning("VSS copy failed: %s", detail)
            raise OSError(f"VSS copy failed: {detail}")
        # Grant the user's group full control so the non-elevated caller can
        # read (and later delete) the staged files despite the elevated DACL.
        grant = subprocess.run(
            ["icacls", dest_dir, "/grant", "*S-1-5-32-545:(OI)(CI)F", "/T", "/Q"],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=_CREATE_NO_WINDOW,
        )
        if grant.returncode != 0:
            log.warning(
                "Could not relax the staged-file ACL (%s): %s",
                grant.returncode,
                (grant.stderr or grant.stdout or "").strip()[-200:],
            )
        for index in range(len(source_paths)):
            dst = os.path.join(dest_dir, f"{index}.cookies")
            if os.path.isfile(dst):
                staged[index] = dst
    finally:
        try:
            os.remove(src_list)
        except OSError:
            pass
    return staged


def run_vss_copy_cli(argv) -> int:
    """Entry point for the elevated ``--blindrss-chromium-vss-copy`` process.

    Reads source paths (one per line) from ``--input``, copies them via Volume
    Shadow Copy into ``--output-dir``, and writes the staged path per line
    (empty = failure) to ``--manifest``.
    """
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", required=True)
    args, _unknown = parser.parse_known_args(argv)
    try:
        with open(args.input, "r", encoding="utf-8") as fh:
            sources = [line.strip() for line in fh.read().splitlines() if line.strip()]
        staged = _vss_copy_files(sources, args.output_dir)
        with open(args.manifest, "w", encoding="utf-8") as fh:
            fh.write("\n".join(staged))
        return 0
    except Exception as exc:
        log.error("Chromium VSS copy helper failed: %s", exc)
        try:
            with open(args.manifest, "w", encoding="utf-8") as fh:
                fh.write("ERROR:" + str(exc))
        except OSError:
            pass
        return 1


# --- Silent elevation via a pre-registered scheduled task ---------------------
#
# A non-elevated process can never silently gain admin/SYSTEM rights on Windows
# — the UAC consent prompt is the whole point of the boundary. The standard way
# to make an app's privileged helper "automatic" is to register a one-off
# scheduled task with RunLevel=Highest; creating it prompts once, and every
# later `schtasks /run` executes elevated with no prompt at all (same pattern
# Chrome's own elevation service uses).

_ELEVATED_TASK_PREFIX = "BlindRSS Elevated Helper"
# Task Scheduler requires a single name per task, but a dev checkout and the
# installed app are different executables. A fixed name would make them steal
# the task from each other (each sees the other's exe as "stale" and
# re-registers, prompting UAC every switch), so the task name embeds a short
# hash of the helper executable. Each install then owns its own task and never
# interferes with another. See `_elevated_task_name`.
_ELEVATED_REQUEST_PATH = os.path.join(
    tempfile.gettempdir(), "blindrss-elevated-request.json"
)
_ELEVATED_RESPONSE_PATH = os.path.join(
    tempfile.gettempdir(), "blindrss-elevated-response.json"
)


def _write_json_atomic(path: str, data) -> None:
    fd, tmp = tempfile.mkstemp(
        prefix="blindrss-req-", suffix=".tmp", dir=os.path.dirname(path) or "."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _is_cancelled(exc: Exception) -> bool:
    return getattr(exc, "winerror", None) == _ERROR_CANCELLED or "cancel" in str(exc).lower()


def _runas_and_wait(exe: str, params: str, timeout: float = 180.0) -> None:
    """Launch ``exe`` elevated via ShellExecuteEx runas and wait for exit."""
    if not _is_windows():
        raise OSError("Elevation is Windows-only")
    shell32 = ctypes.windll.shell32
    kernel32 = _kernel32()
    sei = _SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFO)
    sei.fMask = _SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = exe
    sei.lpParameters = params
    sei.nShow = _SW_HIDE
    ctypes.set_last_error(0)
    ok = shell32.ShellExecuteExW(ctypes.byref(sei))
    if not ok:
        code = ctypes.get_last_error() or ctypes.GetLastError()
        if code == _ERROR_CANCELLED:
            raise OSError("User cancelled the permission prompt", _ERROR_CANCELLED)
        raise OSError(f"ShellExecuteEx runas failed ({code})")
    h_process = sei.hProcess
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if h_process and kernel32.WaitForSingleObject(h_process, 1000) == 0x00000000:
            break
        time.sleep(0.25)
    if h_process:
        try:
            kernel32.CloseHandle(h_process)
        except Exception:
            pass


def _no_console_interpreter() -> str:
    """The interpreter to launch without a console window.

    The packaged app is a GUI-subsystem exe (no console). In a dev checkout
    ``sys.executable`` is console-app ``python.exe``, which would pop a cmd
    window; the sibling ``pythonw.exe`` is the GUI-subsystem build.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    alt = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return alt if os.path.isfile(alt) else sys.executable


def _elevated_helper_command():
    """``(execute, argument)`` for the fixed scheduled-task action."""
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
    )
    if getattr(sys, "frozen", False):
        return sys.executable, _ELEVATED_HELPER_FLAG
    return _no_console_interpreter(), f'"{script}" {_ELEVATED_HELPER_FLAG}'


def _ps_quote(value: str) -> str:
    return str(value).replace("'", "''")


def _elevated_task_name() -> str:
    """The scheduled-task name owned by this executable.

    Embeds a short hash of the helper exe so a dev checkout and the installed
    app each own their own task instead of stealing each other's registration
    (which would re-prompt UAC on every switch).
    """
    exe, _arg = _elevated_helper_command()
    digest = hashlib.sha256(str(exe).encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"{_ELEVATED_TASK_PREFIX} {digest}"


def _task_registered() -> bool:
    """True when this executable's task exists and points at the current exe.

    A task left over from a moved/updated install would silently run stale
    code, so it is treated as not-registered (and re-registered) when its
    command no longer references the current executable.
    """
    if not _is_windows():
        return False
    name = _elevated_task_name()
    proc = subprocess.run(
        ["schtasks", "/query", "/tn", name, "/xml"],
        capture_output=True,
        text=True,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        return False
    exe, _arg = _elevated_helper_command()
    return exe.lower() in (proc.stdout or "").lower()


def _register_elevated_task() -> None:
    """Create this executable's silent-elevation scheduled task (one-time UAC
    prompt). Also removes tasks owned by other BlindRSS executables so stale
    registrations from a moved/updated install never accumulate."""
    exe, arg = _elevated_helper_command()
    task_name = _elevated_task_name()
    script = [
        "$ErrorActionPreference = 'Stop'",
        f"$taskName = '{_ps_quote(task_name)}'",
        f"$action = New-ScheduledTaskAction -Execute '{_ps_quote(exe)}' -Argument '{_ps_quote(arg)}'",
        "$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest",
        "Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null",
        # Remove only other per-executable tasks (hashed suffix) — never the
        # legacy fixed-name task, which an older installed app still uses.
        "Get-ScheduledTask | Where-Object { $_.TaskName -match '^" + _ELEVATED_TASK_PREFIX + " [0-9a-f]{10}$' -and $_.TaskName -ne $taskName } | Unregister-ScheduledTask -Confirm:$false | Out-Null",
    ]
    fd, script_path = tempfile.mkstemp(suffix=".ps1", prefix="blindrss-task-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(script))
        powershell = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
        _runas_and_wait(
            powershell,
            f'-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{script_path}"',
        )
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass
    if not _task_registered():
        raise OSError("Scheduled-task registration did not take effect")


def _run_elevated_task(request: dict) -> dict:
    """Run the silent-elevation helper via the pre-registered scheduled task.

    Writes ``request`` JSON to a fixed location, triggers the task (which runs
    this app elevated as the current user with no UAC prompt), waits for the
    response JSON and returns it. Raises OSError when the one-time task
    registration is cancelled, or when the helper fails.
    """
    registered_here = False
    if not _task_registered():
        _register_elevated_task()
        registered_here = True
    task_name = _elevated_task_name()
    try:
        os.remove(_ELEVATED_RESPONSE_PATH)
    except OSError:
        pass
    _write_json_atomic(_ELEVATED_REQUEST_PATH, request)
    try:
        # The first `schtasks /run` immediately after registration can fail
        # transiently (0x5 access denied / 0x41301 not-ready) while the Task
        # Scheduler service catches up; retry a few times before giving up.
        attempts = 5 if registered_here else 1
        proc = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(1.0 + attempt * 0.5)
            proc = subprocess.run(
                ["schtasks", "/run", "/tn", task_name],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=_CREATE_NO_WINDOW,
            )
            if proc.returncode == 0:
                break
        if proc is None or proc.returncode != 0:
            raise OSError(f"schtasks /run failed: {proc.stderr.strip() if proc else 'no run attempted'}")
        deadline = time.monotonic() + 300.0
        while time.monotonic() < deadline:
            if os.path.isfile(_ELEVATED_RESPONSE_PATH) and os.path.getsize(_ELEVATED_RESPONSE_PATH) > 0:
                break
            time.sleep(0.2)
        try:
            with open(_ELEVATED_RESPONSE_PATH, "r", encoding="utf-8") as fh:
                response = json.load(fh)
        except (OSError, ValueError) as exc:
            raise OSError(f"Elevated helper produced no response: {exc}") from exc
        if response.get("error"):
            raise OSError(f"Elevated helper failed: {response['error']}")
        return response
    finally:
        try:
            os.remove(_ELEVATED_REQUEST_PATH)
        except OSError:
            pass


def run_elevated_helper_cli(argv) -> int:
    """Unified elevated helper, run by the silent scheduled task.

    Reads the request JSON from the fixed request path and writes the response
    JSON to the fixed response path (so the task needs no dynamic arguments).
    Handles v20 key derivation and Volume Shadow Copy file copies.
    """
    request = {}
    try:
        with open(_ELEVATED_REQUEST_PATH, "r", encoding="utf-8") as fh:
            request = json.load(fh)
    except Exception as exc:
        log.error("Elevated helper could not read its request: %s", exc)
        _write_json_atomic(_ELEVATED_RESPONSE_PATH, {"error": str(exc)})
        return 1

    response = {"keys": [], "copies": {}}
    try:
        for app_bound_key_b64 in request.get("keys") or []:
            try:
                master_key = derive_master_key_from_app_bound_key(app_bound_key_b64)
                response["keys"].append(base64.b64encode(master_key).decode("ascii"))
            except Exception as exc:
                log.error("Could not derive one Chromium v20 key: %s", exc)
                response["keys"].append("ERROR:" + str(exc))

        copy_paths = request.get("copy") or []
        if copy_paths:
            dest_dir = request.get("copy_dir") or tempfile.mkdtemp(prefix="blindrss-vss-stage-")
            staged = _vss_copy_files(copy_paths, dest_dir)
            for index, path in enumerate(staged):
                if path:
                    response["copies"][str(index)] = path
        _write_json_atomic(_ELEVATED_RESPONSE_PATH, response)
        return 0
    except Exception as exc:
        import traceback

        log.error("Elevated helper failed: %s", exc)
        try:
            _write_json_atomic(
                _ELEVATED_RESPONSE_PATH,
                {"error": str(exc), "trace": traceback.format_exc()[-2000:]},
            )
        except OSError:
            pass
        return 1


def _run_elevated_helper_batch(app_bound_keys_b64: list) -> list:
    """Derive v20 master keys, silently via the scheduled task when possible.

    Returns master-key bytes in the same order as ``app_bound_keys_b64`` (None
    for a key the helper could not derive). Falls back to a prompting runas
    helper only when the silent task cannot be used.
    """
    if not app_bound_keys_b64:
        return []
    if not _is_windows():
        raise OSError("Elevation is Windows-only")
    try:
        response = _run_elevated_task({"keys": list(app_bound_keys_b64)})
    except OSError as exc:
        if _is_cancelled(exc):
            raise
        log.warning("Silent elevation unavailable (%s); falling back to a UAC prompt", exc)
        return _run_elevated_helper_batch_runas(app_bound_keys_b64)
    raw_keys = response.get("keys") or []
    results = []
    for line in raw_keys:
        line = str(line).strip()
        if not line or line.startswith("ERROR:"):
            results.append(None)
            continue
        try:
            key = base64.b64decode(line)
        except Exception:
            results.append(None)
            continue
        results.append(key if len(key) == 32 else None)
    if len(results) < len(app_bound_keys_b64):
        results.extend([None] * (len(app_bound_keys_b64) - len(results)))
    return results[: len(app_bound_keys_b64)]


def _run_elevated_vss_copy(copy_paths):
    """Copy locked files via Volume Shadow Copy, silently when possible.

    Returns ``(staged_map, staging_dir)`` where ``staged_map`` is
    ``{index: staged_path}`` and ``staging_dir`` must be removed by the caller
    once the staged files have been consumed.
    """
    if not copy_paths or not _is_windows():
        return {}, None
    staging_dir = tempfile.mkdtemp(prefix="blindrss-vss-stage-")
    try:
        response = _run_elevated_task({"copy": list(copy_paths), "copy_dir": staging_dir})
    except OSError as exc:
        if not _is_cancelled(exc):
            log.warning("Silent elevation unavailable (%s); falling back to a UAC prompt", exc)
            shutil.rmtree(staging_dir, ignore_errors=True)
            return _run_elevated_vss_copy_runas(copy_paths)
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    staged_map = {}
    for key, path in (response.get("copies") or {}).items():
        try:
            staged_map[int(key)] = path
        except (TypeError, ValueError):
            continue
    return staged_map, staging_dir


# --- v20 key cache (DPAPI-protected at rest) ----------------------------------

_KEYS_FILENAME = "chromium_v20_keys.json"
_cache_lock = threading.Lock()


def _data_dir() -> str:
    from core import config as config_mod

    return config_mod.get_data_dir()


def _keys_path() -> str:
    return os.path.join(_data_dir(), _KEYS_FILENAME)


def _fingerprint(app_bound_key_b64: str) -> str:
    return hashlib.sha256(str(app_bound_key_b64).encode("utf-8")).hexdigest()


def _load_cached_v20_key(fingerprint: str):
    """The cached master key for a fingerprint, or None."""
    try:
        with open(_keys_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    entry = (data or {}).get(fingerprint)
    if not entry:
        return None
    try:
        protected = base64.b64decode(entry)
    except Exception:
        return None
    try:
        key = _dpapi_unprotect(protected) if _is_windows() else protected
    except Exception:
        return None
    return key if len(key) == 32 else None


def _store_cached_v20_key(fingerprint: str, key: bytes) -> None:
    with _cache_lock:
        path = _keys_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        try:
            protected = _dpapi_protect(key, "BlindRSS Chromium v20 cookie key")
        except Exception:
            protected = key
        data[fingerprint] = base64.b64encode(protected).decode("ascii")
        tmp = ""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="v20-keys-", suffix=".tmp", dir=os.path.dirname(path))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
            tmp = ""
        except OSError:
            log.exception("Could not persist the Chromium v20 key cache")
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def resolve_master_keys(
    app_bound_map: dict, *, elevate: bool = True, elevation_status: dict | None = None
) -> dict:
    """Resolve v20 master keys for ``{fingerprint: app_bound_key_b64}``.

    Cached keys are used when present; the rest are derived in a single
    elevation and cached. Returns ``{fingerprint: key_bytes}`` (missing keys
    are simply absent).
    """
    if not app_bound_map:
        return {}
    resolved = {}
    missing = {}
    for fingerprint, app_bound_b64 in app_bound_map.items():
        cached = _load_cached_v20_key(fingerprint)
        if cached:
            resolved[fingerprint] = cached
        else:
            missing[fingerprint] = app_bound_b64

    if missing and elevate and _is_windows():
        ordered = list(missing.items())
        try:
            keys = _run_elevated_helper_batch([b64 for _fp, b64 in ordered])
        except OSError as exc:
            if elevation_status is not None:
                elevation_status["failed"] = True
                elevation_status["cancelled"] = bool(
                    getattr(exc, "winerror", None) == _ERROR_CANCELLED
                    or "cancel" in str(exc).lower()
                )
            if getattr(exc, "winerror", None) == _ERROR_CANCELLED or "cancel" in str(exc).lower():
                log.info("Chromium v20 key derivation was cancelled by the user")
            else:
                log.warning("Chromium v20 key derivation failed: %s", exc)
            return resolved
        except Exception:
            if elevation_status is not None:
                elevation_status["failed"] = True
                elevation_status["cancelled"] = False
            log.exception("Chromium v20 key derivation failed")
            return resolved
        for (fingerprint, _b64), key in zip(ordered, keys):
            if key is not None:
                resolved[fingerprint] = key
                _store_cached_v20_key(fingerprint, key)
    return resolved


# ---------------------------------------------------------------------------
# Browser / profile discovery
# ---------------------------------------------------------------------------


def _chromium_data_roots():
    """[(browser label, data root)] for installed Chromium-family browsers."""
    roots = []
    if _is_windows():
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        specs = [
            ("Google Chrome", local, ["Google", "Chrome", "User Data"]),
            ("Google Chrome Beta", local, ["Google", "Chrome Beta", "User Data"]),
            ("Google Chrome Dev", local, ["Google", "Chrome Dev", "User Data"]),
            ("Google Chrome Canary", local, ["Google", "Chrome SxS", "User Data"]),
            ("Microsoft Edge", local, ["Microsoft", "Edge", "User Data"]),
            ("Microsoft Edge Beta", local, ["Microsoft", "Edge Beta", "User Data"]),
            ("Microsoft Edge Dev", local, ["Microsoft", "Edge Dev", "User Data"]),
            ("Microsoft Edge Canary", local, ["Microsoft", "Edge SxS", "User Data"]),
            ("Brave", local, ["BraveSoftware", "Brave-Browser", "User Data"]),
            ("Brave Beta", local, ["BraveSoftware", "Brave-Browser-Beta", "User Data"]),
            ("Brave Dev", local, ["BraveSoftware", "Brave-Browser-Dev", "User Data"]),
            ("Brave Nightly", local, ["BraveSoftware", "Brave-Browser-Nightly", "User Data"]),
            ("Chromium", local, ["Chromium", "User Data"]),
            ("Vivaldi", local, ["Vivaldi", "User Data"]),
            ("Vivaldi Snapshot", local, ["Vivaldi Snapshot", "User Data"]),
            ("Opera", roaming, ["Opera Software", "Opera Stable"]),
            ("Opera Beta", roaming, ["Opera Software", "Opera Next"]),
            ("Opera Developer", roaming, ["Opera Software", "Opera Developer"]),
            ("Opera GX", roaming, ["Opera Software", "Opera GX Stable"]),
        ]
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
        specs = [
            ("Google Chrome", base, ["Google", "Chrome"]),
            ("Google Chrome Beta", base, ["Google", "Chrome Beta"]),
            ("Google Chrome Dev", base, ["Google", "Chrome Dev"]),
            ("Google Chrome Canary", base, ["Google", "Chrome Canary"]),
            ("Microsoft Edge", base, ["Microsoft Edge"]),
            ("Microsoft Edge Beta", base, ["Microsoft Edge Beta"]),
            ("Microsoft Edge Dev", base, ["Microsoft Edge Dev"]),
            ("Brave", base, ["BraveSoftware", "Brave-Browser"]),
            ("Brave Beta", base, ["BraveSoftware", "Brave-Browser-Beta"]),
            ("Brave Nightly", base, ["BraveSoftware", "Brave-Browser-Nightly"]),
            ("Chromium", base, ["Chromium"]),
            ("Vivaldi", base, ["Vivaldi"]),
            ("Opera", base, ["com.operasoftware.Opera"]),
            ("Opera GX", base, ["com.operasoftware.OperaGX"]),
        ]
    else:
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        specs = [
            ("Google Chrome", config, ["google-chrome"]),
            ("Google Chrome Beta", config, ["google-chrome-beta"]),
            ("Google Chrome Unstable", config, ["google-chrome-unstable"]),
            ("Chromium", config, ["chromium"]),
            ("Microsoft Edge", config, ["microsoft-edge"]),
            ("Microsoft Edge Beta", config, ["microsoft-edge-beta"]),
            ("Brave", config, ["BraveSoftware", "Brave-Browser"]),
            ("Brave Beta", config, ["BraveSoftware", "Brave-Browser-Beta"]),
            ("Brave Nightly", config, ["BraveSoftware", "Brave-Browser-Nightly"]),
            ("Vivaldi", config, ["vivaldi"]),
            ("Vivaldi Snapshot", config, ["vivaldi-snapshot"]),
            ("Opera", config, ["opera"]),
        ]
    for label, base, parts in specs:
        if not base:
            continue
        root = os.path.join(base, *parts)
        if os.path.isdir(root):
            roots.append((label, root))
    return roots


def _find_cookie_dbs(root: str) -> list:
    """Cookie DB paths under a Chromium data root (handles flat Opera layouts)."""
    dbs = []
    for rel in ("Network", ""):
        path = os.path.join(root, rel, "Cookies") if rel else os.path.join(root, "Cookies")
        if os.path.isfile(path):
            dbs.append(path)
    try:
        entries = os.listdir(root)
    except OSError:
        entries = []
    for entry in entries:
        profile_dir = os.path.join(root, entry)
        if not os.path.isdir(profile_dir):
            continue
        for rel in ("Network", ""):
            path = (
                os.path.join(profile_dir, rel, "Cookies")
                if rel
                else os.path.join(profile_dir, "Cookies")
            )
            if os.path.isfile(path):
                dbs.append(path)
    return dbs


def list_chromium_profiles():
    """Importable Chromium profiles, newest cookie DB first.

    Returns ``[{"browser", "profile", "cookie_db", "local_state", "mtime"}]``.
    """
    found = []
    seen = set()
    for label, root in _chromium_data_roots():
        local_state = os.path.join(root, "Local State")
        for db in _find_cookie_dbs(root):
            key = os.path.abspath(db).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                mtime = os.path.getmtime(db)
            except OSError:
                continue
            profile_dir = os.path.dirname(db)
            if os.path.basename(profile_dir).lower() == "network":
                profile_dir = os.path.dirname(profile_dir)
            found.append({
                "browser": label,
                "profile": os.path.basename(profile_dir),
                "cookie_db": db,
                "local_state": local_state,
                "mtime": mtime,
            })
    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------


def _macos_keychain_password(browser_key: str) -> bytes:
    """The Keychain password used to derive macOS v10 keys, or b''."""
    service = f"{browser_key} Safe Storage"
    try:
        proc = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-w", "-a", browser_key, "-s", service],
            capture_output=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return b""
    return proc.stdout.strip() if proc.returncode == 0 else b""


def _load_v10_key(local_state: str, browser_key: str):
    """The v10 AES key for a profile, or None when unavailable."""
    try:
        with open(local_state, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        enc_b64 = state.get("os_crypt", {}).get("encrypted_key")
    except (OSError, ValueError):
        return None

    if _is_windows():
        if not enc_b64:
            return None
        try:
            raw = base64.b64decode(enc_b64)
        except Exception:
            return None
        if raw[:5] != b"DPAPI":
            return None
        try:
            return _dpapi_unprotect(raw[5:])
        except Exception:
            log.debug("v10 key DPAPI decrypt failed", exc_info=True)
            return None

    if sys.platform == "darwin":
        password = _macos_keychain_password(browser_key)
        if not password:
            return None
        return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, dklen=16)

    # Linux: the pre-keyring default. Modern distros use a secret-service (v11),
    # which this best-effort path does not unlock.
    return hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, dklen=16)


def _browser_key_for_label(label: str) -> str:
    low = label.lower()
    if "edge" in low:
        return "Microsoft Edge"
    if "brave" in low:
        return "Brave"
    if "vivaldi" in low:
        return "Vivaldi"
    if "chromium" in low:
        return "Chromium"
    if "opera" in low:
        return "Opera"
    return "Chrome"


def chromium_profile_user_agent(profile: dict) -> str:
    """A User-Agent matching the Chromium browser a profile belongs to.

    A clearance cookie (cf_clearance, ak_bmsc, ...) is validated against the
    exact browser identity that earned it, so the UA is derived from the
    browser's own installed version (via ``core.user_agents``) rather than a
    single hard-coded string. Browsers ``user_agents`` cannot detect
    (Chromium, Vivaldi, Opera) fall back to the baked Chromium major, which is
    close enough for those sites' clearance checks.
    """
    label = str(profile.get("browser") or "").lower()
    try:
        from core import user_agents

        if "edge" in label:
            key = "installed:edge"
        elif "brave" in label:
            key = "installed:brave"
        else:
            key = "installed:chrome"
        for identity in user_agents.detect_installed():
            if identity.key == key:
                return identity.ua
        plat = (
            "windows"
            if sys.platform.startswith("win")
            else ("macos" if sys.platform == "darwin" else "linux")
        )
        engine = "edge" if "edge" in label else "chromium"
        return user_agents.build_ua(engine, plat, user_agents.CHROMIUM_MAJOR)
    except Exception:
        log.debug("Could not derive a Chromium User-Agent for %s", label, exc_info=True)
        return ""


def _read_local_state(local_state: str) -> dict:
    try:
        with open(local_state, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    return state.get("os_crypt", {}) if isinstance(state, dict) else {}


# ---------------------------------------------------------------------------
# Cookie database reading
# ---------------------------------------------------------------------------


def _copy_with_retries(src: str, dst: str, attempts: int = 3) -> None:
    last_exc = None
    for _ in range(attempts):
        try:
            shutil.copyfile(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.15)
    if last_exc is not None:
        raise last_exc


def _db_has_integrity_check(conn) -> bool:
    """True when the cookie DB prepends a SHA-256(domain) to encrypted values."""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    except sqlite3.OperationalError:
        return True
    if not row:
        return True
    try:
        return int(row[0]) >= 24
    except (TypeError, ValueError):
        return True


def read_cookie_db(cookie_db_path: str, *, v10_key=None, v20_key=None):
    """Decrypted rows as ``(host, path, secure, http_only, expiry, name, value)``."""
    src = cookie_db_path
    if not os.path.isfile(src):
        raise OSError("cookies database not found")
    tmp_dir = tempfile.mkdtemp(prefix="blindrss-chromium-cookies-")
    try:
        dst = os.path.join(tmp_dir, "Cookies")
        _copy_with_retries(src, dst)
        for suffix in ("-wal", "-shm"):
            side = src + suffix
            if os.path.isfile(side):
                try:
                    shutil.copyfile(side, dst + suffix)
                except OSError:
                    pass
        conn = sqlite3.connect(dst)
        try:
            has_integrity_check = _db_has_integrity_check(conn)
            rows = conn.execute(
                "SELECT host_key, path, is_secure, is_httponly, expires_utc, name, value, encrypted_value "
                "FROM cookies"
            ).fetchall()
        finally:
            conn.close()

        out = []
        for host, path, secure, http_only, expires_utc, name, value, encrypted in rows:
            host = str(host or "").strip()
            name = str(name or "")
            if not host or not name:
                continue
            plain_value = str(value or "")
            encrypted_bytes = bytes(encrypted or b"")
            if plain_value and not encrypted_bytes:
                decrypted = plain_value
            else:
                decrypted_bytes = decrypt_cookie_value(
                    encrypted_bytes,
                    v10_key=v10_key,
                    v20_key=v20_key,
                    strip_domain_hash=has_integrity_check,
                )
                if decrypted_bytes is None:
                    continue
                try:
                    decrypted = decrypted_bytes.decode("utf-8", errors="replace")
                except Exception:
                    continue
            try:
                expiry_nt = int(expires_utc or 0)
            except (TypeError, ValueError):
                expiry_nt = 0
            expiry = 0 if expiry_nt <= 0 else int(expiry_nt / 1000000) - _NT_TO_UNIX_OFFSET
            out.append((
                host,
                str(path or "/"),
                bool(secure),
                bool(http_only),
                int(expiry),
                name,
                decrypted,
            ))
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _records_for_rows(rows) -> list:
    """Netscape 7-field records for decrypted rows, dropping expired cookies."""
    records = []
    now = int(time.time())
    for host, path, secure, http_only, expiry, name, value in rows:
        # A Chromium expiry of 0 means a session cookie (store as 0 = no expiry
        # in the Netscape jar); a past expiry is dropped outright.
        if expiry and expiry < now:
            continue
        domain_field = ("#HttpOnly_" + host) if http_only else host
        records.append((
            domain_field,
            "TRUE" if host.startswith(".") else "FALSE",
            path or "/",
            "TRUE" if secure else "FALSE",
            str(expiry),
            name,
            value,
        ))
    return records


def read_profile_cookies(profile: dict, *, elevate: bool = True):
    """Netscape-format records (7-tuples) for one Chromium profile.

    Returns ``(records, stats)`` where stats carries ``decrypted``/``elevated``.
    Unreadable databases are logged and return an empty result.
    """
    local_state = str(profile.get("local_state") or "")
    browser_key = _browser_key_for_label(str(profile.get("browser") or ""))
    v10_key = _load_v10_key(local_state, browser_key) if local_state else None

    v20_key = None
    elevated = False
    os_crypt = _read_local_state(local_state) if local_state else {}
    app_bound_b64 = str(os_crypt.get("app_bound_encrypted_key") or "")
    if app_bound_b64:
        v20_key = resolve_master_keys({_fingerprint(app_bound_b64): app_bound_b64}, elevate=elevate).get(
            _fingerprint(app_bound_b64)
        )
        elevated = v20_key is not None

    try:
        rows = read_cookie_db(
            str(profile.get("cookie_db") or ""), v10_key=v10_key, v20_key=v20_key
        )
    except Exception:
        log.debug(
            "Could not read Chromium cookies from %s", profile.get("cookie_db"), exc_info=True
        )
        return [], {"decrypted": 0, "elevated": False}

    records = _records_for_rows(rows)
    return records, {"decrypted": len(records), "elevated": elevated}


# ---------------------------------------------------------------------------
# High-level import (batched key resolution, one elevation for all browsers)
# ---------------------------------------------------------------------------


def _profile_v10_v20_keys(profile: dict, v20_map: dict):
    """(v10_key, v20_key) for a profile, using pre-resolved v20 keys."""
    local_state = str(profile.get("local_state") or "")
    browser_key = _browser_key_for_label(str(profile.get("browser") or ""))
    v10_key = _load_v10_key(local_state, browser_key) if local_state else None
    v20_key = None
    os_crypt = _read_local_state(local_state) if local_state else {}
    app_bound_b64 = str(os_crypt.get("app_bound_encrypted_key") or "")
    if app_bound_b64:
        v20_key = v20_map.get(_fingerprint(app_bound_b64))
    return v10_key, v20_key


def import_chromium_cookies(config_manager, *, profiles=None, elevate: bool = True) -> dict:
    """Read every Chromium profile and merge its cookies into the managed jars.

    Cookies are merged into the per-site HTTP jar via ``site_cookies``, and
    YouTube/Google cookies are additionally written to the yt-dlp cookie file
    (``youtube_cookies.txt``) when the user has not configured their own
    ``ytdlp_cookies_file``. All v20 keys are resolved in a single elevation.

    Returns a stats dict for logging/notifications.
    """
    from core import site_cookies

    stats = {
        "profiles": 0,
        "cookies": 0,
        "new": 0,
        "elevated": 0,
        "youtube": 0,
        "vss": 0,
        "elevation_failed": 0,
    }
    if profiles is None:
        profiles = list_chromium_profiles()
    profiles = list(profiles or [])

    # Resolve every app-bound key up front so one UAC prompt covers all browsers.
    app_bound_map = {}
    for profile in profiles:
        os_crypt = _read_local_state(str(profile.get("local_state") or ""))
        app_bound_b64 = str(os_crypt.get("app_bound_encrypted_key") or "")
        if app_bound_b64:
            app_bound_map[_fingerprint(app_bound_b64)] = app_bound_b64
    elevation_status = {}
    v20_map = resolve_master_keys(
        app_bound_map, elevate=elevate, elevation_status=elevation_status
    )
    stats["elevation_failed"] = int(bool(elevation_status.get("failed")))
    elevated_count = len(v20_map)

    # A running browser holds its ``Cookies`` database with exclusive access,
    # so a plain copy fails. Read those via a Volume Shadow Copy snapshot
    # (one elevation covers every locked profile) instead of skipping them.
    locked = [
        (i, str(profile.get("cookie_db") or ""))
        for i, profile in enumerate(profiles)
        if _is_locked_file(str(profile.get("cookie_db") or ""))
    ]
    staged_map = {}
    staging_dir = None
    if locked:
        try:
            staged_map, staging_dir = _run_elevated_vss_copy([path for _i, path in locked])
        except OSError as exc:
            stats["elevation_failed"] = 1
            if getattr(exc, "winerror", None) == _ERROR_CANCELLED or "cancel" in str(exc).lower():
                log.info("Chromium VSS copy was cancelled by the user")
            else:
                log.warning("Chromium VSS copy failed: %s", exc)
            staged_map = {}

    all_records = []
    youtube_records = []
    # A clearance cookie is only valid for the exact browser identity that
    # earned it (the "matched triple": cookie + UA + TLS handshake). Record the
    # UA of the profile that supplied each clearance so `_apply_site_cookies`
    # can force a matching fingerprint on later requests.
    clearance_ua = {}
    try:
        for index, profile in enumerate(profiles):
            v10_key, v20_key = _profile_v10_v20_keys(profile, v20_map)
            cookie_db = staged_map.get(index) or str(profile.get("cookie_db") or "")
            if index in staged_map:
                stats["vss"] += 1
            try:
                rows = read_cookie_db(
                    cookie_db, v10_key=v10_key, v20_key=v20_key
                )
            except Exception:
                log.debug(
                    "Could not read Chromium cookies from %s", profile.get("cookie_db"), exc_info=True
                )
                continue
            if not rows:
                continue
            stats["profiles"] += 1
            records = _records_for_rows(rows)
            stats["cookies"] += len(records)
            profile_ua = ""
            for record in records:
                domain = str(record[0]).replace("#HttpOnly_", "", 1).lstrip(".").lower()
                all_records.append(record)
                if site_cookies._is_harvestable(str(record[5] or "")):
                    if not profile_ua:
                        profile_ua = chromium_profile_user_agent(profile)
                    clearance_ua.setdefault(domain, profile_ua or "")
                if (
                    domain == "youtube.com"
                    or domain.endswith(".youtube.com")
                    or domain == "google.com"
                    or domain.endswith(".google.com")
                ):
                    youtube_records.append(record)
    finally:
        if staging_dir:
            shutil.rmtree(staging_dir, ignore_errors=True)

    stats["elevated"] = elevated_count
    if all_records:
        stats["new"] = site_cookies.merge_records_into_jar(all_records)
        for domain, ua in clearance_ua.items():
            if ua:
                try:
                    site_cookies.set_host_user_agent(domain, ua)
                except Exception:
                    log.debug("Could not pin UA for %s", domain, exc_info=True)
        log.info(
            "Imported %d cookie(s) from %d Chromium profile(s) (%d v20 keys resolved)",
            len(all_records), stats["profiles"], elevated_count,
        )

    if youtube_records:
        try:
            stats["youtube"] = site_cookies.merge_youtube_cookies(youtube_records, config_manager)
        except Exception:
            log.exception("Could not persist harvested YouTube cookies")

    return stats
