"""Gera maps/ht_mar_demo.vmf: mar "infinito" com brush de água no mapa + 3D skybox com uma cópia do mar em escala 1/16.

Como funciona (a técnica dos mapas de praia do GMod e da Source):
- o mapa jogável tem uma praia (x < 0) e água de verdade (brush com o material de água só na face de cima; as laterais
  e o fundo são tools/toolsnodraw), com env_cubemap para o reflexo;
- a skybox 3D (sky_camera) é uma miniatura do mesmo mar: a sala fica fora do mapa, numa área separada, e a superfície
  da água da sala fica na altura do sky_camera. O motor desenha a sala em escala 16 ao redor da origem do jogo, então o
  mar ocupa todo o horizonte: a água da sala fica com a mesma cor e altura da do mapa, sem fim visível;
- o céu 2D (sky34, mar com horizonte) fica atrás da sala e completa o fundo;
- sem fog: o fog junto da sala da skybox 3D fez a água do mapa sumir no teste do Goldberg.

Sem a sala da skybox 3D, o horizonte seria o limite da geometria (ou o céu 2D, que é uma imagem parada).

`python tools/mar_demo.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

from srctools import VMF, Vec

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from hammertools.core import vmf as vmfio  # noqa: E402

AGUA = "NATURE/WATER_COAST01"     # água que já existe no GMod base (o mapa rp_surdonoso usa a mesma)
NODRAW = "tools/toolsnodraw"
SKYBOX3D = "tools/toolsskybox"      # faces que mostram a skybox 3D (a miniatura do mar aparece por elas)
SKYBOX2D = "tools/toolsskybox2d"    # paredes do volume selado da miniatura (o que está atrás dela é o céu 2D)
CHAO = "concrete/concretefloor001a"
SKY2D = "sky34"                   # mar com horizonte (addon de conteúdo, tem que estar no servidor)

SCALE = 16                        # escala da skybox 3D (a miniatura é 1/16 do mundo)
WATER_TOP = 0                     # altura da superfície da água, igual nas duas áreas
SKY_CAM = Vec(-10000, 10000, 0)   # sky_camera: fora do mapa jogável, na altura da água


def box(v: VMF, lo, hi, mat: str, water_top: bool = False, sky3d: tuple = ()):
    """Brush. water_top: só a face de cima leva a água e as demais ficam nodraw. sky3d: faces de borda ("east", "west",
    "north", "south") que devem mostrar a skybox 3D (tools/toolsskybox), em vez de nodraw."""
    p = v.make_prism(Vec(*lo), Vec(*hi), NODRAW)
    if water_top:
        p.top.mat = AGUA
    else:
        for f in (p.top, p.bottom, p.north, p.south, p.east, p.west):
            f.mat = mat
    for lado in sky3d:
        getattr(p, lado).mat = SKYBOX3D
    v.add_brush(p.solid)


def sala_skybox(v: VMF) -> None:
    """Miniatura do mar: sala de 4096 x 4096 (vira 65536 no mundo), água até z=0. O volume da sala é selado com
    tools/toolsskybox2d (é a casca do 3D; atrás dela o céu 2D, sky34, completa o horizonte)."""
    cx, cy = SKY_CAM.x, SKY_CAM.y
    h = 2048
    lo, hi = (cx - h, cy - h), (cx + h, cy + h)
    box(v, (lo[0], lo[1], -320), (hi[0], hi[1], -256), SKYBOX2D)       # piso
    box(v, (lo[0], lo[1], 512), (hi[0], hi[1], 576), SKYBOX2D)         # teto
    box(v, (lo[0] - 64, lo[1], -256), (lo[0], hi[1], 512), SKYBOX2D)   # oeste
    box(v, (hi[0], lo[1], -256), (hi[0] + 64, hi[1], 512), SKYBOX2D)   # leste
    box(v, (lo[0], lo[1] - 64, -256), (hi[0], lo[1], 512), SKYBOX2D)   # sul
    box(v, (lo[0], hi[1], -256), (hi[0], hi[1] + 64, 512), SKYBOX2D)   # norte
    # o mar da miniatura: superfície em z = WATER_TOP
    box(v, (lo[0], lo[1], -256), (hi[0], hi[1], WATER_TOP), AGUA, water_top=True)
    v.create_ent("env_cubemap", origin=f"{cx:.0f} {cy:.0f} -64", cubemapsize="3")




def hull(v: VMF) -> None:
    """Casca selada em volta do mapa jogável: sem ela o ar acima e abaixo do mar vaza (o vbsp marca vazamento).
    As paredes têm a face de dentro em tools/toolsskybox (é ali que a miniatura 3D aparece, o mar que continua) e o
    resto em tools/toolsskybox2d; o teto (céu 2D sobre a praia) e o piso são 2D."""
    H = 6144
    box(v, (H, -H, -576), (H + 64, H, 1024), SKYBOX2D, sky3d=("west",))        # leste: dentro é o lado -x
    box(v, (-H - 64, -H, -576), (-H, H, 1024), SKYBOX2D, sky3d=("east",))      # oeste: dentro é +x
    box(v, (-H, H, -576), (H, H + 64, 1024), SKYBOX2D, sky3d=("south",))       # norte: dentro é -y
    box(v, (-H, -H - 64, -576), (H, -H, 1024), SKYBOX2D, sky3d=("north",))     # sul: dentro é +y
    box(v, (-H, -H, 1024), (H, H, 1088), SKYBOX2D)                              # teto
    box(v, (-H, -H, -640), (H, H, -576), SKYBOX2D)                              # piso


def build() -> VMF:
    v = VMF()
    v.spawn["skyname"] = SKY2D
    # praia: chão de concreto de x=-6144 a x=-256 (de y=-6144 a 6144), no nível da água
    # praia: concreto de x=-6144 a x=-256, no nível da água
    box(v, (-6144, -6144, -16), (-256, 6144, 0), CHAO)
    # mar do mapa: água de x=-256 até a borda; a face de cima na altura WATER_TOP, o resto do brush sob ela.
    # O brush de água não leva faces de skybox 3D: o vbsp exige $bottommaterial nelas (são tratadas como da água).
    box(v, (-256, -6144, -512), (6144, 6144, WATER_TOP), AGUA, water_top=True)
    # fundo do mar (água sobre concreto)
    box(v, (-256, -6144, -576), (6144, 6144, -512), CHAO)
    hull(v)
    sala_skybox(v)
    # sem fog em lugar nenhum: com a sala da skybox 3D, o fog (do mundo ou do sky_camera) fez a água do mapa sumir
    v.create_ent("sky_camera", origin=f"{SKY_CAM.x:.0f} {SKY_CAM.y:.0f} {SKY_CAM.z:.0f}", scale=str(SCALE))
    v.create_ent("env_cubemap", origin="-1024 0 -64", cubemapsize="3")
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
