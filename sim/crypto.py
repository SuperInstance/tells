"""The only crypto in the sim: stdlib HKDF-SHA256 + HMAC-SHA256 tags.

REVIEW-MCODE SS1.4 calls for an ephemeral-public-key exchange; stdlib has
no ECC, so the exchange is abstracted exactly as SS1.4 step 5 derives the
keys: everything flows from the per-device secret S, which the gateway
learned out of band (the enclosure label).  Both sides hold S, so the
derivations are faithful; the "public keys" are carried as opaque bytes.
"""

import hashlib
import hmac


def hkdf_sha256(ikm: bytes, info: bytes = b"", salt: bytes = b"", length: int = 32) -> bytes:
    """RFC 5869 HKDF with SHA-256."""
    if not salt:
        salt = b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def _coerce(part) -> bytes:
    if isinstance(part, str):
        return part.encode()
    if isinstance(part, int):
        return part.to_bytes(8, "big")
    if isinstance(part, float):
        raise TypeError("float parts are ambiguous; pass bytes or str")
    return bytes(part)


def mac_tag(key: bytes, *parts) -> bytes:
    m = hmac.new(key, digestmod=hashlib.sha256)
    for part in parts:
        m.update(_coerce(part))
    return m.digest()


def mac_ok(key: bytes, parts, expected_hex: str) -> bool:
    if not isinstance(expected_hex, str):
        return False
    return hmac.compare_digest(mac_tag(key, *parts).hex(), expected_hex)


def random_bytes(rng, n: int) -> bytes:
    return bytes(rng.getrandbits(8) for _ in range(n))
