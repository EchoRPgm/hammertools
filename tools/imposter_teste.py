"""Teste do "window imposter" (shader WindowImposter + cubemap): uma sala vista pelo céu de verdade e outra pelo
imposter, com um céu de coordenadas (R = u, G = v, B = face * 50) para medir a orientação de cada face do cubemap.

  python tools/imposter_teste.py <addon de teste>      # materiais em <addon>/materials, VMF em maps/
  python tools/imposter_teste.py --medir <ceu.tga> <imposter.tga> [...]   # pares de capturas da mesma pose

Sala A em x = 0 (toolsskybox, skyname ht_coord); sala B em x = 2048 (envmaps/ht_coord). O WindowImposter amostra o
cubemap na direção olho -> superfície, então de qualquer ponto a sala B deve ser igual ao céu.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vtfimg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
N = 256
NOME = "ht_coord"
IMPOSTER = f"envmaps/{NOME}"


def face_coord(i: int) -> Image.Image:
    im = Image.new("RGB", (N, N))
    im.putdata([(x, y, i * 50) for y in range(N) for x in range(N)])
    return im


def materiais(addon: Path) -> None:
    sky = addon / "materials" / "skybox"
    env = addon / "materials" / "envmaps"
    sky.mkdir(parents=True, exist_ok=True)
    env.mkdir(parents=True, exist_ok=True)
    faces = {lado: face_coord(i) for i, lado in enumerate(vtfimg.CUBO)}
    for lado, im in faces.items():
        vtfimg.gravar(im, str(sky / f"{NOME}{lado}.vtf"), flags=0x000C | 0x0200)
        (sky / f"{NOME}{lado}.vmt").write_text(
            f'UnlitGeneric\n{{\n\t"$basetexture"\t"skybox/{NOME}{lado}"\n\t"$nofog" 1\n\t"$ignorez" 1\n}}\n')
    vtfimg.gravar_cubo(faces, str(env / f"{NOME}.vtf"))
    (env / f"{NOME}.vmt").write_text(f'WindowImposter\n{{\n\t"$envmap"\t"envmaps/{NOME}"\n}}\n')


def vmf() -> Path:
    from srctools import VMF, Vec
    from hammertools.core import vmf as vmfio
    v = VMF()
    v.spawn["skyname"] = NOME
    t, r = 64, 256
    for cx, mat in ((0, "tools/toolsskybox"), (2048, IMPOSTER)):
        c = Vec(cx, 0, 0)
        for lo, hi in (((-r - t, -r - t, -r - t), (r + t, r + t, -r)), ((-r - t, -r - t, r), (r + t, r + t, r + t)),
                       ((-r - t, -r - t, -r), (-r, r + t, r)), ((r, -r - t, -r), (r + t, r + t, r)),
                       ((-r, -r - t, -r), (r, -r, r)), ((-r, r, -r), (r, r + t, r))):
            v.add_brush(v.make_prism(c + Vec(*lo), c + Vec(*hi), mat).solid)
    v.create_ent("info_player_start", origin="0 0 -240", angles="0 0 0")
    v.create_ent("info_target", targetname="sala_b", origin="2048 0 0")   # sem entidade dentro o vbsp enche a sala B
    out = ROOT / "maps" / "ht_imposter_teste.vmf"
    vmfio.save(v, out)
    return out


def ler(px) -> tuple[int, int, int] | None:
    r, g, b = px[:3]
    f = round(b / 50)
    if abs(b - f * 50) > 8 or not 0 <= f < 6 or min(r, g) < 8 or max(r, g) > 247:
        return None            # costura entre faces ou borda (filtragem mistura texels)
    return f, r, g


TRANSF = {   # (u, v) da face do céu a partir do (u, v) amostrado no cubemap
    "id": lambda u, v: (u, v), "rot90": lambda u, v: (N - 1 - v, u), "rot180": lambda u, v: (N - 1 - u, N - 1 - v),
    "rot270": lambda u, v: (v, N - 1 - u), "flipx": lambda u, v: (N - 1 - u, v), "flipy": lambda u, v: (u, N - 1 - v),
    "transp": lambda u, v: (v, u), "antitransp": lambda u, v: (N - 1 - v, N - 1 - u),
}


def medir(pares: list[tuple[str, str]]) -> None:
    corr = defaultdict(list)        # face amostrada no cubemap -> [(face do céu, u, v, ub, vb)]
    for a, b in pares:
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        w, h = ia.size
        for y in range(4, h - 4, 3):
            for x in range(4, w - 4, 3):
                pa, pb = ler(ia.getpixel((x, y))), ler(ib.getpixel((x, y)))
                if pa and pb:
                    corr[pb[0]].append((pa[0], pa[1], pa[2], pb[1], pb[2]))
    for fb in sorted(corr):
        lst = corr[fb]
        fa, n = Counter(c[0] for c in lst).most_common(1)[0]
        sel = [c for c in lst if c[0] == fa]
        erros = {k: sum(abs(t(c[3], c[4])[0] - c[1]) + abs(t(c[3], c[4])[1] - c[2]) for c in sel) / len(sel)
                 for k, t in TRANSF.items()}
        k = min(erros, key=erros.get)
        print(f"cubemap {vtfimg.CUBO[fb]} -> céu {vtfimg.CUBO[fa]} ({n}/{len(lst)} px), {k} (erro {erros[k]:.1f} px)")


if __name__ == "__main__":
    if sys.argv[1] == "--medir":
        medir(list(zip(sys.argv[2::2], sys.argv[3::2])))
    else:
        materiais(Path(sys.argv[1]))
        print(vmf())
