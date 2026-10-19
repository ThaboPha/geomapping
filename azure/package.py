"""Build an allowlisted App Service ZIP without local settings or credentials."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'geomap_app'
OUTPUT = ROOT / 'artifacts' / 'geobonlytics.zip'
OUTPUT.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.write(APP / 'app.py', 'app.py')
    archive.write(APP / '.streamlit' / 'config.toml', '.streamlit/config.toml')
    archive.write(ROOT / 'azure' / 'startup.sh', 'startup.sh')
    archive.write(ROOT / 'azure' / 'requirements.txt', 'requirements.txt')
    for folder in ('geomap', 'assets'):
        for file in sorted((APP / folder).rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix not in ('.pyc', '.log'):
                archive.write(file, file.relative_to(APP).as_posix())
    snapshot=APP/'snapshotdata'
    if snapshot.exists() and not (snapshot/'manifest.json').exists():
        raise ValueError('Snapshot directory is incomplete; refusing to package it.')
    if (snapshot/'manifest.json').exists():
        import json,hashlib
        manifest=json.loads((snapshot/'manifest.json').read_text())
        if not manifest.get('complete'): raise ValueError('Cannot package an incomplete snapshot.')
        archive.write(snapshot/'manifest.json','snapshotdata/manifest.json')
        for name,entry in manifest['datasets'].items():
            if entry['file']!=name+'.parquet': raise ValueError('Invalid snapshot filename.')
            file=snapshot/entry['file']
            if hashlib.sha256(file.read_bytes()).hexdigest()!=entry['sha256']: raise ValueError('Snapshot checksum failed.')
            archive.write(file,'snapshotdata/'+file.name)
print(OUTPUT)
print(f'{OUTPUT.stat().st_size:,} bytes')
