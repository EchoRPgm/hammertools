"""Auto-update pelos releases do GitHub (`ht update`).

O release (`.github/workflows/release.yml`, disparado por tag `vX.Y.Z`) publica o wheel. Aqui: consulta o último
release, baixa o wheel e instala por cima no MESMO ambiente que está rodando (venv do `uv tool` ou pip), depois
refaz a integração com o Hammer++ (`ht setup --refresh`: FGD e sequências mudam junto com o pacote).

Automático: (1) no início de cada compile (`ht-vbsp`, consulta sempre, timeout de 3 s; com versão nova instala e
compila já com ela, ver `before_compile`); (2) no fim de cada comando `ht`, no máximo uma consulta por dia. Sem rede
segue em silêncio. Desliga com `ht update --auto off` ou env HT_NO_UPDATE=1.
Checkout do git (desenvolvimento) nunca se atualiza sozinho.

Repo público: funciona sem token. Se houver um (HT_GITHUB_TOKEN, GITHUB_TOKEN, arquivo `token` na pasta de config
gravado por `ht update --token ...`, ou `gh auth token`), é usado: limite maior da API e repo privado, se voltar a ser.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from hammertools import __version__

REPO = "EchoRPgm/hammertools"
API = f"https://api.github.com/repos/{REPO}"
CHECK_EVERY = 24 * 3600
TIMEOUT = 4.0


def parse_version(s: str) -> tuple[int, ...]:
    s = s.strip().lstrip("vV")
    parts = []
    for p in s.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "hammertools"


def _state_path() -> Path:
    return config_dir() / "update.json"


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        _state_path().parent.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass


def token() -> str | None:
    for var in ("HT_GITHUB_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    f = config_dir() / "token"
    if f.exists():
        t = f.read_text(encoding="utf-8").strip()
        if t:
            return t
    gh = shutil.which("gh")
    if gh:
        try:
            out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=3)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def save_token(value: str) -> Path:
    f = config_dir() / "token"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(value.strip() + "\n", encoding="utf-8")
    try:
        f.chmod(0o600)
    except OSError:
        pass
    return f


def _get(url: str, accept: str = "application/vnd.github+json", timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"hammertools/{__version__}",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    t = token()
    if t:
        req.add_header("Authorization", f"Bearer {t}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_asset(url: str, timeout: float = 120) -> bytes:
    """Asset de release privado: a API responde 302 pra uma URL assinada (S3) que recusa o header Authorization,
    e o urllib repassaria o header no redirect. Pega o Location sem seguir e baixa sem token."""
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream", "User-Agent": f"hammertools/{__version__}"})
    t = token()
    if t:
        req.add_header("Authorization", f"Bearer {t}")
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            return r.read()                       # sem redirect (servidor entregou direto)
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"):
            raise
        location = e.headers["Location"]
    plain = urllib.request.Request(location, headers={"User-Agent": f"hammertools/{__version__}"})
    with urllib.request.urlopen(plain, timeout=timeout) as r:
        return r.read()


def latest_release(timeout: float = TIMEOUT) -> dict | None:
    """{'version', 'tag', 'wheel' (URL da API do asset), 'wheel_name', 'notes'} do último release, ou None."""
    data = json.loads(_get(f"{API}/releases/latest", timeout=timeout))
    wheel = next((a for a in data.get("assets", []) if a.get("name", "").endswith(".whl")), None)
    if wheel is None:
        return None
    tag = data.get("tag_name", "")
    return {"version": tag.lstrip("vV"), "tag": tag, "wheel": wheel["url"], "wheel_name": wheel["name"],
            "notes": data.get("body") or ""}


def newer(rel: dict | None, current: str = __version__) -> bool:
    return bool(rel) and parse_version(rel["version"]) > parse_version(current)


def dev_install() -> bool:
    """Rodando de um checkout do git (pip -e): quem atualiza é o git, não o release."""
    here = Path(__file__).resolve().parent
    return any((p / ".git").exists() for p in (here.parent, here.parent.parent))


def install_command(wheel: Path) -> list[str]:
    """Instala o wheel no ambiente deste Python (mantém numpy/scipy e o resto que já está lá)."""
    uv = shutil.which("uv")
    if uv is None:      # o Hammer/atalho pode não ter o PATH do usuário: lugares onde o instalador põe o uv
        for cand in (Path.home() / ".local" / "bin", Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
                     Path.home() / ".cargo" / "bin"):
            exe = cand / ("uv.exe" if os.name == "nt" else "uv")
            if exe.exists():
                uv = str(exe)
                break
    if uv:
        return [uv, "pip", "install", "--python", sys.executable, "--upgrade", str(wheel)]
    return [sys.executable, "-m", "pip", "install", "--upgrade", str(wheel)]


def _scripts_dir() -> Path:
    return Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")


def _unlock_scripts() -> None:
    """Windows não deixa sobrescrever um .exe em uso (o próprio ht.exe), mas deixa renomear: tira do caminho."""
    if os.name != "nt":
        return
    for exe in _scripts_dir().glob("ht*.exe"):
        old = exe.with_suffix(".exe.old")
        try:
            old.unlink(missing_ok=True)
            exe.rename(old)
        except OSError:
            pass


def _cleanup_old() -> None:
    for old in _scripts_dir().glob("ht*.exe.old"):
        try:
            old.unlink()
        except OSError:
            pass


def apply(rel: dict, log=print) -> bool:
    _cleanup_old()
    with tempfile.TemporaryDirectory(prefix="ht-update-") as tmp:
        wheel = Path(tmp) / rel["wheel_name"]
        wheel.write_bytes(download_asset(rel["wheel"]))
        _unlock_scripts()
        cmd = install_command(wheel)
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode != 0:
            # devolve os .exe renomeados pra não deixar o ht quebrado
            if os.name == "nt":
                for old in _scripts_dir().glob("ht*.exe.old"):
                    new = old.with_suffix("")
                    if not new.exists():
                        try:
                            old.rename(new)
                        except OSError:
                            pass
            log(f"ht update: falhou ao instalar {rel['wheel_name']}:\n{(out.stderr or out.stdout).strip()}")
            return False
    log(f"ht update: instalado {rel['tag']} (era {__version__})")
    # a integração com o Hammer++ vem do pacote novo: roda num processo novo
    sys.stdout.flush()
    sys.stderr.flush()
    subprocess.run([sys.executable, "-m", "hammertools", "setup", "--refresh"])
    return True


def check(force: bool = False, timeout: float = TIMEOUT) -> dict | None:
    """Último release se for mais novo que o instalado. Sem `force`, no máximo uma consulta por CHECK_EVERY."""
    state = load_state()
    now = time.time()
    if not force and now - state.get("last_check", 0) < CHECK_EVERY:
        rel = state.get("latest")
        return rel if newer(rel) else None
    state["last_check"] = now
    try:
        rel = latest_release(timeout)
    except (urllib.error.URLError, OSError, ValueError):
        rel = None
    state["latest"] = rel
    save_state(state)
    return rel if newer(rel) else None


def auto(log=lambda m: print(m, file=sys.stderr)) -> None:
    """Chamado no fim de cada comando `ht`. Nunca levanta exceção."""
    try:
        if os.environ.get("HT_NO_UPDATE") == "1" or dev_install():
            return
        rel = check()
        if not rel:
            return
        if load_state().get("auto", True):
            log(f"ht: atualizando {__version__} -> {rel['tag']} ...")
            apply(rel, log)
        else:
            log(f"ht: versão nova {rel['tag']} (instalada {__version__}); rode `ht update`")
    except Exception:  # auto-update nunca derruba o comando que o usuário rodou
        pass


COMPILE_TIMEOUT = 3.0


def before_compile(argv: list[str], log=print) -> int | None:
    """Início do `ht-vbsp`: consulta o release a CADA compile (timeout curto). Com versão nova, instala e roda o
    compile com o código novo num processo filho (este já carregou o antigo) e devolve o código de saída dele; o
    Hammer++ espera este processo, então vvis/vrad só começam depois. None = segue o compile aqui mesmo (sem
    versão nova, offline, auto desligado ou qualquer erro: atualizar nunca impede o compile)."""
    try:
        if os.environ.get("HT_NO_UPDATE") == "1" or dev_install():
            return None
        rel = check(force=True, timeout=COMPILE_TIMEOUT)
        if not rel:
            return None
        if not load_state().get("auto", True):
            log(f"ht-vbsp: versão nova {rel['tag']} (instalada {__version__}); rode `ht update`")
            return None
        log(f"ht-vbsp: atualizando {__version__} -> {rel['tag']} antes de compilar ...")
        if not apply(rel, log):
            return None
        log("ht-vbsp: entidades novas do FGD só aparecem depois de reabrir o Hammer++")
        sys.stdout.flush()
        # a trava do mapa é deste processo (vbsp_main a pegou antes): o filho é a mesma compilação, não outra.
        # Sem isto ele via a trava do pai vivo e saía com 3 ("já há uma compilação rodando") a cada auto-update
        env = dict(os.environ, HT_NO_UPDATE="1", HT_VBSP_LOCK_HELD=str(os.getpid()))
        code = "import sys; from hammertools.cli import vbsp_main; sys.exit(vbsp_main())"
        rc = subprocess.call([sys.executable, "-c", code, *argv], env=env)
        os.environ["HT_NO_UPDATE"] = "1"      # o pai (código velho) não tenta atualizar de novo nesta execução
        return rc
    except Exception as e:  # noqa: BLE001
        log(f"ht-vbsp: auto-update falhou ({e}); compilando com a versão {__version__}")
        return None


def cmd_update(args) -> int:
    if args.token:
        print(f"token gravado em {save_token(args.token)}")
    if args.auto:
        state = load_state()
        state["auto"] = args.auto == "on"
        save_state(state)
        print(f"auto-update {'ligado' if state['auto'] else 'desligado'}")
    if args.token or args.auto:
        if not args.check:
            return 0
    try:
        rel = latest_release(timeout=15)
    except urllib.error.HTTPError as e:
        hint = {401: " (token inválido: `ht update --token <token>`)", 403: " (token sem acesso ou limite da API)",
                404: " (nenhum release publicado)"}.get(e.code, "")
        print(f"ht update: GitHub respondeu {e.code}{hint}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"ht update: sem acesso ao GitHub ({e})", file=sys.stderr)
        return 1
    state = load_state()
    state.update(last_check=time.time(), latest=rel)
    save_state(state)
    if rel is None:
        print("ht update: o último release não tem wheel")
        return 1
    if not newer(rel):
        print(f"ht {__version__} já é a última versão ({rel['tag']})")
        return 0
    print(f"versão nova: {rel['tag']} (instalada {__version__})")
    if args.check:
        return 0
    if dev_install():
        print("checkout do git: atualize com `git pull` (o update instalaria por cima do modo editável)", file=sys.stderr)
        return 1
    return 0 if apply(rel) else 1
