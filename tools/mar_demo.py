"""Gera maps/ht_mar_demo.vmf: mar "infinito" com água de verdade até a borda do mapa e o céu 2D com mar no horizonte.

Como funciona:
- a praia (x < -256) e o mar (brush de água: o material de água só na face de cima; laterais e fundo em
  tools/toolsnodraw), com um env_cubemap para o reflexo;
- a água vai até a borda do mapa jogável; a borda é uma casca selada de tools/toolsskybox2d (céu 2D). O céu 2D
  (sky34) tem o mar até o horizonte na metade de baixo, então a água do mapa encosta no horizonte do céu sem emenda.

Por que não skybox 3D (testado no Goldberg, gmod-gbe-mar):
- a passagem 3D desenhava uma faixa preta no horizonte por toda parede com tools/toolsskybox (com r_3dsky 0 a faixa
  some e o horizonte do sky34 fica limpo); trocar textura, tamanho e luz da sala, cubemap, fog e a altura da água
  dela não tirou a faixa;
- a água "cara" dentro da sala da skybox 3D sai escura e a água do mapa a reflete escura;
- fog junto com a sala apagava a água do mapa.
Sem a sala o mapa fica mais enxuto e não perde nada no mar aberto (não há o que mostrar em paralaxe).

`python tools/mar_demo.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

from srctools import VMF, Vec

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from hammertools.core import vmf as vmfio  # noqa: E402

AGUA = "NATURE/WATER_COAST01"     # água que já existe no conteúdo do rp_surdonoso (a mesma da praia dele)
NODRAW = "tools/toolsnodraw"
SKYBOX2D = "tools/toolsskybox2d"  # borda do mapa: mostra o céu 2D
CHAO = "concrete/concretefloor001a"
SKY2D = "sky34"                   # céu com mar até o horizonte (addon de conteúdo, tem que estar no servidor)
WATER_TOP = 0                     # altura da superfície da água


def box(v: VMF, lo, hi, mat: str, water_top: bool = False):
    """Brush. water_top: só a face de cima leva o material (água) e as demais ficam nodraw."""
    p = v.make_prism(Vec(*lo), Vec(*hi), NODRAW)
    if water_top:
        p.top.mat = mat
    else:
        for f in (p.top, p.bottom, p.north, p.south, p.east, p.west):
            f.mat = mat
    v.add_brush(p.solid)


def casca(v: VMF, x0: float, x1: float, y0: float, y1: float, z0: float = -640, z1: float = 1088,
          bairro: str | None = None) -> None:
    """Casca selada de céu 2D em volta de [x0,x1] x [y0,y1]; bairro ("east"/"west"/"north"/"south"): esse lado é uma
    parede de concreto comum (a orla que recebe o bairro), não céu."""
    t = 64
    lados = {
        "west": ((x0 - t, y0 - t, z0), (x0, y1 + t, z1)),
        "east": ((x1, y0 - t, z0), (x1 + t, y1 + t, z1)),
        "south": ((x0, y0 - t, z0), (x1, y0, z1)),
        "north": ((x0, y1, z0), (x1, y1 + t, z1)),
    }
    for nome, (lo, hi) in lados.items():
        box(v, lo, hi, CHAO if nome == bairro else SKYBOX2D)
    box(v, (x0 - t, y0 - t, z1 - 64), (x1 + t, y1 + t, z1), SKYBOX2D)   # teto
    box(v, (x0 - t, y0 - t, z0), (x1 + t, y1 + t, z0 + 64), SKYBOX2D)   # piso


def build() -> VMF:
    v = VMF()
    v.spawn["skyname"] = SKY2D
    H = 6144
    box(v, (-H, -H, -16), (-256, H, 0), CHAO)                               # praia
    box(v, (-256, -H, -512), (H, H, WATER_TOP), AGUA, water_top=True)       # mar até a borda
    box(v, (-256, -H, -576), (H, H, -512), CHAO)                            # fundo do mar
    casca(v, -H, H, -H, H)
    v.create_ent("env_cubemap", origin="-1024 0 64", cubemapsize="3")
    v.create_ent("light_environment", origin="0 0 900", angles="-50 35 0", pitch="-50",
                 _light="255 244 225 420", _ambient="140 170 200 120", SunSpreadAngle="3")
    v.create_ent("info_player_start", origin="-1024 0 16", angles="0 0 0")
    return v


def main() -> None:
    out = ROOT / "maps" / "ht_mar_demo.vmf"
    vmfio.save(build(), out)
    print(out)


if __name__ == "__main__":
    main()
