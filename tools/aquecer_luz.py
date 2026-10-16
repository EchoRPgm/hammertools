"""Paleta de luz quente num VMF: lâmpadas quase brancas (light, light_spot, light_dynamic) viram uma cor quente com a
mesma intensidade; luzes coloridas (neon, sirene) ficam como estão. Opcional: cor/intensidade do sol e do céu do
light_environment e a cor da neblina do env_fog_controller.

  python tools/aquecer_luz.py <in.vmf> <out.vmf> [--lampada R G B] [--sol R G B I] [--ceu R G B I]
                              [--neblina R G B] [--saturacao 0.2]

"Quase branca": (max - min) / max abaixo de --saturacao (255 255 230 e 247 255 217 entram; 255 128 64 não).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

LAMPADAS = ("light", "light_spot", "light_dynamic")


def quase_branca(rgb: list[float], sat: float) -> bool:
    return max(rgb) > 0 and (max(rgb) - min(rgb)) / max(rgb) < sat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada", type=Path)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--lampada", nargs=3, type=int)
    ap.add_argument("--sol", nargs=4, type=int)
    ap.add_argument("--ceu", nargs=4, type=int)
    ap.add_argument("--neblina", nargs=3, type=int)
    ap.add_argument("--saturacao", type=float, default=0.2)
    a = ap.parse_args()
    with open(a.entrada, encoding="utf-8", errors="surrogateescape", newline="") as f:   # mantém CRLF do Hammer
        txt = f.read()
    cont = {"lampadas": 0, "coloridas": 0}

    def entidade(m: re.Match) -> str:
        b = m.group(0)
        cl = re.search(r'"classname" "([^"]+)"', b)
        cl = cl.group(1) if cl else ""

        def troca(chave: str, valor: str, bloco: str) -> str:
            return re.sub(rf'("{chave}" ")[^"]*(")', lambda k: k.group(1) + valor + k.group(2), bloco, count=1)

        if cl in LAMPADAS and a.lampada:
            for chave in ("_light", "_lightHDR"):
                v = re.search(rf'"{chave}" "([^"]+)"', b)
                if not v:
                    continue
                p = v.group(1).split()
                if len(p) < 3 or p[0] == "-1":
                    continue
                if quase_branca([float(x) for x in p[:3]], a.saturacao):
                    b = troca(chave, " ".join(map(str, a.lampada)) + "".join(" " + x for x in p[3:]), b)
                    cont["lampadas"] += chave == "_light"
                else:
                    cont["coloridas"] += chave == "_light"
        elif cl == "light_environment":
            if a.sol:
                b = troca("_light", " ".join(map(str, a.sol)), b)
            if a.ceu:
                b = troca("_ambient", " ".join(map(str, a.ceu)), b)
        elif cl == "env_fog_controller" and a.neblina:
            b = troca("fogcolor", " ".join(map(str, a.neblina)), b)
        return b

    # entidade de nível 0 (sem blocos aninhados além de editor/connections, que não têm "classname")
    novo = re.sub(r'^entity\r?\n\{.*?^\}', entidade, txt, flags=re.S | re.M)
    with open(a.saida, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(novo)
    print(f"{a.saida}: {cont['lampadas']} lâmpadas aquecidas, {cont['coloridas']} coloridas mantidas")


if __name__ == "__main__":
    main()
