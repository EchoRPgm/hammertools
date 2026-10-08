"""Cache do vvis e do vrad por conteúdo do BSP que o vbsp gerou (o `ht compile` usa).

O vvis e o vrad são funções do BSP que entra (mais as opções e o próprio programa). Se o BSP de agora é igual ao de
uma compilação anterior no que eles leem, o resultado deles também é: em vez de rodar de novo, o resultado guardado
volta para o BSP novo.

- **vis**: chave = lumps de geometria (tudo menos ENTITIES, GAME_LUMP e PAKFILE) + .prt + o `farz` dos
  env_fog_controller (o único dado de entidade que o vvis lê, vide `-radius_override`) + opções e executável do vvis.
  Guarda os lumps que o vvis mudou (VISIBILITY, LEAFS, LEAFMINDISTTOWATER, LEAF_AMBIENT_*), medidos na hora (diferença
  antes/depois), e devolve-os por cima do BSP novo. Game lump e pakfile o vvis só regrava (mesmo conteúdo).
- **rad**: chave = chave do vis + game lumps (props estáticos e de detalhe) + conteúdo do pakfile (nome, CRC, tamanho;
  materiais e modelos gerados) + as entidades que o vrad lê (luzes, com a posição na lista; worldspawn; sky_camera;
  entidades de brush; alvos das luzes; qualquer entidade com chave de compilação `_...`) + opções e executável do vrad.
  Guarda o BSP final inteiro; na volta só troca ENTITIES (e a revisão do mapa) pelos do BSP novo — o resto é, por
  construção da chave, o mesmo que entraria no vrad.

Quando muda: qualquer brush (mundo, detail, entidade de brush), prop_static, overlay, cubemap, material embutido,
luz ou opção = chave nova = vvis/vrad rodam. Mudou só entidade que nenhum dos dois lê (prop_physics, spawn, lógica,
trigger de ponto...) = os dois são pulados. Mudou luz ou prop_static = só o vvis é pulado.

O vbsp do GMod não é determinístico em bytes que ninguém lê (lixo de memória): vizinhos inexistentes (0xFFFF) dos
displacements, o byte 31 de cada prop estático (sem uso no formato v10 do GMod; as flags ficam no int do fim) e o resto
dos nomes dos modelos de detail depois do \\0. Eles são zerados só para a chave; o BSP gravado não muda.

Fora da chave (limitação): arquivos do jogo/addons que o vrad lê pelo sistema de arquivos (refletividade de textura
fora do pakfile, lights.rad, modelos de prop que não são do auto-prop). Editou um desses? `--no-cache`/HT_NO_CACHE=1.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

from srctools.bsp import BSP, BSP_LUMPS

FORMAT = 1                  # sobe quando a chave ou o formato do cache muda (invalida tudo)
KEEP = 2                    # entradas guardadas por tipo (o BSP final do rad tem o tamanho do mapa)

NOT_GEOMETRY = {BSP_LUMPS.ENTITIES, BSP_LUMPS.GAME_LUMP, BSP_LUMPS.PAKFILE}
# o vvis regrava esses dois sem mudar o conteúdo (o game lump tem offsets absolutos no arquivo)
VIS_REWRITES = {BSP_LUMPS.GAME_LUMP, BSP_LUMPS.PAKFILE}

DISPINFO_SIZE = 176
DISP_EDGE_OFS = 48          # CDispNeighbor m_EdgeNeighbors[4]: 2 x CDispSubNeighbor (u16 vizinho, 3 x u8, 1 pad)
DISP_CORNER_OFS = 96        # CDispCornerNeighbors m_CornerNeighbors[4]: u16 vizinhos[4], u8 quantos, 1 pad


def enabled() -> bool:
    return os.environ.get("HT_NO_CACHE") != "1"


# ---------------------------------------------------------------------------
# normalização do lixo do vbsp (só para a chave)
# ---------------------------------------------------------------------------

def norm_dispinfo(data: bytes) -> bytes:
    """Zera o que não tem significado nos vizinhos dos displacements: sub-vizinho 0xFFFF (nenhum) leva lixo nos
    outros campos, o byte de alinhamento sempre, e vizinhos de canto além da contagem."""
    out = bytearray(data)
    for base in range(0, len(out) - DISPINFO_SIZE + 1, DISPINFO_SIZE):
        for k in range(8):
            o = base + DISP_EDGE_OFS + 6 * k
            if out[o] == 0xFF and out[o + 1] == 0xFF:
                out[o + 2:o + 6] = b"\0\0\0\0"
            out[o + 5] = 0
        for k in range(4):
            o = base + DISP_CORNER_OFS + 10 * k
            n = min(out[o + 8], 4)
            out[o + 2 * n:o + 8] = bytes(8 - 2 * n)
            out[o + 9] = 0
    return bytes(out)


def norm_sprp(data: bytes) -> bytes:
    """Props estáticos: zera o byte 31 de cada prop (lixo de memória no v10 do GMod)."""
    try:
        n_names = struct.unpack_from("<i", data, 0)[0]
        o = 4 + 128 * n_names
        names = [bytes(data[4 + 128 * i:4 + 128 * (i + 1)]).split(b"\0")[0] for i in range(n_names)]
        n_leaf = struct.unpack_from("<i", data, o)[0]
        o += 4 + 2 * n_leaf
        n_props = struct.unpack_from("<i", data, o)[0]
        base = o + 4
        if n_props <= 0 or (len(data) - base) % n_props:
            return data
        size = (len(data) - base) // n_props
        out = bytearray(data)
        for i, nm in enumerate(names):
            out[4 + 128 * i:4 + 128 * (i + 1)] = nm.ljust(128, b"\0")
        if size >= 32:
            for p in range(n_props):
                out[base + p * size + 31] = 0
        return bytes(out)
    except struct.error:
        return data


DETAIL_OBJ_SIZE = 52        # DetailObjectLump_t v4


def norm_dprp(data: bytes) -> bytes:
    """Props de detalhe: nomes de modelo com lixo depois do \\0; nos objetos (v4, 52 bytes) os bytes de alinhamento
    e, em objeto de modelo (tipo 0), os campos que só valem para sprite (sway, forma, escala), que o vbsp não preenche."""
    try:
        n = struct.unpack_from("<i", data, 0)[0]
        if n < 0 or 4 + 128 * n > len(data):
            return data
        out = bytearray(data)
        for i in range(n):
            s = 4 + 128 * i
            out[s:s + 128] = bytes(out[s:s + 128]).split(b"\0")[0].ljust(128, b"\0")
        o = 4 + 128 * n
        n_spr = struct.unpack_from("<i", data, o)[0]
        o += 4 + 32 * n_spr
        n_obj = struct.unpack_from("<i", data, o)[0]
        base = o + 4
        if n_obj > 0 and len(data) - base == DETAIL_OBJ_SIZE * n_obj:
            for k in range(n_obj):
                s = base + DETAIL_OBJ_SIZE * k
                out[s + 41:s + 44] = b"\0\0\0"
                out[s + 45:s + 48] = b"\0\0\0"
                if out[s + 44] == 0:
                    out[s + 37:s + 40] = b"\0\0\0"
                    out[s + 48:s + 52] = b"\0\0\0\0"
        return bytes(out)
    except struct.error:
        return data


# ---------------------------------------------------------------------------
# entidades
# ---------------------------------------------------------------------------

def parse_entities(text: bytes) -> list[list[tuple[str, str]]]:
    """Lump ENTITIES -> lista de entidades (pares chave/valor na ordem, chave em minúsculas)."""
    ents: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] | None = None
    for raw in text.decode("utf-8", "replace").splitlines():
        line = raw.strip()
        if line == "{":
            cur = []
        elif line == "}":
            if cur is not None:
                ents.append(cur)
            cur = None
        elif cur is not None and line.startswith('"'):
            parts = line.split('"')
            if len(parts) >= 4:
                cur.append((parts[1].lower(), parts[3]))
    return ents


def _get(ent, key: str, default: str = "") -> str:
    for k, v in ent:
        if k == key:
            return v
    return default


def vis_entities(ents) -> list:
    """O que o vvis lê das entidades: o farz do env_fog_controller (raio de vis)."""
    return sorted(_get(e, "farz") for e in ents if _get(e, "classname").lower() == "env_fog_controller")


def rad_entities(ents) -> list:
    """O que o vrad pode ler das entidades, em forma canônica. Luzes levam a posição na lista (o worldlight guarda o
    índice da entidade dona); entidades de brush, worldspawn, sky_camera e qualquer uma com chave de compilação
    (`_light`, `_minlight`, `_castentityshadow`...) entram inteiras; alvo de luz (spot mirando) entra pela posição."""
    out = []
    targets = set()
    for i, e in enumerate(ents):
        cls = _get(e, "classname").lower()
        if cls.startswith("light"):
            out.append(("luz", i, sorted(e)))
            t = _get(e, "target")
            if t:
                targets.add(t.lower())
        elif (cls in ("worldspawn", "sky_camera") or _get(e, "model").startswith("*")
              or any(k.startswith("_") or k.startswith("vrad_") for k, _ in e)):
            out.append(("ent", cls, sorted(e)))
    if targets:
        for e in ents:
            if _get(e, "targetname").lower() in targets:
                out.append(("alvo", _get(e, "targetname").lower(), _get(e, "origin")))
    out.sort(key=repr)
    return out


# ---------------------------------------------------------------------------
# chaves
# ---------------------------------------------------------------------------

def tool_id(exe: Path | str | None) -> str:
    """Identidade do compilador: nome, tamanho e data (atualização do jogo troca o binário = cache novo)."""
    if not exe:
        return "-"
    p = Path(exe)
    try:
        st = p.stat()
        return f"{p.name.lower()}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return p.name.lower()


def _h(*parts) -> str:
    h = hashlib.blake2b(digest_size=20)
    for p in parts:
        if isinstance(p, (bytes, bytearray, memoryview)):
            h.update(len(p).to_bytes(8, "little"))
            h.update(p)
        else:
            s = json.dumps(p, sort_keys=True, default=str).encode()
            h.update(len(s).to_bytes(8, "little"))
            h.update(s)
    return h.hexdigest()


def geometry_digest(b: BSP) -> str:
    """Impressão de tudo que não é entidade, game lump nem pakfile (com o lixo do vbsp zerado)."""
    parts = []
    for lump in BSP_LUMPS:
        if lump in NOT_GEOMETRY or lump not in b.lumps:
            continue
        L = b.lumps[lump]
        data = L.data
        if lump == BSP_LUMPS.DISPINFO:
            data = norm_dispinfo(data)
        parts += [lump.value, L.version, data]
    return _h(FORMAT, "geo", *parts)


def props_digest(b: BSP) -> str:
    parts = []
    for gid in sorted(b.game_lumps):
        g = b.game_lumps[gid]
        data = g.data
        if gid == b"sprp":
            data = norm_sprp(data)
        elif gid == b"dprp":
            data = norm_dprp(data)
        parts += [gid, g.version, g.flags, data]
    return _h("props", *parts)


def pak_digest(b: BSP) -> str:
    raw = b.lumps[BSP_LUMPS.PAKFILE].data if BSP_LUMPS.PAKFILE in b.lumps else b""
    if not raw:
        return _h("pak", [])
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        items = sorted((i.filename.lower().replace("\\", "/"), i.CRC, i.file_size) for i in z.infolist())
    except zipfile.BadZipFile:
        return _h("pak-raw", raw)
    return _h("pak", items)


@dataclass
class Keys:
    vis: str | None       # None: vvis desligado
    rad: str | None       # None: vrad desligado


def compute_keys(bsp: Path, prt: Path | None, vis_args: list[str] | None, vvis: Path | None,
                 rad_args: list[str] | None, vrad: Path | None) -> Keys:
    """Chaves do vvis e do vrad para o BSP que acabou de sair do vbsp (antes do vvis)."""
    b = BSP(str(bsp))
    ents = parse_entities(b.lumps[BSP_LUMPS.ENTITIES].data)
    geo = geometry_digest(b)
    vis = None
    if vis_args is not None:
        prt_data = prt.read_bytes() if prt and prt.exists() else b""
        vis = _h(FORMAT, "vis", geo, prt_data, vis_entities(ents), list(vis_args), tool_id(vvis))
    rad = None
    if rad_args is not None:
        rad = _h(FORMAT, "rad", geo, vis or "sem-vis", props_digest(b), pak_digest(b), rad_entities(ents),
                 list(rad_args), tool_id(vrad))
    return Keys(vis, rad)


# ---------------------------------------------------------------------------
# armazenamento
# ---------------------------------------------------------------------------

def lump_hashes(bsp: Path) -> dict[int, str]:
    b = BSP(str(bsp))
    return {k.value: hashlib.blake2b(L.data, digest_size=16).hexdigest() for k, L in b.lumps.items()}


class Cache:
    """Pasta `build/cache` do mapa: vis-<chave>.npz-like (lumps do vvis) e rad-<chave>.bsp (BSP final)."""

    def __init__(self, folder: Path, keep: int | None = None):
        self.folder = Path(folder)
        self.keep = keep if keep is not None else int(os.environ.get("HT_CACHE_KEEP", KEEP))

    def _vis_file(self, key: str) -> Path:
        return self.folder / f"vis-{key}.lumps"

    def _rad_file(self, key: str) -> Path:
        return self.folder / f"rad-{key}.bsp"

    def _prune(self, prefix: str, newest: Path | None = None) -> None:
        """Fica com as `keep` entradas usadas por último (a recém-gravada sempre fica)."""
        files = sorted((f for f in self.folder.glob(f"{prefix}-*") if f != newest),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for f in files[max(1, self.keep) - (1 if newest else 0):]:
            f.unlink(missing_ok=True)

    @staticmethod
    def _touch(f: Path) -> None:
        try:
            os.utime(f)
        except OSError:
            pass

    # ---- vis ----
    def save_vis(self, key: str, before: dict[int, str], bsp: Path) -> list[str]:
        """Guarda os lumps que o vvis mudou (comparando com os hashes de antes dele)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        b = BSP(str(bsp))
        changed = {}
        for k, L in b.lumps.items():
            if k in VIS_REWRITES:
                continue
            if hashlib.blake2b(L.data, digest_size=16).hexdigest() != before.get(k.value):
                changed[k.value] = (L.version, L.data)
        buf = io.BytesIO()
        buf.write(b"HTVC")
        buf.write(struct.pack("<ii", FORMAT, len(changed)))
        for k, (ver, data) in sorted(changed.items()):
            buf.write(struct.pack("<iiq", k, ver, len(data)))
            buf.write(data)
        tmp = self._vis_file(key).with_suffix(".tmp")
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, self._vis_file(key))
        self._prune("vis", self._vis_file(key))
        return [BSP_LUMPS(k).name for k in sorted(changed)]

    def load_vis(self, key: str) -> dict[int, tuple[int, bytes]] | None:
        f = self._vis_file(key)
        if not f.exists():
            return None
        data = f.read_bytes()
        if data[:4] != b"HTVC":
            return None
        fmt, n = struct.unpack_from("<ii", data, 4)
        if fmt != FORMAT:
            return None
        o, out = 12, {}
        for _ in range(n):
            k, ver, ln = struct.unpack_from("<iiq", data, o)
            o += 16
            out[k] = (ver, data[o:o + ln])
            o += ln
        self._touch(f)
        return out

    def restore_vis(self, key: str, bsp: Path) -> list[str] | None:
        """Põe no BSP os lumps guardados do vvis. None = não estava no cache."""
        lumps = self.load_vis(key)
        if lumps is None:
            return None
        b = BSP(str(bsp))
        for k, (ver, data) in lumps.items():
            L = b.lumps[BSP_LUMPS(k)]
            L.data, L.version = data, ver
        _save_atomic(b, bsp)
        return [BSP_LUMPS(k).name for k in sorted(lumps)]

    # ---- rad ----
    def save_rad(self, key: str, bsp: Path) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self._rad_file(key).with_suffix(".tmp")
        shutil.copy2(bsp, tmp)
        os.replace(tmp, self._rad_file(key))
        self._prune("rad", self._rad_file(key))

    def restore_rad(self, key: str, bsp: Path) -> bool:
        """BSP final guardado com as entidades (e a revisão) do BSP novo. False = não estava no cache."""
        f = self._rad_file(key)
        if not f.exists():
            return False
        new = BSP(str(bsp))
        old = BSP(str(f))
        old.lumps[BSP_LUMPS.ENTITIES].data = new.lumps[BSP_LUMPS.ENTITIES].data
        old.map_revision = new.map_revision
        _save_atomic(old, bsp)
        self._touch(f)
        return True


def _save_atomic(b: BSP, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".cache.tmp")
    b.save(str(tmp))
    os.replace(tmp, dest)
