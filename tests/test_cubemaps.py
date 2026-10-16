import struct

from hammertools import cubemaps


def _layout(v: bytes):
    w, h = struct.unpack_from("<HH", v, 16)
    fmt, mips = struct.unpack_from("<i", v, 52)[0], v[56]
    return w, h, fmt, mips


def test_placeholder_vtf_is_full_cube_with_mips():
    # VTF 7.0, 6 faces, mips até 1x1, sem miniatura: o bake do EchoHammer regrava só os pixels no mesmo lugar
    ldr, hdr = cubemaps.placeholder_vtf(32, False), cubemaps.placeholder_vtf(32, True)
    assert ldr[:4] == b"VTF\0" and _layout(ldr) == (32, 32, 3, 6) and _layout(hdr) == (32, 32, 24, 6)
    px = sum((32 >> m) ** 2 for m in range(6)) * 6
    assert len(ldr) == 64 + px * 3 and len(hdr) == 64 + px * 8
    assert struct.unpack_from("<i", ldr, 57)[0] == -1                       # sem miniatura
    assert struct.unpack_from("<I", ldr, 20)[0] & 0x4000                    # envmap
    g = ldr[64]
    assert ldr[64:67] == bytes((g, g, g)) and 100 < g < 140                 # cinza neutro (0,25 linear em gama 2,2)


def test_patched_name_carries_material_and_cubemap():
    m = cubemaps.PATCHED.match("maps/rp_x/metal/garagedoor01_a_-2009_-8373_-176")
    assert m.group(1) == "rp_x" and m.group(2) == "metal/garagedoor01_a"
    assert tuple(int(m.group(i)) for i in (3, 4, 5)) == (-2009, -8373, -176)
    assert cubemaps.VTF_NAME.match("materials/maps/rp_x/c-2009_-8373_-176.hdr.vtf")
