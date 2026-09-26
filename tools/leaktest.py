"""Gera mapas onde a geometria GERADA é o selo do mapa (não tem sala em volta).
Cada mapa deve compilar sem leak. Compile na VM: tools/leaktest.sh"""
from __future__ import annotations

from pathlib import Path

from srctools import VMF, Vec

from hammertools.core import vmf as vmfio

OUT = Path(__file__).resolve().parent.parent / "maps" / "leak"
MAT = "dev/dev_measuregeneric01b"
T = 16  # espessura das paredes das salas


def box(v, lo, hi, mat=MAT):
    v.add_brush(v.make_prism(Vec(*lo), Vec(*hi), mat).solid)


def room(v, lo, hi, hole=None):
    """Sala oca com paredes de espessura T. `hole` = ("x+", (y0,y1), (z0,z1)) abre um buraco na parede +X
    (ou "y-" na parede -Y) com 4 pedaços em volta."""
    lo, hi = Vec(*lo), Vec(*hi)
    box(v, (lo.x, lo.y, lo.z - T), (hi.x, hi.y, lo.z))            # piso
    box(v, (lo.x, lo.y, hi.z), (hi.x, hi.y, hi.z + T))            # teto
    walls = {
        "x-": ((lo.x - T, lo.y - T, lo.z - T), (lo.x, hi.y + T, hi.z + T)),
        "x+": ((hi.x, lo.y - T, lo.z - T), (hi.x + T, hi.y + T, hi.z + T)),
        "y-": ((lo.x, lo.y - T, lo.z - T), (hi.x, lo.y, hi.z + T)),
        "y+": ((lo.x, hi.y, lo.z - T), (hi.x, hi.y + T, hi.z + T)),
    }
    for name, (a, b) in walls.items():
        if hole and hole[0] == name:
            (u0, u1), (z0, z1) = hole[1], hole[2]
            a, b = Vec(*a), Vec(*b)
            if name[0] == "x":   # buraco em Y/Z
                box(v, (a.x, a.y, a.z), (b.x, u0, b.z)); box(v, (a.x, u1, a.z), (b.x, b.y, b.z))
                box(v, (a.x, u0, a.z), (b.x, u1, z0)); box(v, (a.x, u0, z1), (b.x, u1, b.z))
            else:                # buraco em X/Z
                box(v, (a.x, a.y, a.z), (u0, b.y, b.z)); box(v, (u1, a.y, a.z), (b.x, b.y, b.z))
                box(v, (u0, a.y, a.z), (u1, b.y, z0)); box(v, (u0, a.y, z1), (u1, b.y, b.z))
        else:
            box(v, a, b)


def base(v):
    v.create_ent("light", origin="-256 0 200", _light="255 255 255 400")


def map_duct_between_rooms(sides: int, hollow_wall: int = 8):
    """Duto oco quadrado atravessa a parede de duas salas com cotovelo no meio: único selo é o duto."""
    v = VMF(); base(v)
    R = 48
    # sala A: x -512..0 ; buraco na parede +X (x 0..16) do tamanho EXTERNO do duto (y ±48, z 48..144)
    room(v, (-512, -256, 0), (0, 256, 256), hole=("x+", (-R, R), (96 - R, 96 + R)))
    # sala B: y 400..900 ; buraco na parede -Y (y 384..400) em x 208..304
    room(v, (128, 400, 0), (384, 900, 256), hole=("y-", (256 - R, 256 + R), (96 - R, 96 + R)))
    v.create_ent("info_player_start", origin="-256 0 8")
    v.create_ent("ht_pipe", origin="-64 0 96", targetname="duto", radius=str(R), sides=str(sides), hollow="1", wall=str(hollow_wall))
    v.create_ent("ht_pipe_node", origin="256 0 96", targetname="duto", order="1")
    v.create_ent("ht_pipe_end", origin="256 464 96", targetname="duto")
    return v


