#!/usr/bin/env python
"""BMH encoder: DIB / BMP / PNG(8-bit palette) -> .BMH.  stdlib only.

Usage:
  python -I bmh_encode.py <in.bmp> <out.BMH>            # standard BMP (BITMAPINFOHEADER, 8bpp) or raw DIB
  python -I bmh_encode.py <in.bmp> <out.BMH> --like <orig.BMH>   # copy header dwords 3..5 from an original
  python -I bmh_encode.py --selftest [RES dir]          # decode -> encode -> decode, compare DIB bytes
Never writes into the game folder unless you point <out.BMH> there yourself.
"""
import struct, sys, os, glob, heapq
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bmh_decode import bmh_to_dib, DEFAULT_SRC

MAXLEN = 16   # longest code seen in the original files


def code_lengths(freq):
    syms = [s for s in range(256) if freq[s]]
    if len(syms) == 1:
        return {syms[0]: 1}
    f = {s: freq[s] for s in syms}
    while True:
        heap = [(f[s], i, ('L', s)) for i, s in enumerate(syms)]
        heapq.heapify(heap)
        n = len(heap)
        while len(heap) > 1:
            a = heapq.heappop(heap)
            b = heapq.heappop(heap)
            heapq.heappush(heap, (a[0] + b[0], n, ('N', a[2], b[2])))
            n += 1
        lens = {}
        stack = [(heap[0][2], 0)]
        while stack:
            t, dpt = stack.pop()
            if t[0] == 'L':
                lens[t[1]] = dpt
            else:
                stack.append((t[1], dpt + 1))
                stack.append((t[2], dpt + 1))
        if max(lens.values()) <= MAXLEN:
            return lens
        f = {s: max(1, v >> 1) + 1 for s, v in f.items()}     # flatten and retry


class BitWriter:
    def __init__(self):
        self.buf = bytearray()
        self.acc = 0
        self.n = 0
        self.total = 0

    def put(self, code, ln):
        for i in range(ln - 1, -1, -1):
            self.acc = (self.acc << 1) | ((code >> i) & 1)
            self.n += 1
            if self.n == 8:
                self.buf.append(self.acc)
                self.acc = 0
                self.n = 0
        self.total += ln

    def finish(self):
        if self.n:
            self.buf.append(self.acc << (8 - self.n))
            self.acc = 0
            self.n = 0
        return bytes(self.buf)


def dib_to_bmh(dib, like_header=None):
    freq = [0] * 256
    for b in dib:
        freq[b] += 1
    lens = code_lengths(freq)
    # canonical (length, symbol) assignment
    codes = {}
    code = 0
    prev = 0
    for s in sorted(lens, key=lambda s: (lens[s], s)):
        code <<= (lens[s] - prev)
        prev = lens[s]
        codes[s] = code
        code += 1
    table = bytes(lens.get(s, 0) for s in range(256))
    cw = BitWriter()                           # explicit code bits, symbol order 0..255
    for s in range(256):
        if s in lens:
            cw.put(codes[s], lens[s])
    cbytes = cw.finish()
    dw = BitWriter()
    cl = [(codes[s], lens[s]) if s in lens else None for s in range(256)]
    for b in dib:
        c, l = cl[b]
        dw.put(c, l)
    dbytes = dw.finish()
    nbits = dw.total
    if like_header is not None:
        h3, h4, h5 = like_header
    else:
        h3 = struct.unpack('<I', dib[12:16])[0]
        h4 = struct.unpack('<I', dib[16:20])[0]
        h5 = struct.unpack('<I', dib[20:24])[0]
    body = struct.pack('<II', nbits, len(dib)) + table + cbytes + dbytes
    total = 24 + len(body)
    head = struct.pack('<IIIIII', total, len(dib), 0x4648, h3, h4, h5)
    return head + body


def bmp_to_dib(b):
    if b[:2] == b'BM':
        return b[14:]
    return b


def main(argv):
    if len(argv) >= 2 and argv[1] == '--selftest':
        src = argv[2] if len(argv) > 2 else DEFAULT_SRC
        files = sorted(set(glob.glob(os.path.join(src, '*.BMH')) + glob.glob(os.path.join(src, '*.bmh'))))
        ok = bad = 0
        osz = nsz = 0
        for f in files:
            d = open(f, 'rb').read()
            h, dib, _ = bmh_to_dib(d)
            e = dib_to_bmh(dib, like_header=h[3:6])
            h2, dib2, _ = bmh_to_dib(e)
            if dib2 == dib and h2[0] == len(e) and h2[1:] == h[1:]:
                ok += 1
            else:
                bad += 1
                print('MISMATCH', f)
            osz += len(d)
            nsz += len(e)
        print('roundtrip identical DIB: %d / %d  (orig total %d bytes, re-encoded %d bytes)' % (ok, ok + bad, osz, nsz))
        return 0 if bad == 0 else 1
    if len(argv) >= 3:
        dib = bmp_to_dib(open(argv[1], 'rb').read())
        like = None
        if len(argv) >= 5 and argv[3] == '--like':
            h, _, _ = bmh_to_dib(open(argv[4], 'rb').read())
            like = h[3:6]
        open(argv[2], 'wb').write(dib_to_bmh(dib, like))
        print('wrote', argv[2])
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
