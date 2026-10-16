"""Céu liso (nublado, entardecer...) por direção: gradiente por elevação do zênite ao horizonte e do horizonte ao
chão, com nuvens suaves opcionais (soma de ondas 3D na direção: contínuas entre as faces, sem caixa).

  python tools/ceu_gradiente.py <pasta skybox> <nome> "R G B zênite" "R G B horizonte" "R G B chão" [nuvens 0..1]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vtfimg  # noqa: E402
from skyline_pano import direcoes, suave  # noqa: E402


def cor(s: str) -> np.ndarray:
    return np.array([float(x) for x in s.split()], np.float32)


def main() -> None:
    a = sys.argv
    out, nome = Path(a[1]), a[2]
    zen, hor, chao = cor(a[3]), cor(a[4]), cor(a[5])
    nuvens = float(a[6]) if len(a) > 6 else 0.0
    rng = np.random.default_rng(7)
    ondas = [(rng.normal(size=3) * f, rng.uniform(0, 2 * np.pi), 1 / f) for f in (1.5, 2.5, 4.0, 7.0) for _ in range(3)]
    out.mkdir(parents=True, exist_ok=True)
    for lado in vtfimg.CUBO:
        d = direcoes(lado)
        d = d / np.linalg.norm(d, axis=-1, keepdims=True)
        el = np.degrees(np.arcsin(d[..., 2]))
        t = suave(el / 90)[..., None]                       # 0 no horizonte, 1 no zênite
        px = np.where(el[..., None] >= 0, hor * (1 - t) + zen * t,
                      hor * (1 - suave(-el / 12)[..., None]) + chao * suave(-el / 12)[..., None])
        if nuvens:
            n = sum(np.sin(d @ k + fase) * amp for k, fase, amp in ondas)
            n = n / sum(amp for _, _, amp in ondas)
            px = px * (1 + nuvens * 0.25 * n[..., None] * suave(el / 6)[..., None])   # nada abaixo do horizonte
        im = Image.fromarray(np.clip(px, 0, 255).astype(np.uint8))
        vtfimg.gravar(im.resize((512, 512), Image.LANCZOS), str(out / f"{nome}{lado}.vtf"))
        (out / f"{nome}{lado}.vmt").write_text(
            f'UnlitGeneric\n{{\n\t"$basetexture"\t"skybox/{nome}{lado}"\n\t"$ignorez" "1"\n\t"$nofog" 1\n}}\n')
    print(f"{out}: {nome}")


if __name__ == "__main__":
    main()
