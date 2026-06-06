from __future__ import annotations
from typing import Optional, Iterable, Tuple
import zlib
import binascii
import logging

_LOGGER = logging.getLogger(__name__)

# -------------------------
# Protobuf wire helpers
# -------------------------

def _read_varint(buf: bytes, i: int, n: int):
    shift = 0
    result = 0
    while i < n:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")
    raise ValueError("unexpected EOF in varint")

def iter_len_delimited(buf: bytes, depth: int = 0, max_depth: int = 8) -> Iterable[Tuple[int, int, int, bytes]]:
    """
    Yield (depth, start, length, field_bytes) for all length-delimited (wire_type=2) fields,
    recursively up to max_depth. We recurse even if inner blobs are not protobuf – we’re hunting for deflate streams.
    """
    i, n = 0, len(buf)
    while i < n:
        try:
            key, i = _read_varint(buf, i, n)
        except Exception:
            break
        wt = key & 0x7
        if wt == 0:  # varint
            try:
                _, i = _read_varint(buf, i, n)
            except Exception:
                break
        elif wt == 1:  # 64-bit
            i += 8
            if i > n:
                break
        elif wt == 2:  # length-delimited
            try:
                length, i2 = _read_varint(buf, i, n)
            except Exception:
                break
            start = i2
            end = start + length
            if end > n:
                break
            field_bytes = buf[start:end]
            i = end
            yield (depth, start, length, field_bytes)
            if depth < max_depth and length >= 2:
                yield from iter_len_delimited(field_bytes, depth + 1, max_depth)
        elif wt == 5:  # 32-bit
            i += 4
            if i > n:
                break
        else:
            break

# -------------------------
# Decompress helpers
# -------------------------

# Try multiple wbits (auto zlib/gzip, zlib, raw-deflate, gzip)
_WBITS_TRY = (47, 15, -15, 31)

def _try_decompress_once(blob: bytes):
    """Try to decompress blob from offset 0 with several wbits."""
    for w in _WBITS_TRY:
        try:
            out = zlib.decompress(blob, wbits=w)
            return (0, w, out)  # (offset, wbits, out)
        except Exception:
            continue
    return None

def _scan_offsets_and_decompress(buf: bytes, max_offset: int = 512):
    """
    Slide through offsets 0..max_offset (clamped to len-8) and try several wbits.
    Return first hit: (offset, wbits, out) or None.
    """
    n = len(buf)
    if n < 16:
        return None
    scan_upto = min(max_offset, max(0, n - 8))
    for off in range(0, scan_upto + 1):
        chunk = buf[off:]
        for w in _WBITS_TRY:
            try:
                out = zlib.decompress(chunk, wbits=w)
                return (off, w, out)
            except Exception:
                continue
    return None

def looks_like_obis_text(b: bytes) -> bool:
    """Fast heuristic: must contain '/' (start) and '!' (end) and be reasonably sized."""
    if not b or len(b) < 20:
        return False
    try:
        s = b.decode("utf-8", errors="ignore")
    except Exception:
        return False
    return ("/" in s) and ("!" in s)

def extract_zlib_payload_if_any(buf: bytes) -> Optional[bytes]:
    """
    Back-compat: return *compressed* candidate that can be decompressed (from some offset).
    """
    for _depth, _start, _len, cand in iter_len_delimited(buf, 0, 8):
        if _scan_offsets_and_decompress(cand) is not None:
            return cand
    if _scan_offsets_and_decompress(buf) is not None:
        return buf
    return None

def decompress_any_payload(buf: bytes) -> Optional[bytes]:
    """
    Return *decompressed* OBIS-ish payload (bytes) from the first candidate that yields
    plausible OBIS text after decompression. If none looks like OBIS, return the first
    successful decompressed output anyway (best-effort).
    """
    first_success: Optional[bytes] = None

    for depth, start, length, cand in iter_len_delimited(buf, 0, 8):
        # 1) quick try without offset
        r0 = _try_decompress_once(cand)
        if r0 is not None:
            _off, _w, out = r0
            if looks_like_obis_text(out):
                return out
            if first_success is None:
                first_success = out
        # 2) offset scan
        r = _scan_offsets_and_decompress(cand, max_offset=512)
        if r is not None:
            off, w, out = r
            if looks_like_obis_text(out):
                return out
            if first_success is None:
                first_success = out

    # whole buffer as last chance
    r0 = _try_decompress_once(buf)
    if r0 is not None:
        _off, _w, out = r0
        if looks_like_obis_text(out):
            return out
        if first_success is None:
            first_success = out

    r = _scan_offsets_and_decompress(buf, max_offset=512)
    if r is not None:
        off, w, out = r
        if looks_like_obis_text(out):
            return out
        if first_success is None:
            first_success = out

    return first_success

