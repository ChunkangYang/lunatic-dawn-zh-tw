#!/usr/bin/env python
"""BMH decoder (Lunatic Dawn / Ld95.exe .BMH container -> DIB -> PNG).  stdlib only.

Usage:
  python -I bmh_decode.py <in.BMH> <out.png>
  python -I bmh_decode.py --all <out_png_dir> [--src <RES dir>] [--inventory <csv>]
Format: see FORMAT.md (Huffman-coded BITMAPINFOHEADER + palette + pixels).
"""
import struct, sys, os, zlib, csv, glob

DEFAULT_SRC = r"C:\Program Files (x86)\Steam\steamapps\common\LunaticDawnPotB\RES"


# ---------------------------------------------------------------- BMH container
def _bitreader(buf, pos):
    while True:
        b = buf[pos]
        pos += 1
        for i in range(7, -1, -1):
            yield (b >> i) & 1


def bmh_to_dib(d):
    """Decompress a .BMH byte string. Returns (header6, dib_bytes, blocks)."""
    if len(d) < 24 or d[8:10] != b'HF':
        raise ValueError('bad magic (offset 8 is not "HF")')
    h = struct.unpack('<6I', d[:24])
    total = h[1]
    out = bytearray()
    p = 24
    blocks = []
    while len(out) < total:
        if p + 8 > len(d):
            raise ValueError('truncated block header')
        A, B = struct.unpack('<II', d[p:p + 8])
        if A == 0:                                   # stored block: B raw bytes
            out += d[p + 8:p + 8 + B]
            blocks.append(('raw', B))
            p += 8 + B
            continue
        lens = d[p + 8:p + 264]                      # 256 code lengths
        cb = (sum(lens) + 7) // 8                    # bytes of explicit code bits
        cbits = _bitreader(d, p + 264)
        t0 = [0x7fff] * 512
        t1 = [0x7fff] * 512
        n = 0
        for sym in range(256):
            ln = lens[sym]
            if not ln:
                continue
            node = 0
            for k in range(ln):
                t = t1 if next(cbits) else t0
                v = t[node]
                if v == 0x7fff:
                    if k == ln - 1:
                        t[node] = sym - 256          # leaf
                    else:
                        n += 1
                        t[node] = n
                        node = n
                else:
                    if k == ln - 1 or v < 0:
                        raise ValueError('inconsistent Huffman codes')
                    node = v
        ds = p + 264 + cb
        g = _bitreader(d, ds)
        for _ in range(B):
            node = 0
            while True:
                node = (t1 if next(g) else t0)[node]
                if node < 0:
                    out.append(node + 256)
                    break
        blocks.append(('huf', A, B))
        p = ds + (A + 7) // 8
    if len(out) != total:
        raise ValueError('size mismatch %d != %d' % (len(out), total))
    return h, bytes(out), blocks


# ---------------------------------------------------------------- DIB parsing
def parse_dib(dib):
    """Return dict(width,height,bpp,palette[(r,g,b)],rows(top-down, packed rows))."""
    (bisize, w, hgt, planes, bpp, comp, sizeimg, xpm, ypm, clrused, clrimp) = struct.unpack('<IiiHHIIiiII', dib[:40])
    if bisize != 40:
        raise ValueError('unsupported DIB header size %d' % bisize)
    if comp != 0:
        raise ValueError('unsupported biCompression %d' % comp)
    if bpp not in (1, 4, 8, 24, 32):
        raise ValueError('unsupported bitcount %d' % bpp)
    topdown = hgt < 0
    hgt = abs(hgt)
    npal = (clrused or (1 << bpp)) if bpp <= 8 else clrused
    pal = []
    for i in range(npal):
        b, g, r, _ = dib[40 + 4 * i:44 + 4 * i]
        pal.append((r, g, b))
    off = 40 + 4 * npal
    stride = ((w * bpp + 31) // 32) * 4
    need = off + stride * hgt
    if len(dib) < need:
        raise ValueError('pixel data short %d < %d' % (len(dib), need))
    rows = [dib[off + y * stride: off + y * stride + stride] for y in range(hgt)]
    if not topdown:
        rows.reverse()
    return dict(width=w, height=hgt, bpp=bpp, palette=pal, rows=rows, stride=stride)


# ---------------------------------------------------------------- PNG writer
def _chunk(t, data):
    c = struct.pack('>I', len(data)) + t + data
    return c + struct.pack('>I', zlib.crc32(t + data) & 0xffffffff)


def write_png(path, info):
    w, h, bpp = info['width'], info['height'], info['bpp']
    raw = bytearray()
    if bpp in (1, 4, 8):
        ctype, depth = 3, bpp
        rb = (w * bpp + 7) // 8
        for r in info['rows']:
            raw.append(0)
            raw += r[:rb]
        pal = info['palette'][:1 << depth]
        extra = _chunk(b'PLTE', bytes(v for c in pal for v in c))
    elif bpp == 24:
        ctype, depth, extra = 2, 8, b''
        for r in info['rows']:
            raw.append(0)
            row = r[:w * 3]
            raw += bytes(row[i + j] for i in range(0, w * 3, 3) for j in (2, 1, 0))
    else:  # 32 -> RGBA
        ctype, depth, extra = 6, 8, b''
        for r in info['rows']:
            raw.append(0)
            row = r[:w * 4]
            raw += bytes(row[i + j] for i in range(0, w * 4, 4) for j in (2, 1, 0, 3))
    png = (b'\x89PNG\r\n\x1a\n'
           + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, depth, ctype, 0, 0, 0)) + extra
           + _chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + _chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


def decode_file(path):
    with open(path, 'rb') as f:
        d = f.read()
    h, dib, blocks = bmh_to_dib(d)
    return parse_dib(dib), h, dib


def main(argv):
    if len(argv) >= 3 and argv[1] == '--all':
        outdir = argv[2]
        src = DEFAULT_SRC
        inv = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inventory.csv')
        i = 3
        while i < len(argv):
            if argv[i] == '--src':
                src = argv[i + 1]; i += 2
            elif argv[i] == '--inventory':
                inv = argv[i + 1]; i += 2
            else:
                raise SystemExit('unknown arg ' + argv[i])
        os.makedirs(outdir, exist_ok=True)
        files = sorted(glob.glob(os.path.join(src, '*.BMH')) + glob.glob(os.path.join(src, '*.bmh')))
        seen = set()
        files = [f for f in files if not (f.lower() in seen or seen.add(f.lower()))]
        ok = 0
        with open(inv, 'w', newline='', encoding='utf-8') as fo:
            cw = csv.writer(fo)
            cw.writerow(['file', 'width', 'height', 'bpp', 'decoded_ok', 'fail_reason', 'palette_entries', 'dib_bytes'])
            for f in files:
                name = os.path.basename(f)
                try:
                    info, h, dib = decode_file(f)
                    write_png(os.path.join(outdir, os.path.splitext(name)[0] + '.png'), info)
                    cw.writerow([name, info['width'], info['height'], info['bpp'], 'yes', '', len(info['palette']), len(dib)])
                    ok += 1
                except Exception as e:
                    cw.writerow([name, '', '', '', 'no', repr(e), '', ''])
                    print('FAIL', name, e)
        print('decoded %d / %d' % (ok, len(files)))
        return 0
    if len(argv) == 3:
        info, h, dib = decode_file(argv[1])
        write_png(argv[2], info)
        print('%dx%d %dbpp -> %s' % (info['width'], info['height'], info['bpp'], argv[2]))
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
