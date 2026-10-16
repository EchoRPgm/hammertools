"""VTF <-> imagem (PIL) sem dependências externas: lê DXT1/DXT5/RGBA8888/BGRA8888/BGR888/RGB888 (mip maior) e grava
VTF 7.0 RGBA8888 com a cadeia de mips completa (menor primeiro, como o Source). Usado pelos céus e texturas do mar.

  python tools/vtfimg.py png <entrada.vtf> <saida.png>
"""
from __future__ import annotations

import struct
import sys

from PIL import Image

DXT1, DXT5 = 13, 15
_FMT_BPP = {0: 4, 12: 4, 2: 3, 3: 3}


def _size(fmt: int, w: int, h: int) -> int:
    if fmt in (DXT1, 20):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    if fmt in (14, DXT5):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    return w * h * _FMT_BPP.get(fmt, 4)


def _c565(c: int) -> tuple[int, int, int]:
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def _dxt(data: bytes, w: int, h: int, bloco: int) -> bytes:
    out = bytearray(w * h * 4)
    pos = 0
    for by in range((h + 3) // 4):
        for bx in range((w + 3) // 4):
            if bloco == 16:
                pos += 8  # alfa do DXT5 ignorado (texturas de céu e mar são opacas)
            c0, c1, bits = struct.unpack_from("<HHI", data, pos)
            pos += 8
            a, b = _c565(c0), _c565(c1)
            if c0 > c1:
                cores = [a, b, tuple((2 * a[i] + b[i]) // 3 for i in range(3)), tuple((a[i] + 2 * b[i]) // 3 for i in range(3))]
            else:
                cores = [a, b, tuple((a[i] + b[i]) // 2 for i in range(3)), (0, 0, 0)]
            for py in range(4):
                for px in range(4):
                    x, y = bx * 4 + px, by * 4 + py
                    if x < w and y < h:
                        r, g, bb = cores[(bits >> (2 * (py * 4 + px))) & 3]
                        o = (y * w + x) * 4
                        out[o:o + 4] = bytes((r, g, bb, 255))
    return bytes(out)


def ler(path: str, max_lado: int = 4096) -> Image.Image:
    d = open(path, "rb").read()
    vmin = struct.unpack_from("<I", d, 8)[0]
    hdr = struct.unpack_from("<I", d, 12)[0]
    w, h = struct.unpack_from("<HH", d, 16)
    fmt = struct.unpack_from("<i", d, 52)[0]
    mips = d[56]
    lowfmt = struct.unpack_from("<i", d, 57)[0]
    loww, lowh = d[61], d[62]
    hires = hdr + (_size(lowfmt, loww, lowh) if lowfmt >= 0 and loww else 0)
    if vmin >= 3:
        for i in range(struct.unpack_from("<I", d, 68)[0]):
            o = 80 + 8 * i
            if d[o:o + 3] == b"\x30\x00\x00":
                hires = struct.unpack_from("<I", d, o + 4)[0]
    nivel = 0
    while nivel < mips - 1 and max(w >> nivel, h >> nivel) > max_lado:
        nivel += 1
    p = hires + sum(_size(fmt, max(1, w >> lv), max(1, h >> lv)) for lv in range(nivel + 1, mips))
    mw, mh = max(1, w >> nivel), max(1, h >> nivel)
    s = d[p:p + _size(fmt, mw, mh)]
    if fmt in (DXT1, 20):
        px = _dxt(s, mw, mh, 8)
    elif fmt == DXT5:
        px = _dxt(s, mw, mh, 16)
    elif fmt == 0:
        px = s
    elif fmt == 12:
        px = bytes(v for i in range(mw * mh) for v in (s[i * 4 + 2], s[i * 4 + 1], s[i * 4], s[i * 4 + 3]))
    elif fmt == 3:
        px = bytes(v for i in range(mw * mh) for v in (s[i * 3 + 2], s[i * 3 + 1], s[i * 3], 255))
    elif fmt == 2:
        px = bytes(v for i in range(mw * mh) for v in (s[i * 3], s[i * 3 + 1], s[i * 3 + 2], 255))
    else:
        raise ValueError(f"{path}: formato {fmt} não suportado")
    return Image.frombytes("RGBA", (mw, mh), px).convert("RGB")


def gravar(im: Image.Image, path: str, flags: int = 0x000C) -> None:
    """VTF 7.0 RGBA8888; flags padrão clamps|clampt (faces de céu)."""
    im = im.convert("RGBA")
    w, h = im.size
    mips, s = [], im
    while True:
        mips.append(s)
        if s.width == 1 and s.height == 1:
            break
        s = s.resize((max(1, s.width // 2), max(1, s.height // 2)), Image.BOX)
    hdr = bytearray(64)
    hdr[0:4] = b"VTF\0"
    struct.pack_into("<II", hdr, 4, 7, 0)
    struct.pack_into("<I", hdr, 12, 64)
    struct.pack_into("<HH", hdr, 16, w, h)
    struct.pack_into("<I", hdr, 20, flags)
    struct.pack_into("<HH", hdr, 24, 1, 0)
    r, g, b = [c / 255 for c in im.convert("RGB").resize((1, 1), Image.BOX).getpixel((0, 0))]
    struct.pack_into("<fff", hdr, 32, r, g, b)
    struct.pack_into("<f", hdr, 48, 1.0)
    struct.pack_into("<i", hdr, 52, 0)
    hdr[56] = len(mips)
    struct.pack_into("<i", hdr, 57, -1)
    with open(path, "wb") as f:
        f.write(bytes(hdr))
        for m in reversed(mips):
            f.write(m.tobytes())


CUBO = ("rt", "lf", "bk", "ft", "up", "dn")   # ordem das faces no VTF (+X -X +Y -Y +Z -Z)


def gravar_cubo(faces: dict, path: str, flags: int = 0x4000 | 0x000C | 0x0200) -> None:
    """Cubemap VTF 7.0 (envmap|clamps|clampt|nolod): faces = {"rt": img, ...}, já na orientação do cubemap.
    Na 7.0 (antes da 7.1, que trouxe a spheremap como 7ª face) o cubemap tem 6 faces."""
    ims = [faces[k].convert("RGBA") for k in CUBO]
    w, h = ims[0].size
    cadeias = []
    for im in ims:
        mips, s = [], im
        while True:
            mips.append(s)
            if s.width == 1 and s.height == 1:
                break
            s = s.resize((max(1, s.width // 2), max(1, s.height // 2)), Image.BOX)
        cadeias.append(mips)
    hdr = bytearray(64)
    hdr[0:4] = b"VTF\0"
    struct.pack_into("<II", hdr, 4, 7, 0)
    struct.pack_into("<I", hdr, 12, 64)
    struct.pack_into("<HH", hdr, 16, w, h)
    struct.pack_into("<I", hdr, 20, flags)
    struct.pack_into("<HH", hdr, 24, 1, 0)
    r, g, b = [c / 255 for c in ims[0].convert("RGB").resize((1, 1), Image.BOX).getpixel((0, 0))]
    struct.pack_into("<fff", hdr, 32, r, g, b)
    struct.pack_into("<f", hdr, 48, 1.0)
    struct.pack_into("<i", hdr, 52, 0)
    hdr[56] = len(cadeias[0])
    struct.pack_into("<i", hdr, 57, -1)
    with open(path, "wb") as f:
        f.write(bytes(hdr))
        for nivel in reversed(range(len(cadeias[0]))):   # mip menor primeiro; dentro do mip, face a face
            for mips in cadeias:
                f.write(mips[nivel].tobytes())


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "png":
        ler(sys.argv[2]).save(sys.argv[3])
    else:
        print(__doc__)
