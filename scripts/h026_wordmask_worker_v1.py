"""Public-only H026 counts; worker cannot read verifier material."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from lp_lab.h026_wordmask import analyze

def guard(event,args):
    if event in {'open','os.listdir','os.scandir','os.system'} or event.startswith(('socket.','subprocess.','ctypes.')):
        raise PermissionError('H026 denies file/process/network I/O')

sys.addaudithook(guard)
try: open('__h026_forbidden__','rb')
except PermissionError: guarded=True
public=json.loads(sys.stdin.read())
if set(public)!={'jobs'} or not 1<=len(public['jobs'])<=119: raise ValueError('public contract')
rows=[]
for j,job in enumerate(public['jobs']):
    if set(job)!={'id','words'}: raise ValueError('private field in public job')
    if any(len(w)<3 or any(type(x)is not int or not 0<=x<29 for x in w) for w in job['words']): raise ValueError('bad words')
    rows.append(dict(id=job['id'],**analyze(job['words'],j)))
print(json.dumps(dict(read_guard_probe_passed=guarded,results=rows)))
