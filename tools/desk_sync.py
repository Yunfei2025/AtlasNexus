# -*- coding: utf-8 -*-
"""Share the Futures Desk state between computers through git.

The desk keeps its state in ``../input/futures_desk/`` -- outside the repo and under a git-ignored
``input/`` -- so it never reaches another machine on its own. This tool mirrors only what the Portfolio and
Monitor tabs need into the tracked folder ``desk_share/futures_desk/`` and commits just that folder:

    portfolio.json, approved.json, approved_daily.json   which products / which approved strategy
    wf_*.json                                            walk-forward runs of approved / portfolio products only
    manual/*.json                                        manual trade log
    monitor_bars/                                        the small bar slice the Monitor replays

Not shared: ``bars/`` (full cache, rebuilt from ticks), ``live/`` (Wind live fetch), anything else in input/.

    python tools/desk_sync.py push [-m "msg"] [--no-git]   this computer: input -> desk_share, commit, push
    python tools/desk_sync.py pull [--no-git]              other computer: git pull, desk_share -> input
    python tools/desk_sync.py status                       what differs, nothing written
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from settings.paths import DIR_INPUT  # noqa: E402

SRC = DIR_INPUT / 'futures_desk'
DST = REPO / 'desk_share' / 'futures_desk'
TOP_FILES = ('portfolio.json', 'approved.json', 'approved_daily.json')
SUBDIRS = ('manual', 'monitor_bars')      # mirrored whole (stale files removed on the receiving side)


def _needed_wf(base: Path) -> list[str]:
    """Walk-forward files the Portfolio/Monitor read: the exact variant (day / night) of each approved
    product, and every variant of a portfolio product that is not approved. The rest are research runs on
    products you have not taken up -- ~120 KB each, rewritten on every run, so they would bloat history."""
    import json
    try:
        approved = json.loads((base / 'approved.json').read_text(encoding='utf-8'))
        products = json.loads((base / 'portfolio.json').read_text(encoding='utf-8')).get('products', [])
    except Exception:
        return sorted(f.name for f in base.glob('wf_*.json'))     # can't tell: share them all
    names = [f"wf_{p}{'_night' if (r or {}).get('session') == 'night+day' else ''}.json"
             for p, r in approved.items()]
    for p in products:
        if p not in approved:
            names += [f'wf_{p}.json', f'wf_{p}_night.json']
    return names


def _shared(base: Path) -> dict[str, Path]:
    """Relative path -> file, for everything that is shared under ``base``."""
    out: dict[str, Path] = {}
    if not base.is_dir():
        return out
    for n in TOP_FILES:
        if (base / n).is_file():
            out[n] = base / n
    for name in _needed_wf(base):
        if (base / name).is_file():
            out[name] = base / name
    for d in SUBDIRS:
        if (base / d).is_dir():
            for f in (base / d).rglob('*'):
                if f.is_file() and not f.name.endswith('.tmp') and f.name != '.DS_Store':
                    out[f.relative_to(base).as_posix()] = f
    return out


def _mirror(src: Path, dst: Path, dry: bool = False, prune_all: bool = True) -> dict[str, list[str]]:
    """Copy the shared set src -> dst. Shared files missing from src are removed from dst: everywhere when
    ``prune_all`` (the repo mirror), but only inside SUBDIRS otherwise (a receiving computer keeps its own
    extra wf_*.json research runs)."""
    s, d = _shared(src), _shared(dst)
    if prune_all and dst.is_dir():          # repo mirror: also drop wf files that are no longer needed
        d.update({f.name: f for f in dst.glob('wf_*.json')})
    res = {'copied': [], 'removed': []}
    for rel, f in s.items():
        t = dst / rel
        if not t.exists() or not filecmp.cmp(f, t, shallow=False):
            res['copied'].append(rel)
            if not dry:
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, t)
    for rel, t in d.items():
        if rel not in s and (prune_all or rel.split('/')[0] in SUBDIRS):
            res['removed'].append(rel)
            if not dry:
                t.unlink()
    return res


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(['git', '-C', str(REPO), *args], check=check, capture_output=True, text=True)


def _report(res: dict) -> None:
    print(f"  copied {len(res['copied'])}, removed {len(res['removed'])}")


def push(message: str | None, use_git: bool) -> int:
    if not SRC.is_dir():
        print(f'Nothing to share: {SRC} does not exist.')
        return 1
    res = _mirror(SRC, DST)
    print(f'input -> {DST.relative_to(REPO)}')
    _report(res)
    if not use_git:
        return 0
    _git('add', '-A', '--', str(DST.parent.relative_to(REPO)))
    staged = _git('diff', '--cached', '--name-only', '--', 'desk_share').stdout.split()
    if not staged:
        print('git: desk_share already up to date, nothing to commit.')
        return 0
    stamp = ''
    try:
        import json
        stamp = f" ({len(json.loads((SRC / 'portfolio.json').read_text()).get('products', []))} products)"
    except Exception:
        pass
    # `--only` commits just desk_share even if other files are staged elsewhere.
    _git('commit', '--only', '-m', message or f'desk state{stamp}', '--', 'desk_share')
    print(f'git: committed {len(staged)} file(s) under desk_share/')
    p = _git('push', check=False)
    print(p.stdout.strip() or p.stderr.strip() or 'git: pushed')
    return p.returncode


def pull(use_git: bool) -> int:
    if use_git:
        p = _git('pull', '--ff-only', check=False)
        print(p.stdout.strip() or p.stderr.strip())
        if p.returncode:
            return p.returncode
    if not DST.is_dir():
        print('desk_share/futures_desk/ is not in this checkout yet.')
        return 1
    SRC.mkdir(parents=True, exist_ok=True)
    res = _mirror(DST, SRC, prune_all=False)
    print(f'{DST.relative_to(REPO)} -> {SRC}')
    _report(res)
    return 0


def status() -> int:
    for a, b, label in ((SRC, DST, 'push would change'), (DST, SRC, 'pull would change')):
        if not a.is_dir():
            print(f'{label}: nothing ({a} does not exist)')
            continue
        r = _mirror(a, b, dry=True, prune_all=(b == DST))
        print(f"{label}: copy {len(r['copied'])}, remove {len(r['removed'])}")
        for rel in r['copied'][:8]:
            print(f'   copy   {rel}')
        for rel in r['removed'][:8]:
            print(f'   remove {rel}')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('push', 'pull', 'status'))
    ap.add_argument('-m', '--message')
    ap.add_argument('--no-git', action='store_true', help='copy files only; no commit/push/pull')
    a = ap.parse_args()
    sys.exit(push(a.message, not a.no_git) if a.cmd == 'push' else pull(not a.no_git) if a.cmd == 'pull' else status())
