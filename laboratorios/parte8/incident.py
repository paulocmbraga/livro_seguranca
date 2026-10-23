"""Estado persistente, backup consistente e worker real revalidado no commit."""
from contextlib import closing
from pathlib import Path
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from .common import digest, new_output, write, read, sha, seal, integrity

CLEAN={'memory':'internal','model':'policy-v1-clean','index':'recovery documento aprovado'}


def connect(db):
    return sqlite3.connect(db,timeout=3)


def initialize(db):
    if Path(db).exists():raise FileExistsError(db)
    with closing(connect(db)) as c, c:
        c.executescript('''
        CREATE TABLE control(epoch INTEGER, key_version INTEGER, contained INTEGER);
        INSERT INTO control VALUES(0,1,0);
        CREATE TABLE sessions(id TEXT PRIMARY KEY, epoch INTEGER);
        INSERT INTO sessions VALUES('old-session',0);
        CREATE TABLE delegations(id TEXT PRIMARY KEY, epoch INTEGER);
        INSERT INTO delegations VALUES('old-delegation',0);
        CREATE TABLE artifacts(kind TEXT PRIMARY KEY,value TEXT);
        CREATE VIRTUAL TABLE search USING fts5(content);
        CREATE TABLE jobs(id TEXT PRIMARY KEY, session TEXT, delegation TEXT, epoch INTEGER, state TEXT);
        CREATE TABLE effects(id TEXT PRIMARY KEY, destination TEXT);
        CREATE TABLE timeline(seq INTEGER PRIMARY KEY,event TEXT,epoch INTEGER);
        ''')
        c.executemany('INSERT INTO artifacts VALUES(?,?)',CLEAN.items())
        c.execute('INSERT INTO search VALUES(?)',(CLEAN['index'],))


def event(c,name):
    epoch=c.execute('SELECT epoch FROM control').fetchone()[0]
    c.execute('INSERT INTO timeline(event,epoch) VALUES(?,?)',(name,epoch))


def inventory(c):
    return dict(c.execute('SELECT kind,value FROM artifacts'))


def clean_state(c):
    found=inventory(c)
    index=[r[0] for r in c.execute('SELECT content FROM search')]
    return found==CLEAN and index==[CLEAN['index']]


def backup(db,target):
    if Path(target).exists():raise FileExistsError(target)
    with closing(connect(db)) as source,closing(connect(target)) as dest:
        source.backup(dest)


def compromise(db):
    with closing(connect(db)) as c,c:
        c.execute("UPDATE artifacts SET value='external' WHERE kind='memory'")
        c.execute("UPDATE artifacts SET value='policy-v2-contaminated' WHERE kind='model'")
        c.execute("UPDATE artifacts SET value='recovery documento contaminado' WHERE kind='index'")
        c.execute('DELETE FROM search')
        c.execute("INSERT INTO search VALUES('recovery documento contaminado')")
        event(c,'compromise')


def admit(db,job,session='old-session',delegation='old-delegation'):
    with closing(connect(db)) as c,c:
        c.execute('BEGIN IMMEDIATE')
        epoch,_,contained=c.execute('SELECT * FROM control').fetchone()
        s=c.execute('SELECT epoch FROM sessions WHERE id=?',(session,)).fetchone()
        d=c.execute('SELECT epoch FROM delegations WHERE id=?',(delegation,)).fetchone()
        if contained or s!=(epoch,) or d!=(epoch,):return False
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(job,session,delegation,epoch,'admitted'))
        event(c,'admit:'+job);return True


def execute(db,job,strict=True):
    with closing(connect(db)) as c,c:
        c.execute('BEGIN IMMEDIATE')
        epoch,_,contained=c.execute('SELECT * FROM control').fetchone()
        row=c.execute('SELECT session,delegation,epoch,state FROM jobs WHERE id=?',(job,)).fetchone()
        if not row:return 'missing'
        session,delegation,job_epoch,state=row
        if state!='admitted':return state
        live=c.execute('SELECT epoch FROM sessions WHERE id=?',(session,)).fetchone()==(epoch,)
        delegated=c.execute('SELECT epoch FROM delegations WHERE id=?',(delegation,)).fetchone()==(epoch,)
        if contained or job_epoch!=epoch or not live or not delegated:
            outcome='revoked'
        elif strict and not clean_state(c):outcome='quarantined'
        else:
            context=c.execute("SELECT content FROM search WHERE search MATCH 'recovery'").fetchall()
            if not context:outcome='no_context'
            else:
                destination=inventory(c)['memory']
                c.execute('INSERT INTO effects VALUES(?,?)',(job,destination));outcome='committed'
        c.execute('UPDATE jobs SET state=? WHERE id=?',(outcome,job));event(c,outcome+':'+job)
        return outcome


def contain(db):
    with closing(connect(db)) as c,c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('UPDATE control SET epoch=epoch+1,key_version=key_version+1,contained=1')
        c.execute('DELETE FROM sessions');c.execute('DELETE FROM delegations')
        event(c,'contain')


def readiness(db,revocation_floor):
    with closing(connect(db)) as c:
        epoch,_,contained=c.execute('SELECT * FROM control').fetchone()
        pending=c.execute("SELECT count(*) FROM jobs WHERE state='admitted'").fetchone()[0]
        return {'available':c.execute('SELECT 1').fetchone()==(1,),
                'artifacts_clean':clean_state(c),'epoch_current':epoch>=revocation_floor,
                'drained':pending==0,'contained':bool(contained)}


def release_allowed(report):
    required={'available','artifacts_clean','epoch_current','drained','contained'}
    return set(report)==required and all(type(v) is bool for v in report.values()) and all(report.values())


