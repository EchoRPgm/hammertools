"""`ht content`: monta a pasta de conteúdo de um mapa, automaticamente.

1. Lê o VMF e resolve dependências: materiais das faces/overlays/decals, texturas citadas em cada .vmt
   (inclusive patch -> include), modelos (.mdl + .vvd/.vtx/.phy/.ani + materiais do modelo), skybox e sons
   de ambient_generic.
2. Procura cada arquivo, nesta ordem: o que o JOGO já enxerga (VPKs, jogos montados, addons) -> nada a
   copiar; fontes extras (BSPs com pakfile, pastas, GMAs) -> copia; senão -> faltando.
3. Grava a pasta (padrão: garrysmod/addons/<mapa>_content), que o GMod monta sozinho (gameinfo: addons/*).

Fontes automáticas: BSPs de mapa dentro de addons .gma cujo nome bate com o do VMF (ex.: rp_surdonoso_w ->
maps/rp_surdonoso.bsp): o conteúdo embutido num BSP só é montado quando aquele mapa está carregado.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from srctools import VMF

TEX_KEYS = re.compile(r'"?(\$[a-z0-9_]+)"?\s+"?([^"\s{}]+)"?', re.I)
VTF_PARAMS = {  # parâmetros de .vmt que apontam pra textura (.vtf)
    "$basetexture", "$basetexture2", "$basetexture3", "$basetexture4", "$bumpmap", "$bumpmap2", "$detail", "$detail2",
    "$envmapmask", "$normalmap", "$normalmap2", "$dudvmap", "$blendmodulatetexture", "$selfillummask", "$phongexponenttexture",
    "$lightwarptexture", "$iris", "$corneatexture", "$ambientoccltexture", "$tintmasktexture", "$refracttexture",
    "$reflecttexture", "$texture2", "$flowmap", "$flow_noise_texture", "$fallbackmaterial", "$bottommaterial", "$underwateroverlay",
    "$selfillumtexture", "$emissiveblendtexture", "$emissiveblendbasetexture", "$emissiveblendflowtexture", "$hdrbasetexture",
    "$hdrcompressedtexture", "$hdrcompressedtexture0", "$hdrcompressedtexture1", "$hdrcompressedtexture2", "$envmap",
}
VMT_PARAMS = {"$fallbackmaterial", "$bottommaterial", "$underwateroverlay"}  # apontam pra outro .vmt
# o GMod só lê o .dx90.vtx (o .dx80.vtx e o .sw.vtx ficam no disco à toa)
MODEL_EXTS = (".mdl", ".vvd", ".dx90.vtx", ".phy", ".ani")
SKY_SUFFIXES = ("up", "dn", "lf", "rt", "ft", "bk")


def norm(p: str) -> str:
    return p.replace("\\", "/").lower().lstrip("/")


def mat_name(p: str) -> str:
    """Nome de material como o motor procura: materials/<nome>.vmt, com o nome como o mapa escreve. Um nome que já
    começa com "materials/" vira materials/materials/... de verdade (o motor não tira o prefixo; os arquivos desses
    materiais existem nesse caminho duplo)."""
    return re.sub(r"\.vmt$", "", norm(p))


# --------------------------------------------------------------------------- fontes
@dataclass
class Source:
    name: str
    has: Callable[[str], bool]
    read: Callable[[str], bytes]


def source_bsp(path: Path, label: str | None = None) -> Source:
    from srctools.bsp import BSP
    pak = BSP(str(path)).pakfile
    names = {norm(n): n for n in pak.namelist()}
    return Source(label or f"BSP {path.name}", lambda p: norm(p) in names, lambda p: pak.read(names[norm(p)]))


def source_bsp_bytes(data: bytes, label: str) -> Source:
    import io
    import zipfile
    # o pakfile é um zip no lump 40; o BSP inteiro serve pro zipfile (ele acha o diretório central no fim do lump)
    from srctools.bsp import BSP, BSP_LUMPS
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".bsp", delete=False) as t:
        t.write(data)
        tmp = t.name
    try:
        lump = BSP(tmp).get_lump(BSP_LUMPS.PAKFILE)
    finally:
        Path(tmp).unlink(missing_ok=True)
    z = zipfile.ZipFile(io.BytesIO(lump))
    names = {norm(n): n for n in z.namelist()}
    return Source(label, lambda p: norm(p) in names, lambda p: z.read(names[norm(p)]))


def source_dir(path: Path) -> Source:
    root = Path(path)
    index: dict[str, Path] = {}
    for f in root.rglob("*"):
        if f.is_file():
            index.setdefault(norm(f.relative_to(root).as_posix()), f)
    return Source(f"pasta {root}", lambda p: norm(p) in index, lambda p: index[norm(p)].read_bytes())


def source_subdir(root: Path, rel: str) -> Source:
    """Só uma subpasta do jogo (ex.: models/ht_prop/<mapa>), com caminhos relativos à raiz do jogo."""
    base = Path(root) / rel
    index: dict[str, Path] = {}
    for f in base.rglob("*"):
        if f.is_file():
            index.setdefault(norm(f.relative_to(root).as_posix()), f)
    return Source(f"pasta {base}", lambda p: norm(p) in index, lambda p: index[norm(p)].read_bytes())


def source_gma(path: Path) -> Source:
    from hammertools.core.gma import GMA
    g = GMA(path)
    return Source(f"GMA {path.name}", lambda p: norm(p) in g.files, lambda p: g.read(norm(p)))


def map_bsps_in_addons(gmas: Iterable[Path], map_stem: str, all_maps: bool = False) -> list[Source]:
    """BSPs de mapa dentro de GMAs: os que batem com o nome do VMF (prefixo comum), ou todos com all_maps."""
    from hammertools.core.gma import GMA
    stem = map_stem.lower()
    out = []
    for gp in gmas:
        try:
            g = GMA(gp)
        except (OSError, ValueError, struct.error):
            continue
        for name in g.files:
            if not (name.startswith("maps/") and name.endswith(".bsp")):
                continue
            bsp = Path(name).stem
            if all_maps or stem.startswith(bsp) or bsp.startswith(stem):
                out.append(source_bsp_bytes(g.read(name), f"{name} (dentro de {gp.parent.name}/{gp.name})"))
    return out


# --------------------------------------------------------------------------- dependências
def vmf_roots(v: VMF) -> tuple[set[str], set[str], set[str]]:
    """(materiais sem extensão, modelos .mdl, sons) citados pelo mapa."""
    mats, models, sounds = set(), set(), set()
    for s in v.brushes:
        for side in s.sides:
            mats.add(mat_name(side.mat))
    for e in v.entities:
        for s in e.solids:
            for side in s.sides:
                mats.add(mat_name(side.mat))
        cls = e["classname"]
        # chaves de entidade que apontam para material: overlay ("material"), decal ("texture"), corda
        # ("ropematerial"), textura projetada ("texturename"), e o "material" genérico de várias entidades
        for key in ("material", "texture", "ropematerial"):
            val = e.get(key, "")
            # algumas entidades usam "material"/"texture" para números (tipo de material de quebra etc.)
            if val and not re.fullmatch(r"[-\d.\s]+", val) and not val.lower().endswith((".mdl", ".wav", ".mp3")):
                mats.add(mat_name(val))
        if e.get("texturename"):
            mats.add(mat_name(e["texturename"]))
        if cls == "env_sprite" and e.get("model", "").lower().endswith((".vmt", ".spr")):
            mats.add(norm(re.sub(r"^materials/", "", e["model"], flags=re.I).rsplit(".", 1)[0]))
        for k, val in e.items():
            if isinstance(val, str) and val.lower().endswith(".mdl") and not val.startswith("*"):
                models.add(norm(val))
        if cls == "ambient_generic" and re.search(r"\.(wav|mp3|ogg)$", e.get("message", ""), re.I):
            sounds.add("sound/" + norm(e["message"].lstrip("*#@<>^)(}$!?")))
    if v.spawn.get("detailmaterial"):
        mats.add(mat_name(v.spawn["detailmaterial"]))
    sky = v.spawn.get("skyname", "")
    if sky:
        for suf in SKY_SUFFIXES:
            mats.add(f"skybox/{sky.lower()}{suf}")
    mats.discard("")
    return mats, models, sounds


def vmt_deps(text: str) -> tuple[set[str], set[str]]:
    """(texturas .vtf sem extensão, outros .vmt sem extensão) citados num .vmt."""
    vtfs, vmts = set(), set()
    low = text.lower()
    m = re.search(r'"?include"?\s+"([^"]+)"', low)  # patch
    if m:
        vmts.add(norm(re.sub(r"^materials/", "", m.group(1)).rsplit(".vmt", 1)[0]))
    for key, val in TEX_KEYS.findall(low):
        key = key.lower()
        val = norm(val)
        if key == "$envmap" and val in ("env_cubemap", ""):
            continue
        if key in VMT_PARAMS:
            vmts.add(re.sub(r"\.vmt$", "", val))
        elif key in VTF_PARAMS and not re.fullmatch(r"[\d.\-\s\[\]]+", val):
            vtfs.add(re.sub(r"\.vtf$", "", re.sub(r"^materials/", "", val)))
    return vtfs, vmts


def mdl_extra_models(data: bytes) -> list[str]:
    """Modelos que um .mdl puxa: gibs de prop quebrável (keyvalues "break" { "model" ... }) e $includemodels."""
    if len(data) < 344 or data[:4] != b"IDST":
        return []
    rd = lambda o: struct.unpack_from("<i", data, o)[0]
    out = []
    kv_i, kv_n = rd(312), rd(316)
    if 0 < kv_i < len(data) and 0 < kv_n <= len(data) - kv_i:
        text = data[kv_i:kv_i + kv_n].decode("latin-1", "replace")
        out += [norm(m) for m in re.findall(r'"model"\s+"([^"]+\.mdl)"', text, re.I)]
    n_inc, inc_i = rd(336), rd(340)
    for k in range(max(0, min(n_inc, 64))):
        base = inc_i + 8 * k
        if base + 8 > len(data):
            break
        off = base + rd(base + 4)
        end = data.find(b"\0", off)
        if 0 <= off < len(data) and end > off:
            name = norm(data[off:end].decode("latin-1"))
            out.append(name if name.startswith("models/") else "models/" + name)
    return out


def mdl_textures(data: bytes) -> list[str]:
    """Materiais usados por um .mdl (cdmaterials x nomes de textura), lendo o studiohdr_t direto."""
    if len(data) < 220 or data[:4] != b"IDST":
        return []
    rd = lambda o: struct.unpack_from("<i", data, o)[0]
    ntex, tex_i, ncd, cd_i = rd(204), rd(208), rd(212), rd(216)

    def cstr(off):
        end = data.find(b"\0", off)
        return data[off:end].decode("latin-1") if 0 <= off < len(data) and end > off else ""

    names = [cstr(tex_i + 64 * k + rd(tex_i + 64 * k)) for k in range(max(0, min(ntex, 512)))]
    cds = [cstr(rd(cd_i + 4 * k)) for k in range(max(0, min(ncd, 64)))]
    out = []
    for n in names:
        for cd in cds or [""]:
            out.append(norm((cd + "/" if cd and not cd.endswith(("/", "\\")) else cd) + n))
    return out


@dataclass
class Result:
    copy: dict[str, str] = field(default_factory=dict)      # arquivo -> nome da fonte
    in_game: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)          # raiz (material/modelo/som) que não achou
    roots: int = 0


def resolve(v: VMF, game_has: Callable[[str], bool], game_read: Callable[[str], bytes | None], sources: list[Source]) -> Result:
    """Resolve a árvore de dependências. Arquivo que o jogo tem: não copia (mas segue as dependências dele)."""
    res = Result()
    mats, models, sounds = vmf_roots(v)
    res.roots = len(mats) + len(models) + len(sounds)

    def find(path: str) -> tuple[str, bytes | None] | None:
        if game_has(path):
            return ("jogo", None)
        for s in sources:
            if s.has(path):
                return (s.name, s.read(path))
        return None

    seen: set[str] = set()

    def take(path: str, required: bool, root: str) -> bytes | None:
        if path in seen:
            return None
        seen.add(path)
        hit = find(path)
        if hit is None:
            if required:
                res.missing.add(root)
            return None
        where, data = hit
        if where == "jogo":
            res.in_game.add(path)
            return game_read(path)
        res.copy[path] = where
        return data

    def material(m: str, root: str):
        m = mat_name(m)
        data = take(f"materials/{m}.vmt", True, root)
        if data is None:
            return
        vtfs, vmts = vmt_deps(data.decode("utf-8", "replace"))
        for t in vtfs:
            take(f"materials/{t}.vtf", False, root)
        for other in vmts:
            material(other, root)

    for m in sorted(mats):
        material(m, m)
    queue = sorted(models)
    while queue:
        mdl = queue.pop(0)
        if mdl in seen:
            continue
        from_game = game_has(mdl)
        data = take(mdl, True, mdl)
        base = mdl[:-4]
        # .mdl do jogo: os irmãos também são os do jogo. Copiar .vtx/.phy de uma fonte junto do .mdl de outra
        # versão dá "Error Vertex File ... checksum" no jogo
        if not from_game:
            for ext in MODEL_EXTS[1:]:
                take(base + ext, False, mdl)
        if data:
            for mt in mdl_textures(data):
                if not any(game_has(f"materials/{mt}.vmt") or s.has(f"materials/{mt}.vmt") for s in sources):
                    continue  # cdmaterials testa várias pastas; só a que existe vale
                material(mt, mdl)
            queue += [m for m in mdl_extra_models(data) if m not in seen]
    for snd in sorted(sounds):
        take(snd, True, snd)
    res.copy = {k: v for k, v in res.copy.items()}
    return res


def write(res: Result, sources: list[Source], out: Path, title: str) -> int:
    by_name = {s.name: s for s in sources}
    n = 0
    for path, src in sorted(res.copy.items()):
        dst = out / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(by_name[src].read(path))
        n += 1
    out.mkdir(parents=True, exist_ok=True)      # nada a copiar com --clean: a pasta não foi recriada
    (out / "addon.json").write_text('{"title": "%s", "type": "map", "tags": ["build"], "ignore": []}\n' % title.replace('"', ""))
    return n
