#!/usr/bin/env python3
"""Re-create v06 from schema.sql and seed_data.sql; does not need the Product source file."""
import argparse
import sqlite3
from pathlib import Path

base=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description='Rebuild the deterministic 20-table Omnichannel Retail demo.')
parser.add_argument('--output',type=Path,default=base/'omnichannel_retail_rebuilt.sqlite3')
args=parser.parse_args()
output=args.output.expanduser().resolve()
if output.exists():
    parser.error(f'Output exists, refusing to overwrite: {output}')
output.parent.mkdir(parents=True,exist_ok=True)
db=sqlite3.connect(output)
try:
    db.execute('PRAGMA foreign_keys = ON')
    db.executescript((base/'schema.sql').read_text(encoding='utf-8'))
    db.executescript((base/'seed_data.sql').read_text(encoding='utf-8'))
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    assert len(tables)==20
    assert all(db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]>0 for t in tables)
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    print('PASS:',output,', tables:',len(tables),', FK violations: 0')
except Exception:
    db.close()
    output.unlink(missing_ok=True)
    raise
finally:
    try: db.close()
    except: pass