def recover(db,revocation_floor):
    if revocation_floor<1:raise ValueError('external revocation floor required')
    with closing(connect(db)) as c,c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('UPDATE control SET epoch=max(epoch,?),contained=1',(revocation_floor,))
        c.execute('DELETE FROM sessions');c.execute('DELETE FROM delegations')
        c.execute("UPDATE jobs SET state='cancelled' WHERE state='admitted'")
        c.execute('DELETE FROM artifacts');c.executemany('INSERT INTO artifacts VALUES(?,?)',CLEAN.items())
        c.execute('DELETE FROM search');c.execute('INSERT INTO search VALUES(?)',(CLEAN['index'],))
        event(c,'rebuilt_from_clean_source')
    report=readiness(db,revocation_floor)
    if not release_allowed(report):raise ValueError('release gate')
    with closing(connect(db)) as c,c:
        epoch=c.execute('SELECT epoch FROM control').fetchone()[0]
        c.execute("INSERT INTO sessions VALUES('new-session',?)",(epoch,))
        c.execute("INSERT INTO delegations VALUES('new-delegation',?)",(epoch,))
        c.execute('UPDATE control SET contained=0');event(c,'reopen')
    return report


def worker(db,job):
    print('READY',flush=True)
    # Barreira de teste via stdin; não representa timeout ou fila de produção.
    if sys.stdin.readline().strip()!='GO':return
    print(execute(db,job),flush=True)


def run(path):
    out=new_output(path);db=out/'incident.sqlite';initialize(db);compromise(db)
    backup(db,out/'evidence.sqlite');before=sha(out/'evidence.sqlite')
    with closing(connect(db)) as c,c:
        c.execute('UPDATE control SET key_version=key_version+1');event(c,'rotate_key_only')
    assert admit(db,'rotation-only')
    rotation=execute(db,'rotation-only',strict=False)
    # Reinício real de executor permissivo, preservando o armazenamento.
    assert admit(db,'restart-only')
    restarted=subprocess.run([sys.executable,'-m','laboratorios.parte8.incident',
                              '--legacy',str(db),'restart-only'],capture_output=True,
                             text=True,check=True,timeout=5)
    restart=restarted.stdout.strip()
    assert admit(db,'pending')
    child=subprocess.Popen([sys.executable,'-m','laboratorios.parte8.incident','--worker',str(db),'pending'],
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        import threading
        ready=[]
        thread=threading.Thread(target=lambda:ready.append(child.stdout.readline()),daemon=True)
        thread.start();thread.join(5)
        if ready!=['READY\n']:raise RuntimeError('worker handshake failed')
        contain(db);start=time.perf_counter()
        child.stdin.write('GO\n');child.stdin.flush()
        stdout,stderr=child.communicate(timeout=5)
        elapsed=time.perf_counter()-start
        if child.returncode:raise RuntimeError(stderr)
        stopped=stdout.strip()
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=5)
    floor=1
    old_session=admit(db,'late-old')
    backup(out/'evidence.sqlite',out/'restored.sqlite')
    dirty=readiness(out/'restored.sqlite',floor)
    assert not release_allowed(dirty)
    gate=recover(db,floor)
    assert admit(db,'legitimate','new-session','new-delegation')
    legitimate=execute(db,'legitimate')
    with closing(connect(db)) as c:
        final_effects=[list(r) for r in c.execute('SELECT * FROM effects ORDER BY id')]
        timeline=[list(r) for r in c.execute('SELECT * FROM timeline ORDER BY seq')]
        jobs=[list(r) for r in c.execute('SELECT * FROM jobs ORDER BY id')]
    assert sha(out/'evidence.sqlite')==before
    report={'rotation_only':rotation,'executor_restart_only':restart,'pending_worker':stopped,
            'old_session_admitted':old_session,'dirty_restore':dirty,'recovery_gate':gate,
            'legitimate':legitimate,'effects':final_effects,'jobs':jobs,
            'evidence_sha256':before,'worker_release_to_exit_seconds':elapsed,
            'time_limit':'medida do harness; não RTO/SLA; triagem e intervenção humanas não medidas',
            'scope':'SQLite/FTS5, estado e subprocesso reais; modelo é artefato de política preparado, não rede neural'}
    write(out/'timeline.json',timeline);write(out/'report.json',report);seal(out)
    return verify(out)


def verify(path):
    out=Path(path);integrity(out);r=read(out/'report.json')
    assert sha(out/'evidence.sqlite')==r['evidence_sha256']
    assert r['rotation_only']==r['executor_restart_only']=='committed'
    assert r['pending_worker']=='revoked' and r['old_session_admitted'] is False
    assert r['dirty_restore']==readiness(out/'restored.sqlite',1)
    assert r['dirty_restore']['available'] and not release_allowed(r['dirty_restore'])
    assert release_allowed(r['recovery_gate']) and r['legitimate']=='committed'
    with closing(connect(out/'incident.sqlite')) as c:
        assert clean_state(c)
        assert [list(x) for x in c.execute('SELECT * FROM effects ORDER BY id')]==r['effects']
        assert [list(x) for x in c.execute('SELECT * FROM timeline ORDER BY seq')]==read(out/'timeline.json')
        assert c.execute("SELECT count(*) FROM effects WHERE destination='external'").fetchone()[0]==2
        assert c.execute("SELECT count(*) FROM effects WHERE id='pending'").fetchone()[0]==0
    return r


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',nargs=2);p.add_argument('--legacy',nargs=2)
    a=p.parse_args()
    if a.worker:worker(*a.worker)
    elif a.legacy:print(execute(*a.legacy,strict=False))
