"""Minimal pure-stdlib QR Code encoder (byte mode, error-correction level L, versions 1-9 (up to 230 bytes)) that renders a PNG.

Backs CreateVirtualMFADevice's QRCodePNG so an authenticator app can scan the otpauth:// URI exactly as it
would from a real AWS console. stdlib only (zlib/struct) so it loads under Pyodide (Nano). The encoder follows
ISO/IEC 18004: Reed-Solomon over GF(256)/0x11d, block interleaving, function patterns, all 8 masks scored with
the four penalty rules, BCH-protected format and version information.
"""
from __future__ import annotations

import struct
import zlib

# version -> (ecc codewords per block, [(block count, data codewords per block), ...])  [level L]
_VER = {1: (7, [(1, 19)]), 2: (10, [(1, 34)]), 3: (15, [(1, 55)]), 4: (20, [(1, 80)]), 5: (26, [(1, 108)]),
        6: (18, [(2, 68)]), 7: (20, [(2, 78)]), 8: (24, [(2, 97)]), 9: (30, [(2, 116)])}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46]}

_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_remainder(data: list[int], n: int) -> list[int]:
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            nxt[j] ^= c
            nxt[j + 1] ^= _mul(c, _EXP[i])
        gen = nxt
    rem = [0] * n
    for b in data:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        if f:
            for i in range(n):
                rem[i] ^= _mul(gen[i + 1], f)
    return rem


def _pick_version(nbytes: int) -> int:
    for v in sorted(_VER):
        cap = sum(c * d for c, d in _VER[v][1])
        if nbytes + 2 <= cap:
            return v
    raise ValueError("data too long for this QR encoder (max 230 bytes)")


def _codewords(data: bytes, ver: int) -> list[int]:
    ecc, groups = _VER[ver]
    total = sum(c * d for c, d in groups)
    bits = "0100" + format(len(data), "08b") + "".join(format(b, "08b") for b in data)
    bits += "0" * min(4, total * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    cw = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(cw) < total:
        cw.append(pad[(len(cw) - len(bits) // 8) % 2])
    blocks, pos = [], 0
    for count, dlen in groups:
        for _ in range(count):
            d = cw[pos:pos + dlen]
            pos += dlen
            blocks.append((d, _rs_remainder(d, ecc)))
    out = []
    for i in range(max(len(d) for d, _ in blocks)):
        for d, _ in blocks:
            if i < len(d):
                out.append(d[i])
    for i in range(ecc):
        for _, e in blocks:
            out.append(e[i])
    return out


def _matrix(data: bytes) -> list[list[bool]]:
    ver = _pick_version(len(data))
    size = 17 + 4 * ver
    m = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def put(x, y, v):
        m[y][x] = v
        fn[y][x] = True

    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):          # finders + separators
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    put(x, y, max(abs(dx), abs(dy)) not in (2, 4) and max(abs(dx), abs(dy)) <= 3)
    for i in range(size):                                           # timing
        if not fn[6][i]:
            put(i, 6, i % 2 == 0)
        if not fn[i][6]:
            put(6, i, i % 2 == 0)
    pos = _ALIGN[ver]
    for iy, cy in enumerate(pos):                                   # alignment (not over the three finders)
        for ix, cx in enumerate(pos):
            if (ix, iy) in ((0, 0), (0, len(pos) - 1), (len(pos) - 1, 0)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    put(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
    for i in range(9):                                              # reserve format areas
        fn[8][i] = fn[i][8] = True
    for i in range(8):
        fn[8][size - 1 - i] = fn[size - 1 - i][8] = True
    put(8, size - 8, True)                                          # dark module (x=8, y=size-8)
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vb = ver << 12 | rem
        for i in range(18):
            bit, a, b = (vb >> i) & 1 == 1, size - 11 + i % 3, i // 3
            put(a, b, bit)
            put(b, a, bit)
    cws = _codewords(data, ver)
    i = 0
    for right in range(size - 1, 0, -2):                            # zigzag data placement
        if right <= 6:                                              # skip the vertical timing column
            right -= 1
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fn[y][x]:
                    if i < len(cws) * 8:
                        m[y][x] = (cws[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
    masks = (lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
             lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
             lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0)

    def with_mask(k):
        g = [row[:] for row in m]
        for y in range(size):
            for x in range(size):
                if not fn[y][x] and masks[k](x, y):
                    g[y][x] = not g[y][x]
        d = (1 << 3) | k                                            # level L = 01
        rem = d
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (d << 10 | rem) ^ 0x5412
        bit = lambda n: (bits >> n) & 1 == 1                        # noqa: E731
        for n in range(6):
            g[n][8] = bit(n)
        g[7][8], g[8][8], g[8][7] = bit(6), bit(7), bit(8)
        for n in range(9, 15):
            g[8][14 - n] = bit(n)
        for n in range(8):
            g[8][size - 1 - n] = bit(n)
        for n in range(8, 15):
            g[size - 15 + n][8] = bit(n)
        g[size - 8][8] = True
        return g

    def penalty(g):
        p = 0
        for rows in (g, [list(c) for c in zip(*g)]):                # rule 1 (runs) + rule 3 (finder-like), rows and columns
            for row in rows:
                run = 1
                for a, b in zip(row, row[1:]):
                    run = run + 1 if a == b else 1
                    if run == 5:
                        p += 3
                    elif run > 5:
                        p += 1
                s = "".join("1" if c else "0" for c in row)
                p += 40 * (s.count("10111010000") + s.count("00001011101"))
        for y in range(size - 1):                                   # rule 2 (2x2 blocks)
            for x in range(size - 1):
                if g[y][x] == g[y][x + 1] == g[y + 1][x] == g[y + 1][x + 1]:
                    p += 3
        dark = sum(c for row in g for c in row)                     # rule 4 (balance)
        p += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
        return p

    return min((with_mask(k) for k in range(8)), key=penalty)


def qr_png(text: str, scale: int = 6, border: int = 4) -> bytes:
    """PNG bytes of a QR code for `text` (UTF-8, byte mode, level L, up to 230 bytes)."""
    g = _matrix(text.encode("utf-8"))
    n = len(g) + 2 * border
    raw = bytearray()
    for y in range(n):
        row = bytearray()
        for x in range(n):
            gy, gx = y - border, x - border
            dark = 0 <= gy < len(g) and 0 <= gx < len(g) and g[gy][gx]
            row += (b"\x00" if dark else b"\xff") * scale
        raw += (b"\x00" + bytes(row)) * scale

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    px = n * scale
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", px, px, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
