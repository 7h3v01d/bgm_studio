"""Verify source integrity and, optionally, Windows release tests.

Standard library only. This script never installs or upgrades dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = 'RELEASE_SHA256.json'
PACKAGES = ('numpy', 'soundfile', 'mido', 'pyfluidsynth', 'fastapi', 'uvicorn', 'PyQt6',
            'python-multipart', 'mcp', 'httpx', 'pytest')


# Not part of a release: local environments, native binaries, SoundFonts, generated audio and caches.
EXCLUDED_DIRS = {'.venv', 'venv', '.git', '__pycache__', '.pytest_cache', 'bgm_out', 'gui_exports',
                 'release_evidence', 'dist', 'build'}
EXCLUDED_SUFFIXES = ('.log', '.pyc')
# Folders where users install third-party binaries: only their instruction files are part of a release.
NATIVE_DIRS = {'soundfonts', 'fluidsynth'}


def release_files(root: Path) -> list[str]:
    """Every distributable file under `root` (POSIX-style relative paths), excluding EXCLUDED_DIRS and the manifest."""
    out = []
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if rel.parts[0] in NATIVE_DIRS and not (len(rel.parts) == 2 and path.suffix.lower() == '.txt'):
            continue
        if (path.is_file() and not set(rel.parts[:-1]) & EXCLUDED_DIRS and rel.parts[0] not in EXCLUDED_DIRS
                and rel.as_posix() != MANIFEST and not path.name.endswith(EXCLUDED_SUFFIXES)):
            out.append(rel.as_posix())
    return sorted(out)


def write_manifest(root: Path, release: str, baseline: str) -> int:
    files = release_files(root)
    manifest = {'schema': 1, 'release': release, 'baseline': baseline,
                'files': {name: hash_file(root / name) for name in files}}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return len(files)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(root: Path) -> dict:
    return json.loads((root / MANIFEST).read_text(encoding='utf-8'))


def validate_path(name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts or '\\' in name:
        raise ValueError(f'Unsafe manifest path: {name!r}')
    return relative


def verify(root: Path) -> tuple[bool, list[str]]:
    try:
        manifest = load_manifest(root)
        entries = manifest['files']
        if not isinstance(entries, dict) or not entries:
            raise ValueError('Empty/invalid manifest')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, [f'Cannot read manifest: {exc}']
    problems = []
    for name, expected in sorted(entries.items()):
        try:
            relative = validate_path(name)
            target = root / relative
            # Prevent manifest paths from resolving outside the project through symlinks.
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError('resolves outside project')
            if not target.is_file():
                problems.append(f'MISSING {name}')
            elif not isinstance(expected, str) or len(expected) != 64 or hash_file(target) != expected:
                problems.append(f'CHANGED {name}')
        except (OSError, ValueError, TypeError) as exc:
            problems.append(f'INVALID {name}: {exc}')
    return not problems, problems


def tool_version(name: str) -> str:
    try:
        p = subprocess.run([name, '-version'], capture_output=True, text=True, timeout=10)
        if p.returncode != 0:
            return f'ERROR exit={p.returncode}'
        return (p.stdout or p.stderr).splitlines()[0][:180]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f'UNAVAILABLE ({type(exc).__name__})'


def capture_environment(root: Path, dest: Path) -> None:
    packages = {}
    for package in PACKAGES:
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = 'NOT INSTALLED'
    evidence = {
        'schema': 1,
        'captured_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(),
        'platform': platform.system(),
        'platform_release': platform.release(),
        'dependencies': packages,
        'ffmpeg': tool_version('ffmpeg'),
        'ffprobe': tool_version('ffprobe'),
        'source_manifest_sha256': hash_file(root / MANIFEST),
        'note': 'Environment inventory only; does not authenticate installed packages or native binaries.'
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'[PASS] environment evidence saved to {dest}')


def run_tests(root: Path) -> bool:
    commands = ([sys.executable, '-m', 'pytest', '-q'], [sys.executable, 'selftest.py'])
    for cmd in commands:
        print(f'\n[RUN] {" ".join(cmd)}', flush=True)
        try:
            result = subprocess.run(cmd, cwd=root, check=False)
        except OSError as exc:
            print(f'[FAIL] could not start tests: {exc}', file=sys.stderr)
            return False
        if result.returncode != 0:
            print(f'[FAIL] test stage exited {result.returncode}', file=sys.stderr)
            return False
    print('[PASS] pytest and audio self-test completed successfully')
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='project root (defaults to script folder)')
    parser.add_argument('--tests', action='store_true', help='run pytest then the end-to-end audio self-test')
    parser.add_argument('--capture-env', action='store_true', help='write local environment evidence JSON')
    parser.add_argument('--write-manifest', metavar='RELEASE',
                        help='regenerate the manifest for release RELEASE (e.g. 0.11.1) from the current files')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.write_manifest:
        n = write_manifest(root, args.write_manifest, f'v{args.write_manifest}')
        print(f'[PASS] wrote {MANIFEST} for release {args.write_manifest} ({n} files)')
        return 0
    ok, problems = verify(root)
    if not ok:
        for problem in problems:
            print(f'[FAIL] {problem}', file=sys.stderr)
        return 1
    print(f'[PASS] {len(load_manifest(root)["files"])} distributed files match SHA-256 baseline')
    if args.capture_env:
        capture_environment(root, root / 'release_evidence' / 'environment.json')
    if args.tests and not run_tests(root):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
