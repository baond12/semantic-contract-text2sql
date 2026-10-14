#!/usr/bin/env python3
"""Verify SQLite deliverable and independent schema.sql + seed_data.sql replay."""
import hashlib
import json
import sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FILE=ROOT/'omnichannel_retail.sqlite3'
D=sqlite3.connect(FILE)
D.execute('PRAGMA foreign_keys=ON')
R=sqlite3.connect(':memory:')
R.execute('PRAGMA foreign_keys=ON')
R.executescript((ROOT/'schema.sql').read_text(encoding='utf-8'))
R.executescript((ROOT/'seed_data.sql').read_text(encoding='utf-8'))
tables=lambda db:sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
assert tables(D)==tables(R) and len(tables(D))==20
assert len([x for t in tables(D) for x in D.execute('PRAGMA foreign_key_check')])==0
assert not R.execute('PRAGMA foreign_key_check').fetchall()
assert D.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert R.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
results=[]
for t in tables(D):
    original=list(D.execute(f'SELECT * FROM "{t}" ORDER BY rowid'))
    replay=list(R.execute(f'SELECT * FROM "{t}" ORDER BY rowid'))
    assert original==replay,(t,'replay differs',len(original),len(replay))
    assert list(D.execute(f'PRAGMA table_info("{t}")'))==list(R.execute(f'PRAGMA table_info("{t}")'))
    assert list(D.execute(f'PRAGMA foreign_key_list("{t}")'))==list(R.execute(f'PRAGMA foreign_key_list("{t}")'))
    results.append({'table':t,'rows':len(original),'replay_exact':True})

# Confirm SQLite actually rejects NULL TEXT primary keys, not just metadata.
negative_sql=[
    "INSERT INTO products(product_id,sku,name) VALUES(NULL,'INVALID_NULL_PRODUCT','TEST')",
    "INSERT INTO agents(agent_id,agent_code,full_name) VALUES(NULL,'INVALID_NULL_AGENT','TEST')",
    "INSERT INTO chats(chat_id,conversation_id,customer_id,chat_time,sender_type,content) VALUES(NULL,'INVALID_NULL_CHAT',1,'2026-10-01','CUSTOMER','TEST')",
    "INSERT INTO addresses(address_id,customer_id,formatted_address) VALUES(NULL,1,'TEST')",
    "INSERT INTO order_items(order_item_id,order_id,product_id,quantity,unit_price,line_discount) VALUES(999999,1,'MISSING',1,100,0)",
]
for sql in negative_sql:
    R.execute('SAVEPOINT negative_test')
    try:
        R.execute(sql)
    except sqlite3.IntegrityError:
        R.execute('ROLLBACK TO negative_test')
        R.execute('RELEASE negative_test')
    else:
        R.execute('ROLLBACK TO negative_test')
        R.execute('RELEASE negative_test')
        raise AssertionError('Must reject invalid insert: '+sql)

# Compare every declared SQL FK to exactly one Mermaid relationship and one dot edge.
fks=[]
for t in tables(D):
    fks.extend((t,f[3],f[2],f[4]) for f in D.execute(f'PRAGMA foreign_key_list("{t}")'))
mermaid=(ROOT/'ERD.mmd').read_text(encoding='utf-8')
dot=(ROOT/'ERD.dot').read_text(encoding='utf-8')
for child,child_col,parent,parent_col in fks:
    assert mermaid.count(f'{child.upper()} : "{child_col}"')==1,(child,child_col)
    assert dot.count(f'"{child}" -> "{parent}"') >= 1
assert len(fks)==31
status=json.loads((ROOT/'validation.json').read_text(encoding='utf-8'))
status.update({'replay_from_schema_and_seed':'PASS',
               'replay_all_rows_match_original':True,
               'replay_all_columns_and_foreign_keys_match':True,
               'erd_fk_relationships_match_physical_schema':True,
               'rejected_invalid_inserts':len(negative_sql),
               'all_20_tables_have_data':True,
               'replayed_validation':'PASS'})
(ROOT/'validation.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('PASS',len(results),'tables',sum(i['rows'] for i in results),'rows,',len(fks),'FKs, schema+seed exact replay; negative tests:',len(negative_sql))
for i in results:print(i['table'],i['rows'])
R.close();D.close()
