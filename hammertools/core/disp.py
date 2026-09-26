"""Displacements: caixa com a face de cima virando displacement, alturas por função."""
from __future__ import annotations

import math
from typing import Callable

from srctools import VMF, Vec
from srctools.vmf import Side, Solid


def terrain_tile(vmf: VMF, lo: Vec, hi: Vec, thickness: float, power: int, mat: str,
                 height_at: Callable[[float, float], float], side_mat: str = "tools/toolsnodraw") -> Solid:
    """Caixa de (lo.x,lo.y) a (hi.x,hi.y), base em lo.z - thickness e topo plano em lo.z, com a face de
    cima como displacement de `power` (2^power subdivisões). `height_at(u, v)` em [0,1]² devolve o
    deslocamento vertical do vértice. Vértice (x=0,y=0) = startposition = canto (lo.x, lo.y)."""
    prism = vmf.make_prism(Vec(lo.x, lo.y, lo.z - thickness), Vec(hi.x, hi.y, lo.z), side_mat)
    top = prism.top
    disp = Side(vmf, planes=list(top.planes), mat=mat, disp_power=power)
    disp.reset_uv()
    size = disp.disp_size
    disp.disp_pos = Vec(lo.x, lo.y, lo.z)
    for y in range(size):
        for x in range(size):
            vert = disp._disp_verts[y * size + x]
            vert.normal = Vec(0, 0, 1)
            vert.distance = float(height_at(x / (size - 1), y / (size - 1)))
            vert.offset = Vec()
    solid = prism.solid
    solid.sides = [disp if s is top else s for s in solid.sides]
    return solid


def value_noise(seed: int, scale: float = 1.0, octaves: int = 3) -> Callable[[float, float], float]:
    """Ruído determinístico em [0,1] (value noise com interpolação suave), sem dependências."""
    def hash01(ix: int, iy: int, o: int) -> float:
        n = (ix * 374761393 + iy * 668265263 + o * 2246822519 + seed * 3266489917) & 0xFFFFFFFF
        n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
        return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

    def smooth(t: float) -> float:
        return t * t * (3 - 2 * t)

    def noise(u: float, v: float) -> float:
        total, amp, freq, norm = 0.0, 1.0, scale, 0.0
        for o in range(octaves):
            x, y = u * freq, v * freq
            ix, iy = math.floor(x), math.floor(y)
            fx, fy = smooth(x - ix), smooth(y - iy)
            a, b = hash01(ix, iy, o), hash01(ix + 1, iy, o)
            c, d = hash01(ix, iy + 1, o), hash01(ix + 1, iy + 1, o)
            val = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
            total += val * amp
            norm += amp
            amp *= 0.5
            freq *= 2
        return total / norm
    return noise


def heightmap_png(path: str) -> Callable[[float, float], float]:
    """Lê um PNG em tons de cinza (via PIL se houver, senão via zlib puro) e devolve (u,v)->[0,1]."""
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        w, h = im.size
        px = im.load()
        get = lambda x, y: px[x, y] / 255.0
    except ImportError:
        import struct, zlib
        data = open(path, "rb").read()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "não é PNG"
        pos, chunks, w = 8, [], 0
        while pos < len(data):
            ln, typ = struct.unpack(">I4s", data[pos:pos + 8]); body = data[pos + 8:pos + 8 + ln]; pos += 12 + ln
            if typ == b"IHDR":
                w, h, depth, ctype = struct.unpack(">IIBB", body[:10]); assert depth == 8, "PNG precisa ser 8 bits"
                ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
            elif typ == b"IDAT":
                chunks.append(body)
        raw = zlib.decompress(b"".join(chunks)); stride = w * ch; rows = []; prev = bytearray(stride); i = 0
        for _ in range(h):
            f = raw[i]; line = bytearray(raw[i + 1:i + 1 + stride]); i += 1 + stride
            for j in range(stride):
                a = line[j - ch] if j >= ch else 0; b = prev[j]; c = prev[j - ch] if j >= ch else 0
                if f == 1: line[j] = (line[j] + a) & 255
                elif f == 2: line[j] = (line[j] + b) & 255
                elif f == 3: line[j] = (line[j] + (a + b) // 2) & 255
                elif f == 4:
                    p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    line[j] = (line[j] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            rows.append(bytes(line)); prev = line
        get = lambda x, y: rows[y][x * ch] / 255.0
    return lambda u, v: get(min(w - 1, int(round(u * (w - 1)))), min(h - 1, int(round((1 - v) * (h - 1)))))
