"""Gera maps/ht_regioes_demo.vmf + .regioes.json: 4 pátios a céu aberto (DIA, ENTARDECER, NOITE, NEBLINA) em grade
2×2, ligados em anel por túneis de 128×128 que atravessam paredes de 512u; a borda de cada região passa no meio dos
túneis (a faixa de transição fica dentro deles). Demonstração da luz e do céu por região. Gera também a versão
`ht_regioes_demo_aberto`, com os túneis sem teto. `python tools/regioes_demo.py`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from srctools import VMF, Vec

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from hammertools.core import vmf as vmfio  # noqa: E402

HALF = 1312          # metade do mapa (parede externa por dentro)
WALL = 32
SEP = 256            # metade da largura das paredes entre pátios (512u)
H = 512              # altura das paredes
SKY_Z = 1024
TUN = 64             # metade da largura do túnel
TUN_H = 128
SKY = "tools/toolsskybox"
TUNNEL = "concrete/concretefloor028a"
SEPMAT = "concrete/concretewall008a"

# (nome, centro, piso, parede) — os pátios vão de centro-512 a centro+512
YARDS = [
    ("DIA", (-768, 768), "nature/blendgrassgravel001a", "brick/brickwall001a"),
    ("ENTARDECER", (768, 768), "concrete/concretefloor001a", "plaster/plasterwall003a"),
    ("NOITE", (768, -768), "metal/metalfloor001a", "concrete/concretewall008a"),
    ("NEBLINA", (-768, -768), "nature/dirtfloor003a", "stone/stonewall007a"),
]


def box(v: VMF, lo, hi, mat: str) -> None:
    v.add_brush(v.make_prism(Vec(*lo), Vec(*hi), mat).solid)


def build(open_tunnels: bool = False) -> tuple[VMF, dict]:
    """open_tunnels: túneis sem teto (corredor aberto até o céu): a troca de céu aparece durante a transição."""
    v = VMF()
    v.spawn["skyname"] = "sky_day01_01"
    # piso de cada pátio e dos túneis/paredes (uma laje só por baixo de tudo)
    for _, (cx, cy), floor, _ in YARDS:
        box(v, (cx - 512, cy - 512, -16), (cx + 512, cy + 512, 0), floor)
    for lo, hi in (((-HALF, -SEP, -16), (HALF, SEP, 0)), ((-SEP, SEP, -16), (SEP, HALF, 0)), ((-SEP, -HALF, -16), (SEP, -SEP, 0))):
        box(v, lo, hi, TUNNEL)
    # paredes externas e o céu: casca de toolsskybox acima das paredes e o teto
    o = HALF + WALL
    for lo, hi in (((-o, -o, -16), (o, -HALF, H)), ((-o, HALF, -16), (o, o, H)),
                   ((-o, -HALF, -16), (-HALF, HALF, H)), ((HALF, -HALF, -16), (o, HALF, H))):
        box(v, lo, hi, YARDS[0][3])
    for lo, hi in (((-o, -o, H), (o, -HALF, SKY_Z)), ((-o, HALF, H), (o, o, SKY_Z)),
                   ((-o, -HALF, H), (-HALF, HALF, SKY_Z)), ((HALF, -HALF, H), (o, HALF, SKY_Z)),
                   ((-o, -o, SKY_Z), (o, o, SKY_Z + 16)), ((-o, -o, -32), (o, o, -16))):
        box(v, lo, hi, SKY)
    # paredes entre os pátios (cruz de 512u), com os quatro túneis: em y=±768 pela barra vertical, x=±768 pela horizontal
    t = [768 - TUN, 768 + TUN]

    def bar_with_tunnels(axis: int) -> None:
        """axis 1: barra vertical (x em ±SEP, ao longo de y); axis 0: horizontal (y em ±SEP, ao longo de x, sem o centro)."""
        cuts = [(-HALF, -t[1]), (-t[1], -t[0]), (-t[0], t[0]), (t[0], t[1]), (t[1], HALF)]
        for a, b in cuts:
            spans = [(a, b)] if axis == 1 else [(max(a, -HALF), min(b, -SEP)), (max(a, SEP), min(b, HALF))]
            for s0, s1 in spans:
                if s1 <= s0:
                    continue
                tunnel = (a, b) in ((-t[1], -t[0]), (t[0], t[1]))
                if tunnel and open_tunnels:
                    continue
                z0 = TUN_H if tunnel else 0
                lo, hi = ((-SEP, s0, z0), (SEP, s1, H)) if axis == 1 else ((s0, -SEP, z0), (s1, SEP, H))
                box(v, lo, hi, SEPMAT)
    bar_with_tunnels(1)
    bar_with_tunnels(0)
    # peças para sombra em cada pátio: dois pilares e um pórtico
    for _, (cx, cy), _, wall in YARDS:
        box(v, (cx - 224, cy + 96, 0), (cx - 160, cy + 160, 256), wall)
        box(v, (cx + 160, cy - 160, 0), (cx + 224, cy - 96, 192), wall)
        box(v, (cx - 64, cy - 256, 0), (cx - 32, cy - 224, 160), wall)
        box(v, (cx + 32, cy - 256, 0), (cx + 64, cy - 224, 160), wall)
        box(v, (cx - 64, cy - 256, 160), (cx + 64, cy - 224, 192), wall)
    # luz: sol + céu; lâmpadas no meio de cada túnel e duas na NOITE
    v.create_ent("light_environment", origin="0 0 900", angles="-50 35 0", pitch="-50",
                 _light="255 240 220 450", _ambient="150 180 220 140", SunSpreadAngle="3")
    for x, y in ((0, 768), (768, 0), (0, -768), (-768, 0)):
        v.create_ent("light", origin=f"{x} {y} {TUN_H - 16}", _light="255 220 170 120")
    for x, y in ((600, -600), (940, -940)):
        v.create_ent("light", origin=f"{x} {y} 200", _light="255 190 110 300")
    v.create_ent("info_player_start", origin="-768 768 16", angles="0 0 0")
    # caixas além das paredes externas (meia faixa de folga): a borda de fora não pode cair na face das paredes
    E = HALF + WALL + 128
    regions = {
        "versao": 1,
        "transicao": 128,
        "regioes": [
            {"nome": "DIA", "mins": [-E, 0, -64], "maxs": [0, E, SKY_Z + 64], "luz": {}, "ceu": {"skyname": "sky_day01_01"}},
            {"nome": "ENTARDECER", "mins": [0, 0, -64], "maxs": [E, E, SKY_Z + 64],
             "luz": {"mult_sol": 0.55, "sol_cor": [255, 150, 70], "mult_ceu": 0.8, "ceu_cor": [255, 170, 120]},
             "ceu": {"skyname": "sky_day03_06"}},
            {"nome": "NOITE", "mins": [0, -E, -64], "maxs": [E, 0, SKY_Z + 64],
             "luz": {"mult_sol": 0.0, "mult_ceu": 0.15, "ceu_cor": [60, 80, 160], "mult_indireta": 1.2},
             "ceu": {"skyname": "sky_borealis01", "neblina": {"cor": [10, 14, 30], "inicio": 512, "fim": 4096, "densidade": 0.5}}},
            {"nome": "NEBLINA", "mins": [-E, -E, -64], "maxs": [0, 0, SKY_Z + 64],
             "luz": {"mult_sol": 0.3, "mult_ceu": 1.2, "ceu_cor": [150, 170, 150], "rebotes": 12, "filtro": 5,
                     "escala_lightmap": 8, "ambiente": [10, 14, 10]},
             "ceu": {"cor": [140, 155, 140], "neblina": {"cor": [140, 155, 140], "inicio": 64, "fim": 900, "densidade": 0.85},
                     "skybox3d": False}},
        ],
    }
    return v, regions


def main() -> None:
    for name, open_tunnels in (("ht_regioes_demo", False), ("ht_regioes_demo_aberto", True)):
        v, regions = build(open_tunnels)
        out = ROOT / "maps" / f"{name}.vmf"
        vmfio.save(v, out)
        out.with_suffix(".regioes.json").write_text(json.dumps(regions, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{out} e {out.with_suffix('.regioes.json').name}")


if __name__ == "__main__":
    main()
