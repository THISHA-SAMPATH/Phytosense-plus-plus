import sys, os
from collections import deque
import numpy as np
import pandas as pd

RAIL_HI, RAIL_LO, FLAT_WIN, FLAT_STD, JUMP = 4090.0, 50.0, 60, 2.0, 1200.0
N, MIN_N, Z, RESET_BAD = 1800, 200, 3.0, 600

class Ring:
    def __init__(self): self.q=deque(); self.s=0.0; self.ss=0.0
    def push(self,v):
        self.q.append(v); self.s+=v; self.ss+=v*v
        if len(self.q)>N:
            o=self.q.popleft(); self.s-=o; self.ss-=o*o
    def z(self,v):
        n=len(self.q); m=self.s/n; var=max((self.ss-n*m*m)/(n-1),0.0)
        return (v-m)/(var**0.5+1e-6)
    def reset(self): self.q.clear(); self.s=0.0; self.ss=0.0

def gate(x,prev,fq):
    fq.append(x)
    if len(fq)>FLAT_WIN: fq.popleft()
    if x>=RAIL_HI: return "rail_hi"
    if x<=RAIL_LO: return "rail_lo"
    if len(fq)==FLAT_WIN and np.std(fq,ddof=1)<FLAT_STD: return "flat"
    if prev is not None and abs(x-prev)>JUMP: return "jump"
    return "none"

def run(sig):
    g,u=Ring(),Ring(); fq=deque(); prev=None; bad=0
    reasons,dg,du,sg,su=[],[],[],[],[]
    for x in sig:
        r=gate(x,prev,fq); prev=x; good=r=="none"; reasons.append(r)
        bad = 0 if good else bad+1
        if bad==RESET_BAD: g.reset()
        if good:
            if len(g.q)>=MIN_N: dg.append(abs(g.z(x))>Z); sg.append(True)
            else: dg.append(False); sg.append(False)
            g.push(x)
        else: dg.append(False); sg.append(False)
        if len(u.q)>=MIN_N: du.append(abs(u.z(x))>Z); su.append(True)
        else: du.append(False); su.append(False)
        u.push(x)
    return tuple(np.array(a) for a in (reasons,dg,du,sg,su))

def events(dev,min_len=10):
    n=rl=0
    for d in dev:
        rl=rl+1 if d else 0
        if rl==min_len: n+=1
    return n

def rate(dev,sc):
    h=sc.sum()/3600
    return (dev[sc].sum()/h) if h>0 else float("nan")

FAULT_START, FAULT_END = "2026-10-12 22:03", "2026-10-14 17:52"   # real railed front end
CLEAN_START = "2026-10-18 07:30"                                    # clean October recording (Sept excluded)

path = sys.argv[1]
df = pd.read_csv(path, low_memory=False)
df["t"] = pd.to_datetime(df["wall_clock_time"], format="mixed")
df = df.sort_values("t")
fault = df[(df.t>=FAULT_START)&(df.t<=FAULT_END)].bioelectric_raw.to_numpy(float)
clean = df[df.t>=CLEAN_START].bioelectric_raw.to_numpy(float)
L=[f"fault rows={len(fault)} ({len(fault)/3600:.1f} h) clean rows={len(clean)} ({len(clean)/3600:.1f} h)"]

r,dg,du,sg,su=run(clean)
L.append("[B] CLEAN")
L.append(f" rejected {(r!='none').mean()*100:.2f}% reasons={ {k:int(v) for k,v in pd.Series(r[r!='none']).value_counts().items()} }")
L.append(f" dev samples {dg.mean()*100:.2f}%  events gated={events(dg)} ungated={events(du)}")

seq=np.concatenate([fault,clean]); k=len(fault)
r,dg,du,sg,su=run(seq); fr=r[:k]
L.append("[A] FAULT then CLEAN (spliced)")
L.append(f" fault: rejected {(fr!='none').mean()*100:.1f}%  reasons={ {a:int(v) for a,v in pd.Series(fr[fr!='none']).value_counts().items()} }")
bad=fr!="none"
L.append(f" invalid rows={bad.sum()}  ungated treated as normal={int((~du[:k][bad]).sum())} ({(~du[:k][bad]).mean()*100:.1f}%)")
f2=slice(k,k+7200)
L.append(f" first 2h after fault: false alarms gated={dg[f2].sum()} ungated={du[f2].sum()}")
L.append(f" clean part events gated={events(dg[k:])} ungated={events(du[k:])}  rate/h gated={rate(dg[k:],sg[k:]):.2f} ungated={rate(du[k:],su[k:]):.2f}")
idx=np.where(du[k:])[0]; L.append(f" ungated last alarm {idx.max()/3600:.2f} h after" if len(idx) else " ungated none")
idx=np.where(dg[k:])[0]; L.append(f" gated last alarm {idx.max()/3600:.2f} h after" if len(idx) else " gated none")

rng=np.random.default_rng(7); x=clean.copy(); lab=np.zeros(len(x),bool)
for _ in range(6):
    a=rng.integers(4000,len(x)-2500); d=int(rng.integers(300,1200)); x[a:a+d]=4095; lab[a:a+d]=True
for _ in range(12):
    a=rng.integers(4000,len(x)-10); x[a]+=rng.choice([-1,1])*1800; lab[a]=True
for _ in range(4):
    a=rng.integers(4000,len(x)-2500); x[a:a+600]+=400; lab[a:a+600]=True
r,dg,du,sg,su=run(x); c=r!="none"
L.append("[C] INJECTED FAULTS (SIMULATED: 6 rail episodes, 12 spikes, 4 offset steps)")
L.append(f" caught {c[lab].mean()*100:.1f}%  clean wrongly rejected {c[~lab].mean()*100:.2f}%  alarms gated={dg.sum()} ungated={du.sum()}")
L.append(f" memory: ring = {N} floats ({N*4:,} B), constant regardless of run length")

txt="\n".join(L); print(txt)
out=sys.argv[2] if len(sys.argv)>2 else "."
os.makedirs(out,exist_ok=True)
open(os.path.join(out,"replay_eval_summary.txt"),"w").write(txt+"\n")