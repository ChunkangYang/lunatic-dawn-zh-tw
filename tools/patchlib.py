"""補丁格式（只存「差異位元組」，不含遊戲原始內容）。
一個 .diff 檔 = zlib 壓縮的： b'LDZ1' + u32 筆數 + 每筆 (u32 offset, u32 長度, 資料)。
BMH 圖檔的差異是對「解壓後的 DIB」計算，套用時先解壓、套差異、再用同一個編碼器重新壓縮。
"""
import hashlib, os, struct, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bmh_decode import bmh_to_dib   # noqa: E402
from bmh_encode import dib_to_bmh   # noqa: E402

MAGIC = b'LDZ1'


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def make_diff(a, b, merge_gap=8):
    if len(a) != len(b):
        raise ValueError('長度不同（%d vs %d），本格式只支援等長差異' % (len(a), len(b)))
    runs = []
    n = len(a)
    i = 0
    while i < n:
        if a[i] == b[i]:
            i += 1
            continue
        s = i
        last = i
        i += 1
        while i < n and i - last <= merge_gap:
            if a[i] != b[i]:
                last = i
            i += 1
        runs.append((s, last + 1))
        i = last + 1
    body = bytearray(MAGIC + struct.pack('<I', len(runs)))
    for s, e in runs:
        body += struct.pack('<II', s, e - s) + b[s:e]
    return zlib.compress(bytes(body), 9), len(runs)


def apply_diff(a, diff):
    d = zlib.decompress(diff)
    if d[:4] != MAGIC:
        raise ValueError('不是 LDZ1 差異檔')
    (cnt,) = struct.unpack_from('<I', d, 4)
    out = bytearray(a)
    p = 8
    for _ in range(cnt):
        off, ln = struct.unpack_from('<II', d, p)
        p += 8
        if off + ln > len(out):
            raise ValueError('差異超出檔案範圍')
        out[off:off + ln] = d[p:p + ln]
        p += ln
    return bytes(out)


def bmh_to_payload(bmh_bytes):
    """回傳 (header前6欄, DIB 位元組)；供製作與套用差異。"""
    h, dib, _ = bmh_to_dib(bmh_bytes)
    return h, dib


def dib_to_bmh_like(dib, orig_bmh_bytes):
    h, _, _ = bmh_to_dib(orig_bmh_bytes)
    return dib_to_bmh(dib, like_header=h[3:6])
