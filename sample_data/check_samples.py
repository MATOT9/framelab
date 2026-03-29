from pathlib import Path
import csv

manifest = Path(__file__).with_name('manifest.csv')
with manifest.open(newline='', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
for row in rows:
    p = manifest.parent / 'raw' / row['filename']
    print(f"{row['filename']}: {p.stat().st_size} bytes, fmt={row['pixel_format']}, stride={row['stride_bytes']}")
