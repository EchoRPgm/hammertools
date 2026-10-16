"""Skybox de cidade a partir de um panorama (foto): cada pixel das 6 faces sai da direção que ele representa.

- azimute -> coluna do panorama: a foto cobre `graus` da volta, centrada em `centro` (0 = +X, 90 = +Y); o resto da
  volta são as pontas da foto (colinas, pontes) espelhadas e fundidas no meio, sem emenda;
- elevação -> linha da foto em projeção cilíndrica (tan), com a linha `horizonte` da foto 1° acima do horizonte;
  `estica` > 1 sobe a skyline no céu (numa cidade cercada de prédios ela precisa aparecer por cima dos telhados);
- acima da foto, gradiente por elevação do céu da própria foto (coluna a coluna, fundido no topo dela) até o zênite;
  abaixo, a cor da base escurecendo até o nadir. A face de cima continua as laterais, sem caixa.

Direção de cada pixel como no R_DrawSkyBox do Source (st_to_vec/skytexorder, os mesmos do echorp_ceu): rt = +X,
bk = +Y, lf = -X, ft = -Y; a volta da esquerda para a direita é bk -> rt -> ft -> lf.

  python tools/skyline_pano.py <panorama.jpg> <pasta skybox> <nome> [horizonte base [graus estica centro [quente]]]
      horizonte/base: frações da altura da foto (linha do horizonte, pé da faixa usada); padrão 0.24 0.60 270 1.3 -45 0
      quente: 0..1, aquece a foto e o céu (mais vermelho, menos azul) para combinar com uma luz de sol quente
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vtfimg  # noqa: E402

N = 1024                 # lado da face
ELEV_HORIZONTE = 1.0     # graus: a linha do horizonte da foto fica um pouco acima da linha dos olhos
FUSAO_TOPO = 60          # linhas do topo da foto fundidas no gradiente do céu
FUSAO_BASE = 40          # linhas do pé da faixa fundidas na cor do chão


def direcoes(lado: str) -> np.ndarray:
    """(N, N, 3) direções dos pixels da face (u para a direita, v para baixo, centro do pixel)."""
    u, v = np.meshgrid((np.arange(N) + 0.5) / N, (np.arange(N) + 0.5) / N)
    s, t = 2 * u - 1, 1 - 2 * v
    um = np.ones_like(s)
    return np.stack({
        "rt": (um, -s, t), "lf": (-um, s, t), "bk": (s, um, t), "ft": (-s, -um, t),
        "up": (-t, -s, um), "dn": (t, -s, -um),
    }[lado], axis=-1)


def volta_completa(foto: np.ndarray, graus: float) -> np.ndarray:
    """Foto + pontas espelhadas fundidas até fechar 360° (largura = 360 / graus da foto)."""
    h, w, _ = foto.shape
    total = round(w * 360 / graus)
    rw = total - w
    if rw <= 0:
        return foto
    m = min(400, rw // 2)
    larg = rw // 2 + m // 2
    q = min(w // 6, 640)

    def ponta(bloco: np.ndarray) -> np.ndarray:
        im = Image.fromarray(bloco.astype(np.uint8)).transpose(Image.FLIP_LEFT_RIGHT).resize((larg, h), Image.LANCZOS)
        return np.asarray(im).astype(np.float32)

    dir_, esq = ponta(foto[:, w - q:]), ponta(foto[:, :q])
    resto = np.zeros((h, rw, 3), np.float32)
    resto[:, :larg] = dir_
    resto[:, rw - larg:] = esq
    a = np.linspace(0, 1, m, dtype=np.float32)[None, :, None]
    resto[:, rw - larg:rw - larg + m] = dir_[:, larg - m:] * (1 - a) + esq[:, :m] * a
    return np.concatenate([foto, resto], axis=1)


def amostrar(img: np.ndarray, col: np.ndarray, lin: np.ndarray) -> np.ndarray:
    """Bilinear; colunas dão a volta, linhas presas na faixa."""
    h, w, _ = img.shape
    lin = np.clip(lin, 0, h - 1)
    c0, l0 = np.floor(col).astype(int), np.floor(lin).astype(int)
    fc, fl = (col - c0)[..., None], (lin - l0)[..., None]
    c0, c1 = c0 % w, (c0 + 1) % w
    l1 = np.minimum(l0 + 1, h - 1)
    return (img[l0, c0] * (1 - fc) + img[l0, c1] * fc) * (1 - fl) + (img[l1, c0] * (1 - fc) + img[l1, c1] * fc) * fl


def suave(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def main() -> None:
    a = sys.argv
    src, out, nome = Path(a[1]), Path(a[2]), a[3]
    horizonte, base = (float(a[4]), float(a[5])) if len(a) > 5 else (0.24, 0.60)
    graus = float(a[6]) if len(a) > 6 else 270.0
    estica = float(a[7]) if len(a) > 7 else 1.3
    centro = float(a[8]) if len(a) > 8 else -45.0
    quente = float(a[9]) if len(a) > 9 else 0.0

    pano = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    pano = pano * np.array([1 + 0.07 * quente, 1 + 0.01 * quente, 1 - 0.12 * quente], np.float32)
    H, W, _ = pano.shape
    faixa = volta_completa(pano[: int(H * base)], graus)
    hb, wt, _ = faixa.shape
    lin_h = H * horizonte
    px_grau = W / graus                               # px da foto por grau de azimute
    f = px_grau / estica * 180 / np.pi                # px por radiano na vertical (cilíndrica)

    # cores de borda por coluna (suavizadas): topo da foto (céu) e pé da faixa (chão)
    def borda(linhas: np.ndarray, k: int) -> np.ndarray:
        c = linhas.mean(axis=0)
        pad = np.concatenate([c[-k:], c, c[:k]])
        ker = np.ones(k) / k
        return np.stack([np.convolve(pad[:, i], ker, "same")[k:-k] for i in range(3)], axis=-1)

    ceu_col = borda(faixa[:8], 81)
    chao_col = borda(faixa[-8:], 801)         # chão quase liso: sem raios coloridos na face de baixo
    zenite = ceu_col.mean(axis=0) * np.array([0.78, 0.85, 0.95])
    nadir = chao_col.mean(axis=0) * 0.6
    tan_h = np.tan(np.radians(ELEV_HORIZONTE))
    el_topo = np.degrees(np.arctan((lin_h - 0) / f + tan_h))          # elevação do topo da foto
    el_pe = np.degrees(np.arctan((lin_h - (hb - 1)) / f + tan_h))     # elevação do pé da faixa

    faces = {}
    for lado in vtfimg.CUBO:
        d = direcoes(lado)
        az = np.degrees(np.arctan2(d[..., 1], d[..., 0]))
        el = np.degrees(np.arctan2(d[..., 2], np.hypot(d[..., 0], d[..., 1])))
        col = ((centro + graus / 2 - az) % 360) * wt / 360           # azimute cai para a direita
        lin = lin_h - f * (np.tan(np.radians(np.clip(el, -89, 89))) - tan_h)
        foto = amostrar(faixa, col, lin)
        ci = np.clip(col.astype(int), 0, wt - 1)
        # céu acima da foto: do céu da coluna até o zênite; chão abaixo: da cor do pé até o nadir
        t_ceu = suave((el - el_topo) / (90 - el_topo))[..., None]
        ceu = ceu_col[ci] * (1 - t_ceu) + zenite * t_ceu
        t_chao = suave((el_pe - el) / 15)[..., None]
        chao = chao_col[ci] * (1 - t_chao) + nadir * t_chao
        a_ceu = suave(1 - lin / FUSAO_TOPO)[..., None]                 # 1 acima do topo, 0 depois da fusão
        a_chao = suave((lin - (hb - 1 - FUSAO_BASE)) / FUSAO_BASE)[..., None]
        px = foto * (1 - a_ceu) + ceu * a_ceu
        px = px * (1 - a_chao) + chao * a_chao
        faces[lado] = Image.fromarray(np.clip(px, 0, 255).astype(np.uint8))

    out.mkdir(parents=True, exist_ok=True)
    for lado, im in faces.items():
        vtfimg.gravar(im, str(out / f"{nome}{lado}.vtf"))
        (out / f"{nome}{lado}.vmt").write_text(
            f'UnlitGeneric\n{{\n\t"$basetexture"\t"skybox/{nome}{lado}"\n\t"$ignorez" "1"\n\t"$nofog" 1\n}}\n')
    # prévia: a volta na ordem contínua bk rt ft lf; embaixo up e dn como estão no VTF
    prev = Image.new("RGB", (4 * 256, 2 * 256))
    for i, lado in enumerate(("bk", "rt", "ft", "lf", "up", "dn")):
        prev.paste(faces[lado].resize((256, 256)), ((i % 4) * 256, (i // 4) * 256))
    prev.save(out.parent.parent / f"_preview_{nome}.jpg")
    print(f"{out}: {nome} (foto {el_pe:.1f}° a {el_topo:.1f}°, faixa {hb}x{wt})")


if __name__ == "__main__":
    main()