def try_decompress_all_candidates(buf: bytes, debug: bool = False) -> Optional[Tuple[int, int, int, int, int, bytes, bool]]:
    """
    Verbose scanner: logs every candidate and returns
      (depth, start, length, offset, wbits, out, looks_obis)
    for the FIRST success (prioritizing anything that looks like OBIS).
    """
    best_plain: Optional[Tuple[int, int, int, int, int, bytes, bool]] = None

    for depth, start, length, cand in iter_len_delimited(buf, 0, 8):
        head = binascii.hexlify(cand[:8]).decode()
        if debug:
            _LOGGER.debug("  candidate depth=%d len=%d head=%s", depth, length, head)

        r0 = _try_decompress_once(cand)
        if r0 is not None:
            _off, _w, out = r0
            looks = looks_like_obis_text(out)
            if debug:
                _LOGGER.debug("  -> decompressed at off=%d wbits=%d out_len=%d obis=%s",
                              _off, _w, len(out), "yes" if looks else "no")
            if looks:
                return (depth, start, length, _off, _w, out, True)
            if best_plain is None:
                best_plain = (depth, start, length, _off, _w, out, False)

        r = _scan_offsets_and_decompress(cand, max_offset=512)
        if r is not None:
            off, w, out = r
            looks = looks_like_obis_text(out)
            if debug:
                _LOGGER.debug("  -> decompressed at off=%d wbits=%d out_len=%d obis=%s",
                              off, w, len(out), "yes" if looks else "no")
            if looks:
                return (depth, start, length, off, w, out, True)
            if best_plain is None:
                best_plain = (depth, start, length, off, w, out, False)

    # Whole buffer as ultimate fallback
    r0 = _try_decompress_once(buf)
    if r0 is not None:
        _off, _w, out = r0
        looks = looks_like_obis_text(out)
        if debug:
            _LOGGER.debug("  whole buffer decompressed off=%d wbits=%d out_len=%d obis=%s",
                          _off, _w, len(out), "yes" if looks else "no")
        if looks:
            return (0, 0, len(buf), _off, _w, out, True)
        if best_plain is not None:
            return best_plain
        best_plain = (0, 0, len(buf), _off, _w, out, False)

    r = _scan_offsets_and_decompress(buf, max_offset=512)
    if r is not None:
        off, w, out = r
        looks = looks_like_obis_text(out)
        if debug:
            _LOGGER.debug("  whole buffer decompressed at off=%d wbits=%d out_len=%d obis=%s",
                          off, w, len(out), "yes" if looks else "no")
        if looks:
            return (0, 0, len(buf), off, w, out, True)
        if best_plain is not None:
            return best_plain
        best_plain = (0, 0, len(buf), off, w, out, False)

    return best_plain

def pick_best_candidate_from_blob(blob: bytes) -> bytes | None:
    # Prefer the first candidate that decompresses at offset 0..64; else return the largest candidate (excluding 'P1').
    best = None
    best_len = -1
    for depth, start, length, cand in iter_len_delimited(blob, 0, 6):
        if length == 2 and cand == b"P1":
            continue
        if length > best_len:
            best = cand; best_len = length
        # quick probe
        r0 = _try_decompress_once(cand)
        if r0 is not None:
            return cand
        r = _scan_offsets_and_decompress(cand, max_offset=64)
        if r is not None:
            return cand
    return best

# -------------------------
# Multi-chunk stream decoder
# -------------------------

def _read_varint_simple(buf: bytes, pos: int):
    """Simple varint reader for the multi-chunk decoder."""
    result, shift = 0, 0
    while pos < len(buf):
        b = buf[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("unexpected EOF in varint")

def _read_field_simple(buf: bytes, pos: int):
    """Read one protobuf field. Returns (field_number, wire_type, value, new_pos) or None."""
    if pos >= len(buf):
        return None
    try:
        tag, pos = _read_varint_simple(buf, pos)
    except ValueError:
        return None
    wt, fn = tag & 7, tag >> 3
    try:
        if wt == 0:
            v, pos = _read_varint_simple(buf, pos)
            return fn, wt, v, pos
        elif wt == 1:
            return fn, wt, buf[pos:pos + 8], pos + 8
        elif wt == 2:
            length, pos = _read_varint_simple(buf, pos)
            return fn, wt, buf[pos:pos + length], pos + length
        elif wt == 5:
            return fn, wt, buf[pos:pos + 4], pos + 4
    except Exception:
        return None
    return None


def decode_multi_chunk_stream(payload: bytes) -> Optional[bytes]:
    """
    Decode a Tibber Pulse P1 MQTT payload that uses a multi-chunk Zlib stream.
    Returns the decompressed OBIS plaintext, or None if decoding fails.
    """
    # Step 1: Collect all outer Field-2 chunks (the repeated blobs)
    outer_chunks = []
    pos = 0
    while pos < len(payload):
        field = _read_field_simple(payload, pos)
        if field is None:
            break
        fn, wt, val, pos = field
        if wt == 2:
            outer_chunks.append(val)

    if not outer_chunks:
        return None

    # Step 2: From each chunk extract the Zlib fragment (Field 3, not "P1")
    zlib_fragments = []
    for chunk in outer_chunks:
        if b"P1" not in chunk:
            continue
        cpos = 0
        while cpos < len(chunk):
            field = _read_field_simple(chunk, cpos)
            if field is None:
                break
            fn, wt, val, cpos = field
            # Field 3 is the Zlib fragment; Field 2 = "P1" string is skipped
            if wt == 2 and val != b"P1":
                zlib_fragments.append(val)

    if not zlib_fragments:
        return None

    if len(zlib_fragments) < 2:
        return None

    # Step 3: Combine all fragments and decompress as one Zlib stream
    combined = b"".join(zlib_fragments)
    try:
        d = zlib.decompressobj(wbits=15)
        out = d.decompress(combined)
        out += d.flush()
        if out:
            return out
    except Exception as exc:
        _LOGGER.debug("decode_multi_chunk_stream: zlib failed: %s", exc)

    return None


def split_obis_frames(buf: bytes) -> list[bytes]:
    """
    Split a decompressed byte buffer into individual OBIS telegrams.
    """
    frames: list[bytes] = []
    b = bytearray(buf)
    while True:
        start = b.find(b"/")
        if start < 0:
            break
        end = b.find(b"!", start + 1)
        if end < 0:
            break
        frames.append(bytes(b[start:end + 1]))
        del b[:end + 1]
    return frames
