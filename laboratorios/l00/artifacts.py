"""Download explícito dos artefatos oficiais fixados, fora do Git."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import zipfile

PROJECT = Path(__file__).resolve().parents[2]


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_target(root, name):
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Caminho fora do diretório de artefatos')
    return target


def prepare(cache, download=False):
    root = Path(cache).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = json.loads((PROJECT/'materiais/m1/artefatos.lock.json').read_text(encoding='utf-8'))
    rows = []
    for item in lock['artifacts']:
        path = checked_target(root, item['filename'])
        if not path.exists() and download:
            partial = path.with_suffix(path.suffix+'.partial')
            # Um download interrompido não é promovido nem sobrescrito silenciosamente.
            with partial.open('xb') as output, urlopen(item['url'], timeout=90) as response:
                while chunk := response.read(1024*1024):
                    output.write(chunk)
            if partial.stat().st_size != item['size'] or file_hash(partial) != item['sha256']:
                raise ValueError('Download divergente preservado em ' + str(partial))
            partial.rename(path)
        if not path.is_file() or file_hash(path) != item['sha256']:
            raise ValueError('Artefato ausente ou divergente: ' + str(path))
        rows.append({'id': item['id'], 'sha256': item['sha256'], 'bytes': path.stat().st_size})
    runtime = next(x for x in lock['artifacts'] if x['id'] == 'llama_cpp_cpu')
    destination = root / ('runtime_' + runtime['release'])
    with zipfile.ZipFile(root/runtime['filename']) as archive:
        for member in archive.infolist():
            target = checked_target(destination, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            content = archive.read(member)
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError('Runtime extraído divergente: ' + str(target))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    return {'verified': rows, 'runtime_extracted': True, 'runtime_executed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.cache, args.download), indent=2))
