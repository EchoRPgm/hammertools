"""Gera maps/test_stairs.vmf: sala fechada com um exemplo de cada gerador. `python tools/fixture.py`."""
from __future__ import annotations

import sys
from pathlib import Path

from srctools import Vec

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from conftest import base_room  # noqa: E402

from hammertools.core import vmf as vmfio  # noqa: E402

MAT = "dev/dev_measuregeneric01b"   # sala (cinza escuro)
PENDING = "dev/dev_measuregeneric01"   # LARANJA: construto ainda não validado no jogo
OK = "dev/graygrid"                    # cinza claro: validado no jogo

# Status de validação por marcador: "ok" (validado no jogo) ou "pending". Atualizar conforme testado.
STATUS = {
    "escada1": "ok", "escada2": "ok", "corrimao1": "ok", "cerca1": "ok", "cerca2": "ok", "ladder1": "ok",
    "arco1": "ok", "tubo1": "ok", "duto1": "ok", "curva1": "ok",
    "porta1": "ok", "luzes1": "ok", "elev1": "ok", "spawn1": "ok",
    "cabo1": "pending", "trilho1": "pending", "terreno1": "ok", "cubemaps1": "pending", "zona1": "pending",
}


def mat(name: str) -> str:
    return OK if STATUS.get(name, "pending") == "ok" else PENDING


def box(v, lo, hi, mat=MAT):
    v.add_brush(v.make_prism(Vec(*lo), Vec(*hi), mat).solid)


