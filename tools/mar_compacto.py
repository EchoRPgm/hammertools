"""Gera maps/ht_mar_compacto.vmf: a versão enxuta do mar infinito, cabendo na área de praia do rp_surdonoso.

Área medida no rp_surdonoso_w_new (versão 692, brushes de água NATURE/WATER_COAST01 na praia oeste): x -9098..-5869,
y -8904..-5908, ~3229 x 2996 u. Aqui a área jogável é 3200 x 3000 (coordenadas locais, origem no centro):
- mar a oeste, norte e sul: a borda vira skybox 3D (tools/toolsskybox), e a miniatura do mar continua o horizonte;
- praia a leste: a orla que vai receber o bairro é uma parede de concreto comum (CHAO). Quando o bairro entrar, troca-se
  essa parede pela junção com o bairro (ver BAIRRO_X);
- teto e piso selados (tools/toolsskybox2d), sem vazamento.

Reaproveita as peças de mar_demo.py (água, sala da skybox 3D, faces). `python tools/mar_compacto.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

from srctools import VMF, Vec

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from hammertools.core import vmf as vmfio  # noqa: E402
import mar_demo as m  # noqa: E402

X0, X1 = -1600, 1600              # área jogável
Y0, Y1 = -1500, 1500
MAR_ATE_X = -300                  # água de X0 até aqui; o resto é praia
BAIRRO_X = X1                     # orla que recebe o bairro (parede de concreto, a trocar quando o bairro entrar)
H = 64                            # espessura das paredes


def casca(v: VMF) -> None:
    """Hull selado: três lados de mar (skybox 3D por dentro), o lado do bairro em concreto, teto e piso 2D."""
    m.box(v, (X0 - H, Y0 - H, -576), (X0, Y1 + H, 1024), m.SKYBOX2D, sky3d=("east",))   # oeste (mar)
    m.box(v, (X0, Y1, -576), (X1, Y1 + H, 1024), m.SKYBOX2D, sky3d=("south",))          # norte (mar)
    m.box(v, (X0, Y0 - H, -576), (X1, Y0, 1024), m.SKYBOX2D, sky3d=("north",))          # sul (mar)
    m.box(v, (BAIRRO_X, Y0 - H, -576), (BAIRRO_X + H, Y1 + H, 1024), m.CHAO)            # leste (bairro)
    m.box(v, (X0 - H, Y0 - H, 1024), (BAIRRO_X + H, Y1 + H, 1088), m.SKYBOX2D)          # teto
    m.box(v, (X0 - H, Y0 - H, -640), (BAIRRO_X + H, Y1 + H, -576), m.SKYBOX2D)          # piso


def build() -> VMF:
    v = VMF()
    v.spawn["skyname"] = m.SKY2D
    # praia (concreto) a leste da água
    m.box(v, (MAR_ATE_X, Y0, -16), (X1, Y1, 0), m.CHAO)
    # mar: de X0 até MAR_ATE_X, superfície em z = 0; fundo de concreto sob ele
    m.box(v, (X0, Y0, -512), (MAR_ATE_X, Y1, m.WATER_TOP), m.AGUA, water_top=True)
    m.box(v, (X0, Y0, -576), (MAR_ATE_X, Y1, -512), m.CHAO)
    casca(v)
    m.sala_skybox(v)
    v.create_ent("sky_camera", origin=f"{m.SKY_CAM.x:.0f} {m.SKY_CAM.y:.0f} {m.SKY_CAM.z:.0f}", scale=str(m.SCALE))
    v.create_ent("env_fog_controller", origin="0 0 0", fogenable="1", fogcolor="40 92 118", fogstart="2000",
                 fogend="16000", fogmaxdensity="0.9")
    v.create_ent("light_environment", origin="0 0 900", angles="-50 35 0", pitch="-50",
                 _light="255 244 225 420", _ambient="140 170 200 120", SunSpreadAngle="3")
    v.create_ent("info_player_start", origin="800 0 16", angles="0 0 0")
    return v


def main() -> None:
    out = ROOT / "maps" / "ht_mar_compacto.vmf"
    vmfio.save(build(), out)
    print(out)


if __name__ == "__main__":
    main()
