"""H026 preregistered gate then optional corpus collision screen."""
from pathlib import Path
import argparse,datetime as dt,hashlib,json,math,random,re,sys,time,traceback,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from lp_lab.h026_wordmask import blocks,control_words,fingerprint
from lp_lab.synthetic import encode_text
from lp_lab.execution import execute
from lp_lab.provenance import sha256

SPEC=ROOT/'hypotheses/H026-word-mask-collisions-v1.json'
WORKER=ROOT/'scripts/h026_wordmask_worker_v1.py'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def independent(words):
    total=0
    for i,a in enumerate(words):
        for b in words[i+1:]:
            if len(a)==len(b) and len(a)>=3:
                k=(a[0]-b[0])%29
                total+=all((x-y)%29==k for x,y in zip(a,b))
    return total

def worker(run,label,jobs,remaining):
    folder=run/label
    write(folder/'public.json',dict(jobs=jobs))
    result=execute([sys.executable,'-I','-S','-B','-X','utf8',str(WORKER)],cwd=ROOT,timeout=max(1,int(remaining)),stdin=json.dumps(dict(jobs=jobs)))
    write(folder/'execution.json',result)
    (folder/'stdout.json').write_text(result['stdout'],encoding='utf8')
    (folder/'stderr.txt').write_text(result['stderr'],encoding='utf8')
    if result['status']!='completed':
        if result['status']=='timeout': raise TimeoutError('worker timeout')
        raise RuntimeError('worker error')
    output=json.loads(result['stdout'])
    if not output['read_guard_probe_passed']: raise ValueError('guard failed')
    if [r['id'] for r in output['results']] != [j['id'] for j in jobs]: raise ValueError('coverage')
    for j,row in zip(jobs,output['results']):
        if independent(j['words'])!=row['observed']: raise ValueError('independent collision mismatch')
        if len(row['controls'])!=99: raise ValueError('control coverage')
    return output['results']

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    run=args.out.resolve()
    if not run.is_relative_to(ROOT/'runs'): raise ValueError('outside runs')
    run.mkdir(parents=True,exist_ok=False)
    start=time.monotonic(); stamp=lambda:dt.datetime.now(dt.timezone.utc).isoformat()
    paths=[SPEC,WORKER,Path(__file__),ROOT/'src/lp_lab/h026_wordmask.py',ROOT/'src/lp_lab/runes.py',ROOT/'src/lp_lab/synthetic.py',ROOT/'src/lp_lab/execution.py',ROOT/'src/lp_lab/provenance.py',ROOT/'src/lp_lab/__init__.py',ROOT/'src/lp_lab/cipher.py',ROOT/'data/synthetic/heldout.txt',ROOT/'data/attempt1-corpus-v1.json',ROOT/'data/README.md',ROOT/'reviews/auto-cycle-009.md']
    hashes={p.relative_to(ROOT).as_posix():sha256(p) for p in paths}
    record=dict(hypothesis='H026-word-mask-collisions-v1',status='running',started_at_utc=stamp(),source_hashes=hashes,lp2_pages_dispatched=0,unsolved_page_candidates=[])
    write(run/'record.json',record);write(run/'frozen.json',dict(specification=json.loads(SPEC.read_text(encoding='utf8')),source_hashes=hashes,frozen_at_utc=stamp()))
    def deadline():
        if time.monotonic()-start>300: raise TimeoutError('300 second budget')
    try:
        fixture=blocks('ᚠ/ᚢ ᚦ-ᚩᚱ;A1ᚳᚷ.ᚹ')
        if [b['values'] for b in fixture]!=[[0,1,2],[3,4],[5,6],[7]]: raise ValueError('parser fixture')
        source=[encode_text(w) for w in re.findall('[A-Za-z]+',(ROOT/'data/synthetic/heldout.txt').read_text(encoding='utf8'))]
        rng=random.Random(330119261);jobs=[];private={}
        for i in range(119):
            n=[40,48,56,64,72][i%5];s=(i*7)%(len(source)-n+1);plain=source[s:s+n]
            kind='positive' if i<20 else ('independent_rune' if i<70 else 'within_word_permutation')
            words=[]
            for word in plain:
                if kind=='independent_rune': cipher=[(x+rng.randrange(29))%29 for x in word]
                else:
                    a=list(word)
                    if kind=='within_word_permutation':rng.shuffle(a)
                    k=rng.randrange(29);cipher=[(x+k)%29 for x in a]
                if len(cipher)>=3: words.append(cipher)
            jid=f'case-{i:03d}';jobs.append(dict(id=jid,words=words));private[jid]=dict(kind=kind,start_word=s,window_words=n,plaintext=[w for w in plain if len(w)>=3])
            if kind=='positive' and [fingerprint(w) for w in words]!=[fingerprint(w) for w in private[jid]['plaintext']]: raise ValueError('exact cancellation')
        write(run/'verifier-only/gate-answers.json',dict(generation_seed=330119261,answers=private))
        rows=worker(run,'gate-worker',jobs,300-(time.monotonic()-start));deadline()
        for j in range(2):
            for r in range(99):
                if independent(control_words(jobs[j]['words'],j,r))!=rows[j]['controls'][r]: raise ValueError('independent control mismatch')
        for row in rows:row['kind']=private[row['id']]['kind']
        good=sum(r['p']<=.01 for r in rows if r['kind']=='positive');false=sum(r['p']<=.01 for r in rows if r['kind']!='positive')
        gate=dict(status='passed' if good>=18 and false==0 else 'failed',positive_passes=good,positive_count=20,negative_false_accepts=false,negative_count=99,rows=rows,independent_observed_checks=119,independent_control_checks=198,positive_fingerprint_checks=20,limitation='Overlapping windows from one synthetic natural document, not independent natural texts.')
        write(run/'gate.json',gate);record.update(gate_status=gate['status'],positive_passes=good,negative_false_accepts=false)
        if gate['status']!='passed':
            record.update(status='inconclusive',reason='power_gate_failed',formal_confirmation=False,controls_completed=0)
        else:
            corpus=json.loads((ROOT/'data/attempt1-corpus-v1.json').read_text(encoding='utf8'));formal=[];coverage=[]
            for page in corpus['pages']:
                chunks=blocks(page['raw']);words=[b['values'] for b in chunks if len(b['values'])>=3];runes=sum(len(b['values']) for b in chunks)
                coverage.append(dict(page=page['page'],runes=runes,scored_words=len(words),scored_runes=sum(map(len,words)),blocks=chunks,raw_sha256=page['raw_sha256'],source=page['source']))
                if runes:formal.append(dict(id=page['page'],words=words))
            if len(formal)!=55 or sum(r['runes'] for r in coverage)!=12956:raise ValueError('corpus coverage')
            write(run/'coverage.json',coverage);record['lp2_pages_dispatched']=len(formal)
            rows=worker(run,'formal-worker',formal,300-(time.monotonic()-start));deadline()
            maxima=[];z=[]
            for row in rows:
                a=[row['observed']]+row['controls'];mean=sum(a)/100;sd=math.sqrt(sum((v-mean)**2 for v in a)/100)
                z.append([(v-mean)/sd if sd else 0 for v in a])
            maxima=[max(v[r] for v in z) for r in range(100)]
            for j,row in enumerate(rows):row['max_t_p']=(1+sum(v>=z[j][0] for v in maxima[1:]))/100
            sums=[sum(r['observed'] if i==0 else r['controls'][i-1] for r in rows) for i in range(100)]
            gp=(1+sum(v>=sums[0] for v in sums[1:]))/100
            leads=[r['id'] for r in rows if r['max_t_p']<=.01]
            if gp<=.01:leads.append('global-sum')
            write(run/'screening.json',dict(status='inconclusive' if leads else 'negative',formal_confirmation=False,replicates=99,page_rows=rows,global_score=sums[0],global_p=gp,exploratory_leads=leads,confirmed_leads=[],reason='99-control exploratory screen only; joint endpoint Bonferroni alpha.005 unattainable at this resolution.'))
            record.update(status='inconclusive' if leads else 'negative',formal_confirmation=False,controls_completed=99,exploratory_leads=leads,reason='fixed_parser_collision_screen_only')
        deadline()
    except Exception as exc:
        record.update(status='timeout' if isinstance(exc,TimeoutError) else 'error',error=repr(exc))
        (run/'runner.stderr.txt').write_text(traceback.format_exc(),encoding='utf8')
    if any(sha256(ROOT/p)!=h for p,h in hashes.items()):record.update(status='error',error='direct input changed')
    record.update(finished_at_utc=stamp(),elapsed_seconds=time.monotonic()-start)
    write(run/'record.json',record)
    archive=run/'reproduction-bundle.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in paths+[p for p in run.rglob('*') if p.is_file() and p!=archive]:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip(): raise ValueError('archive CRC')
    write(run/'archive-manifest.json',dict(sha256=sha256(archive),crc='passed'))
    print(json.dumps({k:v for k,v in record.items() if k!='source_hashes'},ensure_ascii=False))
    return int(record['status'] in {'error','timeout'})

if __name__=='__main__':sys.exit(main())
