"""Aplica o mar infinito (skybox 3D) a um VMF do rp_surdonoso: acrescenta a sala da skybox acima do mapa, com o plano de
mar a oeste, e o sky_camera. O resto do mapa não muda (a água da praia já vai até as bordas de tools/toolsskybox).
Ver praia_teste.py para o porquê de cada escolha (sala sem água, plano ht/mar_longe na altura do nível do mar).

`python tools/mar_surdonoso.py <entrada.vmf> <saida.vmf>`
"""
from __future__ import annotations

import sys
from pathlib import Path

from srctools import VMF

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from hammertools.core import vmf as vmfio  # noqa: E402
import praia_teste as praia  # noqa: E402


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    v = VMF.parse(src)
    if any(e["classname"] == "sky_camera" for e in v.entities):
        raise SystemExit(f"{src} já tem sky_camera: não aplico de novo")
    praia.sala_skybox(v)
    vmfio.save(v, dst)
    print(f"{dst}: sala da skybox 3D e sky_camera acrescentados (sky_camera em {praia.SKY_CAM})")


if __name__ == "__main__":
    main()
