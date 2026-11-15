"""Optional language-server packs, downloaded on demand.

Java (jdtls + a bundled JRE) and C/C++ (clangd) need binaries that are far too
large to put inside the installer, so they are fetched from their official
sources and unpacked under a per-user directory instead. Nothing here is
language specific beyond the entry-point lookup for each pack; the language
adapters in engine/languages.py just ask for a command.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
import zipfile

ROOT = pathlib.Path.home() / ".qta" / "langpacks"
STAGING_SUFFIX = ".staging"
CURL = shutil.which("curl.exe") or shutil.which("curl")
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Only the sources we can actually reach and verify a layout for are listed.
PACKS: list[dict] = [
    {
        "id": "java",
        "label": "Java",
        "detail": "jdtls + 内置 JRE 25，装完不依赖本机 Java",
        "size_mb": 102,
        "requires": "约 102 MB 下载，磁盘约 320 MB",
        "artifacts": [
            {
                # The Eclipse download server is unusably slow on some networks;
                # open-vsx serves the exact same jdtls build inside the Java
                # extension. Pin the version so the layout stays predictable.
                "url": "https://open-vsx.org/api/redhat/java/1.59.2026111308/file/"
                       "redhat.java-1.59.2026111308.vsix",
                "name": "redhat.java.vsix",
                "kind": "zip",
                "dest": "jdtls",
                "pick": "extension/server",
                "label": "jdtls",
            },
            {
                # This jdtls build resolves bundles that require JavaSE 25
                # (osgi.ee version=25), so the bundled runtime must be 25.
                "url": "https://api.adoptium.net/v3/binary/latest/25/ga/windows/x64/jre/hotspot/normal/eclipse",
                "name": "jre.zip",
                "kind": "zip",
                "dest": "jre",
                "label": "JRE 25",
            },
        ],
    },
    {
        "id": "cpp",
        "label": "C / C++",
        "detail": "clangd 23.1.0，单个可执行文件，无额外运行时",
        "size_mb": 30,
        "requires": "约 30 MB 下载，磁盘约 110 MB",
        "artifacts": [
            {
                "url": "https://github.com/clangd/clangd/releases/download/23.1.0/clangd-windows-23.1.0.zip",
                "name": "clangd.zip",
                "kind": "zip",
                "dest": "clangd",
                "label": "clangd",
            },
        ],
    },
]

_LOCK = threading.Lock()
_PROGRESS: dict[str, dict] = {}


def root() -> pathlib.Path:
    override = os.environ.get("QTA_LANGPACK_DIR", "").strip()
    base = pathlib.Path(override).expanduser() if override else ROOT
    base.mkdir(parents=True, exist_ok=True)
    return base


def pack_dir(pack_id: str) -> pathlib.Path:
    return root() / pack_id


def meta_path(pack_id: str) -> pathlib.Path:
    return pack_dir(pack_id) / "pack.json"


def _read_meta(pack_id: str) -> dict:
    try:
        return json.loads(meta_path(pack_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _norm(path: pathlib.Path) -> str:
    return path.as_posix()


def _java_command(base: pathlib.Path) -> tuple[str, ...] | None:
    java = next(iter(sorted(base.glob("jre/*/bin/javaw.exe"))), None)
    if java is None:
        java = base / "jre" / "bin" / "javaw.exe"
    if not java.is_file():
        return None
    jars = sorted(base.glob("jdtls/plugins/org.eclipse.equinox.launcher_*.jar"))
    if not jars:
        return None
    config = base / "jdtls" / ("config_win" if os.name == "nt" else "config_linux")
    if not config.is_dir():
        return None
    data = base / "workspace"
    data.mkdir(parents=True, exist_ok=True)
    return (
        _norm(java), "-jar", _norm(jars[-1]),
        "-configuration", _norm(config),
        "-data", _norm(data),
        "-Xms256m", "-Xmx1g",
    )


def _cpp_command(base: pathlib.Path) -> tuple[str, ...] | None:
    exe = next(iter(sorted(base.glob("clangd/*/bin/clangd.exe"))), None)
    if exe is None:
        exe = base / "clangd" / "bin" / "clangd.exe"
    if not exe.is_file():
        return None
    return (_norm(exe), "--background-index")


_COMMANDS = {"java": _java_command, "cpp": _cpp_command}


def server_command(pack_id: str) -> tuple[str, ...] | None:
    """The launch command for an installed pack, or None if it is not usable."""
    builder = _COMMANDS.get(pack_id)
    if builder is None:
        return None
    try:
        return builder(pack_dir(pack_id))
    except OSError:
        return None


def _artifact_url(art: dict) -> str:
    return art["url"]


def _remote_size(url: str) -> int:
    if not CURL:
        return 0
    try:
        out = subprocess.run(
            [CURL, "-sS", "-I", "-L", "--ssl-no-revoke", "--max-time", "30", url],
            capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    total = 0
    for line in out.stdout.splitlines():
        if line.lower().startswith("content-length:"):
            try:
                total = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return total


def _curl_download(url: str, target: pathlib.Path, pack_id: str, index: int,
                   count: int, label: str, expected: int) -> None:
    total = _remote_size(url) or expected
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    # System curl handles the Windows TLS/proxy stack reliably; --ssl-no-revoke
    # only relaxes the certificate revocation lookup, chain and host are still
    # verified.
    process = subprocess.Popen(
        [CURL, "-L", "--fail", "--ssl-no-revoke", "--retry", "2",
         "--connect-timeout", "30", "--max-time", "2400",
         "-o", str(target), url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    while process.poll() is None:
        size = target.stat().st_size if target.exists() else 0
        share = (size / total) if total else 0.0
        _set_progress(
            pack_id, (index + min(share, 1.0)) / count,
            f"正在下载 {label} {size // (1024 * 1024)}/{total // (1024 * 1024) or '?'} MB",
        )
        time.sleep(0.8)
    if process.returncode != 0:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"{label} 下载失败（curl {process.returncode}），检查网络后重试")


def _download(art: dict, target: pathlib.Path, pack_id: str,
              index: int, count: int) -> None:
    if CURL:
        _curl_download(art["url"], target, pack_id, index, count,
                       art["label"], int(art.get("bytes") or 0))
        if target.stat().st_size < 1024:
            raise RuntimeError(f"{art['label']} 下载得到空文件")
        return
    request = urllib.request.Request(
        _artifact_url(art),
        headers={"User-Agent": "Quick-TakeApart/langpacks", "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                share = (done / total) if total else 0.0
                _set_progress(
                    pack_id,
                    (index + min(share, 1.0)) / count,
                    f"正在下载 {art['label']} "
                    f"{done // (1024 * 1024)}/{total // (1024 * 1024) or '?'} MB",
                )
    if target.stat().st_size < 1024:
        raise RuntimeError(f"{art['label']} 下载得到空文件")


def _safe_members_tar(archive: tarfile.TarFile, dest: pathlib.Path):
    for member in archive.getmembers():
        resolved = (dest / member.name).resolve()
        if dest.resolve() not in resolved.parents and resolved != dest.resolve():
            raise RuntimeError(f"压缩包包含越界路径：{member.name}")
        if member.issym() or member.islnk():
            continue
        yield member


def _extract(art: dict, archive: pathlib.Path, dest: pathlib.Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if art["kind"] == "tar.gz":
        with tarfile.open(archive, "r:gz") as tar:
            members = list(_safe_members_tar(tar, dest))
            tar.extractall(dest, members=members)
    else:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                resolved = (dest / info.filename).resolve()
                if dest.resolve() not in resolved.parents and resolved != dest.resolve():
                    raise RuntimeError(f"压缩包包含越界路径：{info.filename}")
            zf.extractall(dest)


def _set_progress(pack_id: str, percent: float, message: str,
                  state: str = "installing") -> None:
    with _LOCK:
        _PROGRESS[pack_id] = {
            "state": state,
            "percent": round(max(0.0, min(1.0, percent)) * 100, 1),
            "message": message,
        }


def _clear_progress(pack_id: str) -> None:
    with _LOCK:
        _PROGRESS.pop(pack_id, None)


def install(pack_id: str) -> dict:
    """Start a background install. Re-entrant calls return the running state."""
    spec = next((item for item in PACKS if item["id"] == pack_id), None)
    if spec is None:
        raise KeyError(pack_id)
    with _LOCK:
        running = (_PROGRESS.get(pack_id) or {}).get("state") == "installing"
    if running:
        return item(pack_id)
    _set_progress(pack_id, 0.0, "准备下载…")
    thread = threading.Thread(target=_install_worker, args=(pack_id,), daemon=True)
    thread.start()
    return item(pack_id)


def _install_worker(pack_id: str) -> None:
    spec = next(item for item in PACKS if item["id"] == pack_id)
    staging = root() / f"{pack_id}{STAGING_SUFFIX}"
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        artifacts = spec["artifacts"]
        count = len(artifacts)
        for index, art in enumerate(artifacts):
            archive = staging / art["name"]
            _set_progress(pack_id, index / count, f"正在下载 {art['label']}")
            _download(art, archive, pack_id, index, count)
            _set_progress(pack_id, (index + 1) / count, f"正在解压 {art['label']}")
            raw = staging / "raw" / art["dest"]
            _extract(art, archive, raw)
            source = raw / art["pick"] if art.get("pick") else raw
            target = staging / "out" / art["dest"]
            if not source.is_dir():
                raise RuntimeError(f"{art['label']} 内没有找到 {art.get('pick') or '/'} 目录")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            archive.unlink(missing_ok=True)

        built = staging / "out"
        builder = _COMMANDS[pack_id]
        command = builder(built)
        if not command:
            raise RuntimeError("解压后没找到语言服务器入口文件")

        final = pack_dir(pack_id)
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(built), str(final))
        meta = {
            "id": pack_id,
            "label": spec["label"],
            "command": list(command),
            "artifacts": [art["url"] for art in artifacts],
            "installed_at": _now(),
            "size_mb": spec["size_mb"],
        }
        meta_path(pack_id).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        _set_progress(pack_id, 1.0, f"{spec['label']} 已就绪", state="installed")
    except Exception as exc:  # surfaced to the settings page, not swallowed
        _set_progress(pack_id, 0.0, f"安装失败：{exc}", state="failed")
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def remove(pack_id: str) -> dict:
    with _LOCK:
        _PROGRESS.pop(pack_id, None)
    target = pack_dir(pack_id)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            raise RuntimeError("删除失败，可能语言服务仍在运行，请重启应用后重试")
    return item(pack_id)


def item(pack_id: str) -> dict:
    spec = next((entry for entry in PACKS if entry["id"] == pack_id), None)
    if spec is None:
        raise KeyError(pack_id)
    command = server_command(pack_id)
    meta = _read_meta(pack_id)
    with _LOCK:
        progress = dict(_PROGRESS.get(pack_id) or {})
    state = progress.get("state") or ("installed" if command else "idle")
    return {
        "id": spec["id"],
        "label": spec["label"],
        "detail": spec["detail"],
        "size_mb": spec["size_mb"],
        "requires": spec["requires"],
        "installed": bool(command),
        "state": state,
        "percent": progress.get("percent", 100.0 if command else 0.0),
        "message": progress.get("message", ""),
        "command": " ".join(command) if command else "",
        "installed_at": meta.get("installed_at", ""),
    }


def items() -> list[dict]:
    return [item(spec["id"]) for spec in PACKS]


def known(pack_id: str) -> bool:
    return any(spec["id"] == pack_id for spec in PACKS)