def map_duct_capped(sides: int):
    """Duto oco (quadrado ou octogonal) só, com cotovelo, pontas tampadas, jogador dentro. Sem sala."""
    v = VMF()  # sem base(): a luz da base ficaria no vazio (fora do duto) e vazaria por definição
    R = 48
    v.create_ent("ht_pipe", origin="0 0 96", targetname="duto", radius=str(R), sides=str(sides), hollow="1", wall="8", bend_radius="128")
    v.create_ent("ht_pipe_node", origin="512 0 96", targetname="duto", order="1")
    v.create_ent("ht_pipe_end", origin="512 512 96", targetname="duto")
    # tampas: caixas cobrindo as bocas (maiores que o perfil)
    box(v, (-32, -80, 0), (0, 80, 192)); box(v, (432, 512, 0), (592, 544, 192))
    v.create_ent("info_player_start", origin="128 0 60")
    v.create_ent("light", origin="128 0 120", _light="255 255 255 200")
    return v


def map_stairs_as_floor():
    """Dois níveis de piso; a escada sólida gerada fecha o degrau entre eles (é parede do mapa)."""
    v = VMF(); base(v)
    # caixa fechada de x -256..512, y -128..128, z 0..384, mas com o piso em dois níveis:
    # piso baixo z=0 em x -256..0, piso alto z=128 em x 128..512; entre 0 e 128 só a escada sela
    box(v, (-256 - T, -128 - T, -T), (512 + T, 128 + T, 0))            # laje de fundo geral (z -16..0)
    box(v, (128, -128, 0), (512, 128, 128))                             # bloco do piso alto (sólido)
    for a, b in ((( -256 - T, -128 - T, -T), (-256, 128 + T, 384)), ((512, -128 - T, -T), (512 + T, 128 + T, 384)),
                 ((-256, -128 - T, -T), (512, -128, 384)), ((-256, 128, -T), (512, 128 + T, 384)),
                 ((-256 - T, -128 - T, 384), (512 + T, 128 + T, 384 + T))):
        box(v, a, b)
    v.create_ent("info_player_start", origin="-128 0 8")
    v.create_ent("ht_stairs", origin="0 0 0", targetname="e", width="256", step_height="8")   # 16 degraus de 8x8
    v.create_ent("ht_stairs_end", origin="128 0 128", targetname="e")
    return v


def map_arch_in_wall():
    """Duas salas ligadas por um vão com arco gerado na divisória. As folgas entre o extradorso curvo
    e a laje reta acima ligam sala com sala (não com o vazio), então NÃO é leak; o teste garante que
    os solids do arco são válidos e não quebram o selo das salas."""
    v = VMF(); base(v)
    span, H = 256, 128
    # duas salas lado a lado com a divisória em x=0 e o arco no meio (y -128..128)
    room(v, (-512, -256, 0), (0, 256, 256), hole=("x+", (-span / 2, span / 2), (0, 256)))
    room(v, (16, -256, 0), (512, 256, 256), hole=("x-", (-span / 2, span / 2), (0, 256)))
    v.create_ent("info_player_start", origin="-256 0 8")
    # arco na divisória: profundidade 16 (= espessura x 0..16), altura 128, espessura radial 16
    v.create_ent("ht_arch", origin="8 -128 0", targetname="arco", height=str(H), segments="8", thickness="16", depth="16")
    v.create_ent("ht_arch_end", origin="8 128 0", targetname="arco")
    # parede em volta do arco: laje acima (z 128..256) + laterais fora do vão já são as paredes das salas;
    # sobra o espaço entre o extradorso e a laje reta: preenche com uma laje que desce até z=128-? Não:
    # o extradorso é curvo, então deixa-se uma laje reta de z=H até 256 e as quinas entre a curva e a laje
    # ficam ABERTAS de propósito? Não — isso seria leak do usuário. Fechamos com 2 blocos triangulares? Simples:
    # laje reta z H-16..256 (encosta no topo do arco, mas as laterais curvas ficam abertas -> LEAK esperado)
    box(v, (0, -span / 2, H), (16, span / 2, 256))
    return v


MAPS = {
    "leak_duct_square_rooms": lambda: map_duct_between_rooms(4),
    "leak_duct_square_capped": lambda: map_duct_capped(4),
    "leak_duct_octagon_capped": lambda: map_duct_capped(8),
    "leak_stairs_floor": map_stairs_as_floor,
    "leak_arch_wall": map_arch_in_wall,
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in MAPS.items():
        vmfio.save(fn(), OUT / f"{name}.vmf")
        print("gerado", name)
