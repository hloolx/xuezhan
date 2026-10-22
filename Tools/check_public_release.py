"""Audit tracked public files without reading private asset folders or printing secrets."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PREFIXES = (
    'rawassets/', 'content/artpilot/', 'content/audio/thirdparty/',
    '.tripo/', '.impeccable/', 'reviews/', 'saved/', 'binaries/',
    'intermediate/', 'deriveddatacache/', 'build/',
)
MODEL_SUFFIXES = {'.fbx', '.glb', '.gltf', '.blend', '.blend1', '.obj', '.usd', '.usda', '.usdc', '.usdz'}
TEXT_SUFFIXES = {'.cpp', '.h', '.cs', '.py', '.ps1', '.cmd', '.md', '.txt', '.json', '.ini', '.yml', '.yaml', '.cjs'}
SECRET = re.compile(
    r'gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|'
    r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|'
    r'Bearer [A-Za-z0-9._-]{30,}|[?&](?:X-Amz-Signature|X-Oss-Signature)=|'
    r'^SecurityToken\s*=\s*\S+',
    re.IGNORECASE | re.MULTILINE,
)


def main():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    failures = []
    count = size = 0
    for relative in filter(None, paths):
        path = ROOT / relative
        name = relative.lower()
        suffix = path.suffix.lower()
        count += 1
        if name.startswith(PRIVATE_PREFIXES) or suffix in MODEL_SUFFIXES:
            failures.append((relative, 'private/generated path or model format'))
        if name.startswith('content/data/') and 'art' in path.name.lower():
            failures.append((relative, 'private art mapping'))
        if suffix in {'.uasset', '.umap'}:
            allowed = name in {
                'content/art/m_cwstylized.uasset', 'content/art/m_cwwarning.uasset',
                'content/maps/battlefield.umap', 'content/ui/epicborders/t_commandframe.uasset',
                'content/audio/music/mus_titan.uasset', 'content/audio/music/mus_legionnaire.uasset',
                'content/audio/music/mus_juggernaut.uasset',
            } or (name.startswith('content/audio/sfx_') and name.count('/') == 2 and suffix == '.uasset')
            if not allowed:
                failures.append((relative, 'unreviewed Unreal binary'))
        if not path.is_file():
            failures.append((relative, 'missing tracked file'))
            continue
        size += path.stat().st_size
        if path.stat().st_size >= 100 * 1024 * 1024:
            failures.append((relative, 'exceeds normal GitHub file-size limit'))
        if suffix in TEXT_SUFFIXES and SECRET.search(path.read_text(encoding='utf-8-sig')):
            failures.append((relative, 'possible credential or signed URL; value withheld'))
        if suffix in {'.uasset', '.umap'}:
            data = path.read_bytes()
            if any(marker in data for marker in (b'/Game/ArtPilot/', '/Game/ArtPilot/'.encode('utf-16-le'))):
                failures.append((relative, 'binary references private art'))
    for relative, reason in failures:
        print(f'FAIL: {relative}: {reason}')
    print(f'Public audit: {count} files, {size / 1024 / 1024:.1f} MiB, {len(failures)} issues')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
