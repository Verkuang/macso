"""Encrypted portable files/preferences; deliberately excludes browser auth and TCC."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import tarfile
import tempfile
import subprocess
import sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"MACSO_STATE_1\n"
LIMIT = 20 * 1024 * 1024
ROOTS = ("Desktop", "Documents", "MacsoProjects")
PREFS = {
    "com.apple.finder": {"AppleShowAllFiles", "ShowPathbar", "ShowStatusBar", "FXPreferredViewStyle"},
    "com.apple.dock": {"autohide", "tilesize", "orientation", "magnification", "largesize"},
    ".GlobalPreferences": {"AppleLanguages", "AppleLocale", "AppleInterfaceStyle", "AppleShowAllExtensions"},
}

def key(password, salt):
    if not password:
        raise ValueError("Backup password is not configured")
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 1_200_000, dklen=32)

def safe_name(name):
    p = PurePosixPath(name)
    return (not p.is_absolute() and ".." not in p.parts and bool(p.parts)
            and (p.parts[0] in ROOTS or (len(p.parts) == 3 and p.parts[:2] == ("Library", "Preferences")
                and p.name in {n + ".plist" for n in PREFS})))

def files(home):
    for root in ROOTS:
        base = home / root
        if base.is_symlink() or not base.is_dir():
            continue
        for folder, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", "build", "dist"}
                             and not (Path(folder)/d).is_symlink())
            for name in sorted(names):
                path = Path(folder)/name
                if not name.startswith(".") and not path.is_symlink() and path.is_file():
                    yield path

def pack(home, password, target):
    buffer = io.BytesIO()
    count, total = 0, 0
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in files(home):
            if count >= 9000:
                raise ValueError("Saved file count limit exceeded")
            data = path.read_bytes() if path.stat().st_size <= LIMIT else None
            if data is None or total + len(data) > LIMIT:
                raise ValueError("Saved files exceed the 20 MiB limit; previous backup is retained")
            entry = tarfile.TarInfo(path.relative_to(home).as_posix())
            entry.size, entry.mode = len(data), 0o600
            tar.addfile(entry, io.BytesIO(data))
            total += len(data)
            count += 1
        for domain, allowed in PREFS.items():
            path = home / "Library" / "Preferences" / (domain + ".plist")
            if path.is_symlink() or not path.is_file():
                continue
            values = plistlib.loads(path.read_bytes())
            data = plistlib.dumps({k: v for k, v in values.items() if k in allowed})
            entry = tarfile.TarInfo(path.relative_to(home).as_posix())
            entry.size, entry.mode = len(data), 0o600
            tar.addfile(entry, io.BytesIO(data))
    raw = buffer.getvalue()
    if len(raw) > LIMIT + 1024 * 1024:
        raise ValueError("Encrypted backup size limit exceeded")
    salt, nonce = os.urandom(32), os.urandom(12)
    encrypted = MAGIC + salt + nonce + AESGCM(key(password, salt)).encrypt(nonce, raw, MAGIC)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
        temp.write(encrypted)
        name = temp.name
    os.chmod(name, 0o600)
    os.replace(name, target)
    return {"files": count, "bytes": total, "encrypted_bytes": len(encrypted)}

def restore(home, password, source):
    data = source.read_bytes()
    if not data.startswith(MAGIC) or len(data) > LIMIT + 2 * 1024 * 1024:
        raise ValueError("Invalid or oversized backup")
    pos = len(MAGIC)
    salt, nonce, encrypted = data[pos:pos+32], data[pos+32:pos+44], data[pos+44:]
    raw = AESGCM(key(password, salt)).decrypt(nonce, encrypted, MAGIC)
    prepared, total = [], 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or not safe_name(member.name):
                raise ValueError("Backup contains an unsafe path")
            total += member.size
            if total > LIMIT + 1024 * 1024 or len(prepared) >= 10000:
                raise ValueError("Expanded backup limit exceeded")
            target = home / member.name
            if any(p.is_symlink() for p in [target, *target.parents] if p != home.parent):
                raise ValueError("Restore path contains a symbolic link")
            content = tar.extractfile(member).read()
            if member.name.startswith("Library/Preferences/"):
                domain = target.name[:-6]
                saved = plistlib.loads(content)
                if set(saved) - PREFS[domain]:
                    raise ValueError("Unsupported preference setting")
                existing = plistlib.loads(target.read_bytes()) if target.exists() else {}
                existing.update(saved)
                content = plistlib.dumps(existing)
            prepared.append((target, content))
    for target, content in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
            temp.write(content)
            name = temp.name
        os.chmod(name, 0o600)
        os.replace(name, target)
    if sys.platform == "darwin" and home.resolve() == Path.home().resolve():
        for target, _ in prepared:
            if target.parent.name == "Preferences":
                domain = "-g" if target.name == ".GlobalPreferences.plist" else target.name[:-6]
                subprocess.run(["/usr/bin/defaults", "import", domain, str(target)], check=True, capture_output=True, timeout=10)
    return {"restored_entries": len(prepared)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["pack", "restore"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    password = os.environ.get("MACOS_STATE_KEY") or os.environ.get("MACOS_PASSWORD", "")
    try:
        result = (pack if args.mode == "pack" else restore)(args.home, password, args.path)
        print(json.dumps({"status": args.mode + "_verified", **result}))
    except Exception:
        # Do not reveal names, file contents, authentication data, or passwords.
        print("State operation failed: wrong key, unsafe paths, changed files, or 20 MiB limit. Previous remote backup remains available.")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