def build():
    v = base_room(size=1536, height=640)  # piso z=0, paredes em ±1536
    # --- sprint 1/2
    v.create_ent("ht_stairs", origin="-256 0 0", targetname="escada1", width="96", material=mat("escada1"))
    v.create_ent("ht_stairs_end", origin="-64 0 96", targetname="escada1")
    v.create_ent("ht_stairs", origin="256 -128 0", targetname="escada2", style="floating", material=mat("escada2"))
    v.create_ent("ht_stairs_end", origin="256 128 128", targetname="escada2")
    v.create_ent("ht_railing", origin="-256 48 0", targetname="corrimao1", material=mat("corrimao1"))
    v.create_ent("ht_railing_end", origin="-64 48 96", targetname="corrimao1")
    v.create_ent("ht_fence", origin="-640 -512 0", targetname="cerca1", spacing="64", height="64", material=mat("cerca1"))
    v.create_ent("ht_fence_end", origin="-640 200 0", targetname="cerca1")
    v.create_ent("ht_fence", origin="640 -512 0", targetname="cerca2", mode="prop")
    v.create_ent("ht_fence_end", origin="640 300 0", targetname="cerca2")
    # escada de mão: sobe a face frontal (x=1408) de uma plataforma encostada na parede +X
    box(v, (1408, -704, 176), (1536, -576, 192))
    v.create_ent("ht_ladder", origin="1408 -640 0", targetname="ladder1", angles="0 0 0", material=mat("ladder1"))
    v.create_ent("ht_ladder_end", origin="1408 -640 192", targetname="ladder1")
    # --- sprint 3
    v.create_ent("ht_arch", origin="-384 640 0", targetname="arco1", segments="12", thickness="16", depth="32", material=mat("arco1"))
    v.create_ent("ht_arch_end", origin="-128 640 0", targetname="arco1")
    v.create_ent("ht_pipe", origin="0 -960 32", targetname="tubo1", radius="16", sides="8", material=mat("tubo1"))
    v.create_ent("ht_pipe_node", origin="384 -960 32", targetname="tubo1", order="1")
    v.create_ent("ht_pipe_node", origin="384 -960 224", targetname="tubo1", order="2")
    v.create_ent("ht_pipe_end", origin="640 -960 224", targetname="tubo1")
    v.create_ent("ht_pipe", origin="-960 -960 64", targetname="duto1", radius="48", sides="4", hollow="1", wall="8", material=mat("duto1"))
    v.create_ent("ht_pipe_node", origin="-960 -640 64", targetname="duto1", order="1")
    v.create_ent("ht_pipe_end", origin="-640 -640 64", targetname="duto1")
    v.create_ent("ht_stairs_curve", origin="384 384 0", targetname="curva1", width="64", material=mat("curva1"))
    v.create_ent("ht_stairs_curve_ctrl", origin="704 384 0", targetname="curva1")
    v.create_ent("ht_stairs_curve_end", origin="704 704 160", targetname="curva1")
    # --- sprint 4
    # porta numa parede divisória x -1024..-1008, y 1024..1408, z 0..128, com o VÃO cortado:
    # porta em y=1216, largura 56 -> vão y 1188..1244 z 0..112; batente (8) ocupa 1180..1188, 1244..1252 e z 112..120
    box(v, (-1024, 1024, 0), (-1008, 1180, 128))
    box(v, (-1024, 1252, 0), (-1008, 1408, 128))
    box(v, (-1024, 1180, 120), (-1008, 1252, 128))
    v.create_ent("ht_door", origin="-1016 1216 0", targetname="porta1", angles="0 0 0", auto_open="1", frame_depth="16", material_frame=mat("porta1"))
    v.create_ent("ht_lights", origin="-512 -256 560", targetname="luzes1", spacing="192", with_prop="1")
    v.create_ent("ht_lights_end", origin="512 -256 560", targetname="luzes1")
    v.create_ent("ht_elevator", origin="1024 1024 0", targetname="elev1", angles="0 0 0", width="128", depth="128", material=mat("elev1"))
    v.create_ent("ht_elevator_end", origin="1024 1024 256", targetname="elev1")
    box(v, (1096, 960, 248), (1400, 1088, 264))  # patamar de chegada ao lado (+X): piso em rise(256) + espessura(8)
    v.create_ent("ht_spawnroom", origin="-1408 -1408 0", targetname="spawn1", angles="0 45 0", spacing="64", margin="32")
    v.create_ent("ht_spawnroom_end", origin="-1152 -1216 0", targetname="spawn1")
    # --- sprint 5
    v.create_ent("ht_rope", origin="-1400 800 400", targetname="cabo1", slack="40")            # cabo pendurado entre 3 pontos
    v.create_ent("ht_rope_node", origin="-900 1000 440", targetname="cabo1", order="1")
    v.create_ent("ht_rope_end", origin="-400 1300 400", targetname="cabo1")
    # circuito elevado de trem dando a volta na sala (z=300), automático
    v.create_ent("ht_rope", origin="-1400 -1300 300", targetname="trilho1", kind="rail", train="1", train_mode="auto", loop="1", train_speed="250", material=mat("trilho1"))
    v.create_ent("ht_rope_node", origin="1400 -1300 300", targetname="trilho1", order="1")
    v.create_ent("ht_rope_node", origin="1400 1300 300", targetname="trilho1", order="2")
    v.create_ent("ht_rope_end", origin="-1400 1300 300", targetname="trilho1")
    v.create_ent("ht_terrain", origin="1024 -1536 0", targetname="terreno1", tile="512", power="3", amplitude="48", thickness="16", material=mat("terreno1"))
    v.create_ent("ht_terrain_end", origin="1536 -1024 0", targetname="terreno1")               # canto +X/-Y da sala, 512x512
    v.create_ent("ht_cubemaps", origin="-1408 -1408 96", targetname="cubemaps1", spacing="512", margin="128")
    v.create_ent("ht_cubemaps_end", origin="1408 1408 96", targetname="cubemaps1")
    v.create_ent("ht_zone", origin="-960 -1024 0", targetname="zona1", kind="block_los", height="96")  # atrás do duto
    v.create_ent("ht_zone_end", origin="-640 -960 0", targetname="zona1")
    return v


if __name__ == "__main__":
    out = ROOT / "maps" / "test_stairs.vmf"
    vmfio.save(build(), out)
    print("fixture:", out)
