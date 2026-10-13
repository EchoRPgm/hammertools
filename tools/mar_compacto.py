"""Gera maps/ht_mar_compacto.vmf: a versão enxuta do mar infinito, cabendo na área de praia do rp_surdonoso.

Área medida no rp_surdonoso_w_new (versão 692, brushes de água NATURE/WATER_COAST01 na praia oeste): x -9098..-5869,
y -8904..-5908, ~3229 x 2996 u. Aqui a área jogável é 3200 x 3000 (coordenadas locais, origem no centro):
- mar a oeste, norte e sul: a água vai até a borda, que é céu 2D (sky34, mar até o horizonte), sem emenda;
- praia a leste: a orla que vai receber o bairro é uma parede de concreto comum. Quando o bairro entrar, troca-se essa
  parede pela junção com o bairro;
- teto e piso selados, sem vazamento. Sem skybox 3D (ver mar_demo.py: a passagem 3D fazia uma faixa preta).

`python tools/mar_compacto.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

from srctools import VMF

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from hammertools.core import vmf as vmfio  # noqa: E402
import mar_demo as m  # noqa: E402

X0, X1 = -1600, 1600              # área jogável
Y0, Y1 = -1500, 1500
MAR_ATE_X = -300                  # água de X0 até aqui; o resto é praia


def build() -> VMF:
    v = VMF()
    v.spawn["skyname"] = m.SKY2D
    m.box(v, (MAR_ATE_X, Y0, -16), (X1, Y1, 0), m.CHAO)                          # praia
    m.box(v, (X0, Y0, -512), (MAR_ATE_X, Y1, m.WATER_TOP), m.AGUA, water_top=True)   # mar até a borda
    m.box(v, (X0, Y0, -576), (MAR_ATE_X, Y1, -512), m.CHAO)                      # fundo do mar
    m.casca(v, X0, X1, Y0, Y1, bairro="east")
    v.create_ent("env_cubemap", origin="0 0 64", cubemapsize="3")
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
