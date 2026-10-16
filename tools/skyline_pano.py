"""Skybox de cidade a partir de um panorama (foto) ~180°: a faixa da skyline vai para o horizonte das faces laterais.

- a faixa [topo, base] do panorama (prédios até a beira do rio) é escalada para 2 faces (180°) e posta com a base um
  pouco abaixo do horizonte;
- as outras 2 faces são as bordas do panorama (colinas baixas) espelhadas e fundidas no meio: a volta fecha sem emenda;
- acima da faixa, gradiente do céu com a cor do topo da foto (fundida na faixa); abaixo, a cor da base continua até o
  pé da face; up e dn em cor lisa.

  python tools/skyline_pano.py <panorama.jpg> <pasta skybox> <nome> [topo base [faces_pano estica]]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vtfimg  # noqa: E402

N = 1024                 # lado da face
HOR = N // 2             # horizonte (direção horizontal) no meio da face


def media(im: Image.Image, box) -> tuple[int, int, int]:
    return tuple(int(v) for v in ImageStat.Stat(im.crop(box)).mean[:3])


def gradiente(w: int, h: int, cima, baixo) -> Image.Image:
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(cima[i] + (baixo[i] - cima[i]) * t) for i in range(3)))
    return g.resize((w, h))


def main() -> None:
    src, out, nome = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    topo, base = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (0.06, 0.50)
    # faces cobertas pelo panorama (o resto são as pontas espelhadas) e esticamento vertical: numa cidade cercada de
    # prédios a skyline precisa subir mais no céu para aparecer por cima dos telhados
    faces_pano = int(sys.argv[6]) if len(sys.argv) > 6 else 3
    estica = float(sys.argv[7]) if len(sys.argv) > 7 else 1.3
    pano = Image.open(src).convert("RGB")
    W, H = pano.size
    faixa = pano.crop((0, int(H * topo), W, int(H * base)))
    fw = faces_pano * N
    fh = round(faixa.height * fw / faixa.width * estica)
    faixa = faixa.resize((fw, fh), Image.LANCZOS)
    # resto da volta: só as pontas do panorama (colinas, pontes), espelhadas e esticadas; a direita do panorama
    # continua na face seguinte e a esquerda fecha a volta, sem emenda
    q = fw // (5 * faces_pano // 2)
    m = 900                       # largura da fusão entre as duas pontas (o céu da foto muda de tom de uma ponta à outra)
    rw = (4 - faces_pano) * N       # largura do resto da volta
    m = min(m, rw // 2)
    larg = rw // 2 + m // 2         # cada ponta cobre metade do resto + meia fusão
    dir_ = faixa.crop((fw - q, 0, fw, fh)).transpose(Image.FLIP_LEFT_RIGHT).resize((larg, fh), Image.LANCZOS)
    esq = faixa.crop((0, 0, q, fh)).transpose(Image.FLIP_LEFT_RIGHT).resize((larg, fh), Image.LANCZOS)
    resto = Image.new("RGB", (rw, fh))
    resto.paste(dir_, (0, 0))
    resto.paste(esq, (rw - larg, 0))
    mask = Image.linear_gradient("L").rotate(90, expand=True).resize((m, fh))   # horizontal: 0 à esquerda, 255 à direita
    a_ = dir_.crop((larg - m, 0, larg, fh))
    b_ = esq.crop((0, 0, m, fh))
    resto.paste(Image.composite(b_, a_, mask), (rw - larg, 0))
    faixa_toda = Image.new("RGB", (4 * N, fh))
    faixa_toda.paste(faixa, (0, 0))
    faixa_toda.paste(resto, (fw, 0))

    ceu_topo = media(pano, (0, 0, W, max(2, int(H * 0.02))))
    ceu_hor = media(faixa_toda, (0, 0, 4 * N, 6))
    chao = media(faixa_toda, (0, fh - 6, 4 * N, fh))
    tira = Image.new("RGB", (4 * N, N))
    y0 = HOR + 24 - fh            # base da faixa 24 px abaixo do horizonte
    tira.paste(gradiente(4 * N, y0 + fh, tuple(int(c * 0.85) for c in ceu_topo), ceu_hor), (0, 0))   # até a base: a fusão do topo da faixa mostra o céu, não o fundo
    tira.paste(gradiente(4 * N, N - (y0 + fh) + 8, chao, tuple(int(c * 0.8) for c in chao)), (0, y0 + fh - 8))
    # faixa por cima, com borda superior suave (céu da foto fundido no gradiente)
    mask = Image.new("L", (4 * N, fh), 255)
    mask.paste(gradiente(4 * N, 24, (0, 0, 0), (255, 255, 255)).convert("L"), (0, 0))
    tira.paste(faixa_toda, (0, y0), mask)
    out.mkdir(parents=True, exist_ok=True)
    faces = {lado: tira.crop((i * N, 0, (i + 1) * N, N)) for i, lado in enumerate(["ft", "rt", "bk", "lf"])}
    faces["up"] = Image.new("RGB", (N, N), tuple(int(c * 0.85) for c in ceu_topo))
    faces["dn"] = Image.new("RGB", (N, N), tuple(int(c * 0.8) for c in chao))
    for lado, im in faces.items():
        vtfimg.gravar(im, str(out / f"{nome}{lado}.vtf"))
        (out / f"{nome}{lado}.vmt").write_text(
            f'UnlitGeneric\n{{\n\t"$basetexture"\t"skybox/{nome}{lado}"\n\t"$ignorez" "1"\n\t"$nofog" 1\n}}\n')
    tira.resize((2048, 512)).save(out.parent.parent / f"_preview_{nome}.jpg")
    print(f"{out}: {nome} (faixa {fh}px, céu {ceu_topo}, chão {chao})")


if __name__ == "__main__":
    main()
