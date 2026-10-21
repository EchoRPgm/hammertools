"""Geradores ht_* como serviço para editores (EchoHammer): `ht gen --serve` lê um pedido JSON por linha no stdin e
responde uma linha JSON no stdout com a geometria de cada grupo de marcadores, sem tocar no VMF.

Pedido:   {"markers": [{"id": 12, "classname": "ht_stairs", "kv": {"origin": "0 0 0", "targetname": "e1", ...}}, ...]}
Resposta: {"groups": [{"key": "ht_stairs:e1", "classname": "ht_stairs", "name": "e1", "markers": [12, 13],
                       "vmf": "solid\\n{...}\\n", "detail": true, "ents": [{"classname": ..., "origin": ..., ...}],
                       "warnings": [...], "cached": false}], "ms": 12.3}
          {"error": "..."} se o pedido não for JSON válido.

`vmf` são os blocos solid no formato do VMF (o editor lê com o mesmo parser do mapa). Cada grupo é guardado pelo
conteúdo dos seus marcadores: mexer num marcador só refaz o grupo dele."""
from __future__ import annotations

import io
import json
import sys
import time

from srctools import VMF

from hammertools.core import vmf as vmfio
from hammertools.generators import REGISTRY, Result

_cache: dict[str, dict] = {}


def _signature(group: vmfio.Group) -> str:
    return json.dumps(sorted((e["classname"], sorted(e.items())) for e in group.ents), sort_keys=True)


def _solids_text(solids) -> str:
    buf = io.StringIO()
    for s in solids:
        s.export(buf, ind="", include_groups=False)
    return buf.getvalue()


def _ent_json(e) -> dict:
    out = dict(e.items())
    if e.solids:
        out["_solids"] = _solids_text(e.solids)
    return out


def _pairing_hints(groups: dict[str, vmfio.Group]) -> dict[str, str]:
    """Grupo sem par (só o início, ou só o _end) diz o que falta: quantos marcadores dessa ferramenta estão sem nome e
    que, com mais de um par, cada par precisa do mesmo targetname. O aviso do gerador ("precisa de um ... com o mesmo
    targetname") não dizia por que o par não se formou."""
    from hammertools.generators import SINGLE
    hints: dict[str, str] = {}
    by_base: dict[str, list[vmfio.Group]] = {}
    for g in groups.values():
        by_base.setdefault(g.classname, []).append(g)
    for base, gs in by_base.items():
        if base in SINGLE:
            continue
        unnamed = [g for g in gs if all(not e.get("targetname") for e in g.ents)]
        starts = sum(1 for g in unnamed for e in g.ents if vmfio.role_of(e) == "start")
        ends = sum(1 for g in unnamed for e in g.ents if vmfio.role_of(e) == "end")
        for key, g in groups.items():
            if g.classname != base:
                continue
            roles = {vmfio.role_of(e) for e in g.ents}
            if "start" in roles and "end" in roles:
                continue
            o = vmfio.origin(g.ents[0])
            where = f"em {o.x:g} {o.y:g} {o.z:g}"
            cls = base if "start" in roles else f"{base}_end"
            name = g.ents[0].get("targetname")
            if name:
                other = f"{base}_end" if "start" in roles else base
                hints[key] = f"{cls} '{name}' {where} sem {other} com o mesmo targetname"
            else:
                hints[key] = (f"{cls} {where} sem par: o mapa tem {starts} {base} e {ends} {base}_end sem nome; com mais de "
                              f"um par, dê o mesmo targetname ao pé ({base}) e ao topo ({base}_end) de cada um")
    return hints


def generate(markers: list[dict]) -> list[dict]:
    """Roda os geradores para os marcadores dados (lista do pedido) e devolve os grupos."""
    v = VMF()
    by_ent: dict[int, int] = {}
    ents = []
    for m in markers:
        e = v.create_ent(m["classname"])
        for k, val in (m.get("kv") or {}).items():
            if k.lower() not in ("classname", "id"):
                e[k] = str(val)
        by_ent[id(e)] = m.get("id", e.id)
        ents.append(e)
    groups = vmfio.group_markers(vmfio.markers(v))
    hints = _pairing_hints(groups)
    out = []
    live = set()
    for key, g in groups.items():
        sig = g.classname + "|" + _signature(g)
        live.add(sig)
        ids = [by_ent[id(e)] for e in g.ents]
        hit = _cache.get(sig)
        if hit is None:
            gen = REGISTRY.get(g.classname)
            if gen is None:
                res = Result(warnings=[f"{g.classname}: sem gerador registrado"])
            else:
                try:
                    res = gen(v, g)
                except Exception as ex:   # um grupo mal configurado não derruba os outros
                    res = Result(warnings=[f"{g.name}: erro no gerador: {ex}"])
            hit = {"classname": g.classname, "name": g.name, "vmf": _solids_text(res.solids),
                   "detail": vmfio.detail_for(g, res.detail), "ents": [_ent_json(e) for e in res.ents],
                   "warnings": list(res.warnings), "solids": len(res.solids)}
            _cache[sig] = hit
            cached = False
        else:
            cached = True
        item = {"key": key, "markers": ids, "cached": cached, **hit}
        if key in hints:
            item = {**item, "warnings": [hints[key], *hit["warnings"]]}
        out.append(item)
    for k in [k for k in _cache if k not in live]:   # grupos que sumiram do mapa saem do cache
        del _cache[k]
    return out


def serve(game: str | None = None, stdin=None, stdout=None) -> int:
    from hammertools.core import models
    models.GAMEDIR = game
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    from hammertools import __version__
    stdout.write(json.dumps({"ready": True, "version": __version__, "generators": sorted(REGISTRY)}) + "\n")
    stdout.flush()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        t0 = time.perf_counter()
        try:
            req = json.loads(line)
            resp = {"groups": generate(req.get("markers") or [])}
        except Exception as ex:
            resp = {"error": f"{type(ex).__name__}: {ex}"}
        resp["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        stdout.write(json.dumps(resp) + "\n")
        stdout.flush()
    return 0
