"""Céu como "window imposter": cubemap (shader WindowImposter) com as faces de uma skybox, para mostrar o céu de uma
região em superfícies do mundo, vários céus no mesmo mapa.

O WindowImposter amostra o cubemap na direção olho -> superfície, então uma superfície com ele fica igual ao céu
daquele skyname visto por ela, de qualquer ponto. As faces da skybox (rt lf bk ft up dn) entram no cubemap na mesma
ordem, com a orientação medida no GMod por tools/imposter_teste.py (céu de coordenadas, captura do céu de verdade e do
imposter na mesma pose): rt, up e dn transpostas; lf transposta pela outra diagonal; bk espelhada na vertical e ft na
horizontal.

  python tools/imposter.py cubo <pasta skybox> <nome> <addon> [lado]
      -> <addon>/materials/envmaps/<nome>.vtf/.vmt (lado padrão 512)
  python tools/imposter.py faces <mapa.bsp> <mapa.regioes.json> <grupo,...> [--embutir]
      -> chave "imposters" ({skyname: [polígonos]}) no JSON embutido no BSP (data_static/ht_regioes/<mapa>.json);
         o JSON de origem não muda (o editor de regiões não carrega milhares de vértices)

Faces: as de céu do BSP (SKYBOX_2D/3D) cujo centro cai numa região dos grupos dados (a primeira da lista que contém
o ponto, como no echorp_ceu), deslocadas 1 unidade para dentro do mapa. O echorp_ceu desenha cada skyname com o
material envmaps/<skyname>.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vtfimg  # noqa: E402

ORIENT = {"rt": Image.TRANSPOSE, "lf": Image.TRANSVERSE, "bk": Image.FLIP_TOP_BOTTOM,
          "ft": Image.FLIP_LEFT_RIGHT, "up": Image.TRANSPOSE, "dn": Image.TRANSPOSE}


def faces_cubo(faces: dict[str, Image.Image], lado: int) -> dict[str, Image.Image]:
    return {k: im.convert("RGB").resize((lado, lado), Image.LANCZOS).transpose(ORIENT[k]) for k, im in faces.items()}


def cubo(pasta: Path, nome: str, addon: Path, lado: int = 512) -> Path:
    faces = {k: vtfimg.ler(str(pasta / f"{nome}{k}.vtf")) for k in vtfimg.CUBO}
    env = addon / "materials" / "envmaps"
    env.mkdir(parents=True, exist_ok=True)
    vtfimg.gravar_cubo(faces_cubo(faces, lado), str(env / f"{nome}.vtf"))
    (env / f"{nome}.vmt").write_text(f'WindowImposter\n{{\n\t"$envmap"\t"envmaps/{nome}"\n}}\n')
    return env / f"{nome}.vtf"


def regiao_de(regs: list[dict], p) -> dict | None:
    for r in regs:
        mn, mx = r.get("mins"), r.get("maxs")
        if mn and mx and all(min(mn[i], mx[i]) <= p[i] <= max(mn[i], mx[i]) for i in range(3)):
            return r
    return None


def poligonos(bsp_path: Path, regioes: dict, grupos: set[str]) -> dict[str, list[list[float]]]:
    from srctools.bsp import BSP
    from srctools.const import SurfFlags
    ceu = SurfFlags.SKYBOX_2D | SurfFlags.SKYBOX_3D
    regs = regioes["regioes"]
    out: dict[str, list[list[float]]] = {}
    for f in BSP(str(bsp_path)).faces:
        if not f.texinfo or not f.texinfo.flags & ceu or len(f.edges) < 3:
            continue
        pts = [e.a for e in f.edges]
        c = sum(pts[1:], pts[0]) / len(pts)
        r = regiao_de(regs, c)
        sky = r and r.get("grupo") in grupos and (r.get("ceu") or {}).get("skyname")
        if not sky:
            continue
        n = f.plane.normal if f.same_dir_as_plane else -f.plane.normal   # normal visível: aponta para dentro do mapa
        out.setdefault(sky, []).append([round(v, 1) for p in pts for v in (p + n).as_tuple()])
    return out


def faces(bsp: Path, regioes_json: Path, grupos: set[str], embutir: bool) -> None:
    dados = json.loads(regioes_json.read_text())
    imp = poligonos(bsp, dados, grupos)
    for sky, pol in imp.items():
        print(f"{sky}: {len(pol)} faces, {sum(len(p) // 3 for p in pol)} vértices")
    dados["imposters"] = imp
    txt = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode()
    if embutir:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from hammertools.embutir import write_pak
        write_pak(bsp, {f"data_static/ht_regioes/{bsp.stem}.json": txt})
        print(f"{bsp}: data_static/ht_regioes/{bsp.stem}.json ({len(txt) // 1024} KB)")
    else:
        sys.stdout.buffer.write(txt)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "cubo":
        print(cubo(Path(a[1]), a[2], Path(a[3]), int(a[4]) if len(a) > 4 else 512))
    elif a and a[0] == "faces":
        faces(Path(a[1]), Path(a[2]), set(a[3].split(",")), "--embutir" in a)
    else:
        print(__doc__)
