"""Recorta a praia oeste do rp_surdonoso_w_new (VMF mesclado) num mapa de teste pequeno, já com o mar infinito em skybox
3D, para iterar rápido sem compilar o mapa inteiro.

Mar infinito no Surdonoso (o que este teste valida):
- o mapa já tem a água da praia (NATURE/WATER_COAST01, topo em z=-551) indo até as bordas norte, sul e oeste, que são
  tools/toolsskybox;
- entra uma sala de skybox 3D bem acima do mapa (z ~8000) com um sky_camera em escala 16. Na sala NÃO pode haver água:
  água ali conflita com a água do mapa ("uma água por PVS") e a sala sai preta. O mar da sala é um plano comum com o
  material ht/mar_longe (UnlitGeneric, textura do mar na cor da água do mapa junto ao horizonte);
- o plano fica na altura que corresponde ao nível da água (z do sky_camera + (-551)/16) e cobre só o lado oeste
  (mundo x < -5119), que é para onde o mar continua.

`python tools/praia_teste.py <rp_surdonoso_w_new.vmf>` grava maps/ht_praia_teste.vmf.
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

# recorte: praia oeste (mar, areia, píer, pedras e a ilha) com folga
X0, X1 = -9200.0, -4800.0
Y0, Y1 = -9500.0, -5300.0
Z0, Z1 = -1500.0, 1500.0

NIVEL_MAR = -551          # topo da água da praia no Surdonoso
SCALE = 16
SKY_CAM = Vec(0, 0, 8000)  # sala da skybox 3D acima do mapa (o mapa vai até z ~1400)
SALA_H = 6000              # metade da sala (em unidades da sala)
MAR_LONGE = "ht/mar_longe"
MAR_ATE_X_MUNDO = -5119    # o plano cobre o mundo a oeste disto
# entidades do mapa inteiro que valem em qualquer lugar (luz, fog, tonemap): copiadas sempre, para o teste ser fiel
GLOBAIS = {"light_environment", "env_fog_controller", "env_tonemap_controller", "shadow_control", "water_lod_control"}


def dentro(lo, hi) -> bool:
    return lo[0] >= X0 and hi[0] <= X1 and lo[1] >= Y0 and hi[1] <= Y1 and lo[2] >= Z0 and hi[2] <= Z1


def bb(solid):
    pts = [tuple(p) for f in solid.sides for p in f.planes]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def sala_skybox(v: VMF) -> None:
    """Sala selada de céu 2D com o plano de mar (não é água) só a oeste."""
    cx, cy, cz = SKY_CAM.x, SKY_CAM.y, SKY_CAM.z
    h = SALA_H
    lo, hi = (cx - h, cy - h), (cx + h, cy + h)
    zmar = round(cz + NIVEL_MAR / SCALE)
    piso, teto = zmar - 64, cz + 512
    m.box(v, (lo[0], lo[1], piso - 64), (hi[0], hi[1], piso), m.SKYBOX2D)
    m.box(v, (lo[0], lo[1], teto), (hi[0], hi[1], teto + 64), m.SKYBOX2D)
    m.box(v, (lo[0] - 64, lo[1], piso), (lo[0], hi[1], teto), m.SKYBOX2D)
    m.box(v, (hi[0], lo[1], piso), (hi[0] + 64, hi[1], teto), m.SKYBOX2D)
    m.box(v, (lo[0], lo[1] - 64, piso), (hi[0], lo[1], teto), m.SKYBOX2D)
    m.box(v, (lo[0], hi[1], piso), (hi[0], hi[1] + 64, teto), m.SKYBOX2D)
    # plano do mar: do fundo da sala até a altura do nível do mar, só a oeste (x do mundo < MAR_ATE_X_MUNDO)
    x_fim = round(cx + MAR_ATE_X_MUNDO / SCALE)
    m.box(v, (lo[0], lo[1], piso), (x_fim, hi[1], zmar), MAR_LONGE, water_top=True)
    v.create_ent("sky_camera", origin=f"{cx:.0f} {cy:.0f} {cz:.0f}", scale=str(SCALE))


def main() -> None:
    src = Path(sys.argv[1])
    full = VMF.parse(src)
    v = VMF()
    for k in ("skyname", "detailmaterial", "detailvbsp", "maxpropscreenwidth"):
        if k in full.spawn:
            v.spawn[k] = full.spawn[k]
    n_b = n_e = 0
    for s in full.brushes:
        lo, hi = bb(s)
        if dentro(lo, hi):
            v.add_brush(s.copy(vmf_file=v))
            n_b += 1
    for e in full.entities:
        if e.solids:
            boxes = [bb(s) for s in e.solids]
            if all(dentro(lo, hi) for lo, hi in boxes):
                v.add_ent(e.copy(vmf_file=v))
                n_e += 1
        elif e["classname"] in GLOBAIS:
            v.add_ent(e.copy(vmf_file=v))
            n_e += 1
        elif e["origin"]:
            o = Vec.from_str(e["origin"])
            if X0 <= o.x <= X1 and Y0 <= o.y <= Y1 and Z0 <= o.z <= Z1 and e["classname"] not in ("info_player_start",):
                v.add_ent(e.copy(vmf_file=v))
                n_e += 1
    # casca de céu 2D em volta do recorte (fecha o lado da cidade, a leste)
    m.casca(v, X0, X1, Y0, Y1, z0=Z0, z1=Z1)
    sala_skybox(v)
    v.create_ent("info_player_start", origin="-5900 -7400 -400", angles="0 180 0")
    out = ROOT / "maps" / "ht_praia_teste.vmf"
    vmfio.save(v, out)
    print(f"{out}: {n_b} brushes e {n_e} entidades da praia")


if __name__ == "__main__":
    main()
