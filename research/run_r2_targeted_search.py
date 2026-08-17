"""Fast targeted >2R model search. Research only; no execution or ledger writes."""
from __future__ import annotations
import hashlib, json, math, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from statistics import median
from daily_alpha.backtest import fetch_orats_history, indicators

SYMBOLS=[
"AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","AMD","QCOM","TXN","AMAT","KLAC","CRM","NOW","ADBE","ORCL","IBM","CSCO","PANW","CRWD","SNOW","INTC","MUFG","JPM","BAC","WFC","GS","MS","AXP","SCHW","BLK","SPGI","CME","ICE","PNC","USB","COF","BK","TROW","UNH","LLY","PFE","ABBV","TMO","DHR","ISRG","MDT","BMY","AMGN","GILD","CVS","CI","ELV","BSX","ZTS","MCK","CAT","DE","GE","RTX","BA","HON","ETN","PH","EMR","ITW","MMM","UPS","FDX","URI","PWR","XOM","CVX","COP","EOG","SLB","OXY","MPC","KMI","WMB","DVN","FANG","WMT","COST","HD","LOW","TGT","NKE","MCD","SBUX","BKNG","MAR","ABNB","TSLA","GM","F","NFLX","DIS","T","NEE","SO","DUK","AEP","EXC","SRE","AMT","PLD","EQIX","LIN","FCX","NEM","NUE","SHW"]

def bkt(s): return int(hashlib.sha256(s.encode()).hexdigest()[:8],16)%100
SEARCH=[s for s in SYMBOLS if bkt(s)<65]
HOLDOUT=[s for s in SYMBOLS if bkt(s)>=65]
FETCH_START=date(2021,1,1); FETCH_END=date(2026,7,31)
TRAIN=(date(2022,1,1),date(2024,12,31)); VALID=(date(2025,1,1),date(2025,12,31)); STRESS=(date(2026,1,1),date(2026,7,31)); FULL=(date(2022,1,1),date(2025,12,31))

@dataclass(frozen=True)
class Cfg:
    breakout:int=20; eff:float=.20; close_loc:float=0; relvol:float=0
    turtle:int=10; failed_window:int=3; failed_tol:float=0
    harvest:float=3; be:bool=True; trend_flip:bool=True

def hi(b,i,n): return max(x.high for x in b[i-n:i]) if i>=n else None
def lo(b,i,n): return min(x.low for x in b[i-n:i]) if i>=n else None
def fresh(b,i,n):
    u=hi(b,i,n)
    if u is None:return None,False
    p=False
    if i>=n+1:p=b[i-1].close>max(x.high for x in b[i-n-1:i-1])
    return u,b[i].close>u and not p

def run(b,ind,c,start,end):
    qty=0.;avg=0.;eb=None;ei=None;base=None;atr0=None;a1=a2=hv=False;a1i=a2i=None;be=None;cur=None;trs=[]
    for i,(bar,r) in enumerate(zip(b,ind)):
        inside=start<=bar.trade_date<=end; upper,fr=fresh(b,i,c.breakout); l10=lo(b,i,10); lx=lo(b,i,c.turtle)
        atr=float(r['atr']) if r['atr'] is not None else None; adx=float(r['adx']) if r['adx'] is not None else None; eff=float(r['efficiency']) if r['efficiency'] is not None else None; rsi=float(r['rsi']) if r['rsi'] is not None else None
        cl=(bar.close-bar.low)/(bar.high-bar.low) if bar.high>bar.low else .5; rv=float(r.get('relative_volume') or 0)
        adxok=adx is not None and adx>=17 and i>0 and ind[i-1]['adx'] is not None and adx>float(ind[i-1]['adx'])
        mature=i>=2 and int(ind[i-1]['trend_state'])==1 and int(ind[i-2]['trend_state'])==1
        normal=inside and qty==0 and fr and not bool(r['is_earnings_up_gap']) and int(r['trend_state'])==1 and mature and bar.close>=25 and eff is not None and eff>=c.eff and rsi is not None and rsi<=80 and adxok and cl>=c.close_loc and rv>=c.relvol
        gap=inside and qty==0 and bool(r['gap_go']) and bool(r['fresh_breakout']) and bar.close>=25
        ent=normal or gap; sig=float(r['upper20']) if gap and r['upper20'] is not None else upper
        if ent:
            eb=float(sig);ei=i;base=bar.close;atr0=atr;a1=a2=hv=False;a1i=a2i=None;be=None
        bs=i-ei if ei is not None else None
        fail=qty>0 and c.failed_window>0 and eb is not None and bs is not None and 1<=bs<=c.failed_window and atr0 is not None and bar.close<eb-c.failed_tol*atr0
        trendok=int(r['trend_state'])==1 and adx is not None and adx>=17
        add1=qty>0 and not a1 and base is not None and atr0 is not None and trendok and bar.close>=base+atr0
        if add1:a1=True;a1i=i
        add2=qty>0 and a1 and not a2 and a1i is not None and i>a1i and base is not None and atr0 is not None and trendok and bar.close>=base+2*atr0
        if add2:a2=True;a2i=i
        harvest=qty>0 and c.harvest>0 and a2 and not hv and a2i is not None and i>a2i and base is not None and atr0 is not None and bar.close>=base+c.harvest*atr0
        if harvest:hv=True;be=avg if c.be else None
        bx=qty>0 and hv and c.be and be is not None and bar.close<=be
        tx=qty>0 and lx is not None and bar.close<lx
        fx=qty>0 and c.trend_flip and bool(r['bear_flip'])
        ex=inside and (bx or fail or tx or fx); reason='BREAK_EVEN' if bx else 'FAILED_BREAKOUT' if fail else f'TURTLE_{c.turtle}' if tx else 'TREND_FLIP' if fx else ''
        if ent:
            risk=max(bar.close-l10,0) if l10 is not None else None;qty=2.;avg=bar.close;cur={'pnl':0.,'risk':risk,'entry':bar.trade_date.isoformat(),'harvested':False}
        if add1 and cur is not None:
            nq=qty+1;avg=(avg*qty+bar.close)/nq;qty=nq
        if add2 and cur is not None:
            nq=qty+1;avg=(avg*qty+bar.close)/nq;qty=nq
        if harvest and cur is not None:
            cur['pnl']+=bar.close-avg;qty-=1;cur['harvested']=True
        if ex and cur is not None and qty>0:
            cur['pnl']+=(bar.close-avg)*qty; rd=2*cur['risk'] if cur['risk'] and cur['risk']>0 else None;cur['r']=cur['pnl']/rd if rd else None;cur['reason']=reason;trs.append(cur)
            qty=0;avg=0;eb=ei=base=atr0=None;a1=a2=hv=False;a1i=a2i=None;be=None;cur=None
    if cur is not None and qty>0:
        last=max(x for x in b if x.trade_date<=end);cur['pnl']+=(last.close-avg)*qty;rd=2*cur['risk'] if cur['risk'] and cur['risk']>0 else None;cur['r']=cur['pnl']/rd if rd else None;cur['reason']='MARK';trs.append(cur)
    rs=[float(t['r']) for t in trs if t.get('r') is not None and math.isfinite(float(t['r']))];w=[x for x in rs if x>0];l=[-x for x in rs if x<0];wr=len(w)/len(rs) if rs else 0;aw=sum(w)/len(w) if w else 0;al=sum(l)/len(l) if l else 0
    return {'trades':len(rs),'win_rate':wr*100,'avg_win_r':aw,'avg_loss_r':al,'expectancy':wr*aw-(1-wr)*al if rs else 0,'pf':sum(w)/sum(l) if l and sum(l)>0 else None,'best':max(rs) if rs else 0,'worst':min(rs) if rs else 0,'rs':rs}

def comb(ms):
    rs=[x for m in ms for x in m['rs']];w=[x for x in rs if x>0];l=[-x for x in rs if x<0];wr=len(w)/len(rs) if rs else 0;aw=sum(w)/len(w) if w else 0;al=sum(l)/len(l) if l else 0
    return {'trades':len(rs),'win_rate':wr*100,'avg_win_r':aw,'avg_loss_r':al,'expectancy':wr*aw-(1-wr)*al if rs else 0,'pf':sum(w)/sum(l) if l and sum(l)>0 else None,'best':max(rs) if rs else 0,'worst':min(rs) if rs else 0,'rs':rs}
def ev(data,syms,c,p):return comb([run(data[s][0],data[s][1],c,p[0],p[1]) for s in syms])
def fetch(s,t):
    b,_=fetch_orats_history(s,start=FETCH_START,end=FETCH_END,token=t);return s,b,indicators(b)
def clean(m):return {k:v for k,v in m.items() if k!='rs'}

def main():
    t=os.environ['ORATS_TOKEN'];data={};err={}
    with ThreadPoolExecutor(max_workers=4) as p:
        fs={p.submit(fetch,s,t):s for s in SYMBOLS}
        for f in as_completed(fs):
            s=fs[f]
            try:_,b,ind=f.result();data[s]=(b,ind)
            except Exception as e:err[s]=f'{type(e).__name__}:{e}'
    ss=[s for s in SEARCH if s in data];hs=[s for s in HOLDOUT if s in data]
    base=Cfg();bm={"train":ev(data,ss,base,TRAIN),"valid":ev(data,ss,base,VALID),"holdout":ev(data,hs,base,FULL),"stress":ev(data,list(data),base,STRESS)}
    candidates=[]
    for bo in (10,20,30,55):
      for eff in (.20,.25):
       for turtle in (10,20,30,55):
        for fw in (0,1,3):
         for ft in (0,.5):
          for hv,be in ((0,False),(3,True),(4,True),(4,False),(5,True),(5,False)):
           for flip in (True,False):
            c=Cfg(bo,eff,0,0,turtle,fw,ft,hv,be,flip);m=ev(data,ss,c,TRAIN)
            if m['trades']>=120 and m['expectancy']>0 and (m['pf'] or 0)>1:
                score=m['expectancy']+.12*min(m['avg_win_r'],4)+.05*math.log(m['pf'])
                candidates.append((score,c,m))
    candidates.sort(key=lambda x:x[0],reverse=True)
    top=[]
    for score,c,tr in candidates[:40]:
        va=ev(data,ss,c,VALID)
        if va['trades']<25 or va['expectancy']<=0:continue
        # quality overlay search only on survivors
        for cl in (0,.6,.7):
         for rv in (0,1.0,1.25):
          cc=Cfg(c.breakout,c.eff,cl,rv,c.turtle,c.failed_window,c.failed_tol,c.harvest,c.be,c.trend_flip)
          tr2=ev(data,ss,cc,TRAIN);va2=ev(data,ss,cc,VALID)
          if tr2['trades']<100 or va2['trades']<20 or tr2['expectancy']<=0 or va2['expectancy']<=0:continue
          score2=.55*(tr2['expectancy']+.1*min(tr2['avg_win_r'],4))+.45*(va2['expectancy']+.1*min(va2['avg_win_r'],4))
          top.append((score2,cc,tr2,va2))
    top.sort(key=lambda x:x[0],reverse=True)
    finals=[]
    for score,c,tr,va in top[:30]:
        ho=ev(data,hs,c,FULL);st=ev(data,list(data),c,STRESS)
        finals.append({'score':score,'config':asdict(c),'train':clean(tr),'valid':clean(va),'holdout':clean(ho),'stress':clean(st),'holdout_2r':ho['avg_win_r']>=2 and ho['expectancy']>0 and (ho['pf'] or 0)>1,'stress_2r':st['avg_win_r']>=2 and st['expectancy']>0 and (st['pf'] or 0)>1})
    quals=[f for f in finals if f['holdout_2r'] and f['stress']['expectancy']>0]
    quals.sort(key=lambda f:(f['stress_2r'],f['holdout']['expectancy'],f['stress']['expectancy'],f['holdout']['pf'] or 0),reverse=True)
    champ=quals[0] if quals else (finals[0] if finals else None)
    out={'valid':len(data),'errors':err,'search_n':len(ss),'holdout_n':len(hs),'tested':len(candidates),'baseline':{k:clean(v) for k,v in bm.items()},'qualifying':len(quals),'champion':champ,'finalists':finals[:15]}
    Path('r2-targeted.json').write_text(json.dumps(out,indent=2))
    lines=['# Targeted >2R Search',f"valid={len(data)} search={len(ss)} holdout={len(hs)} qualifying={len(quals)}",'','## Baseline']
    for k,v in bm.items():lines.append(f"- {k}: trades={v['trades']} win={v['win_rate']:.1f}% avgWin={v['avg_win_r']:.2f}R avgLoss={v['avg_loss_r']:.2f}R exp={v['expectancy']:+.3f}R PF={(v['pf'] or 0):.2f}")
    if champ:
      lines+=['','## Champion',json.dumps(champ['config'],sort_keys=True)]
      for k in ('train','valid','holdout','stress'):
       v=champ[k];lines.append(f"- {k}: trades={v['trades']} win={v['win_rate']:.1f}% avgWin={v['avg_win_r']:.2f}R avgLoss={v['avg_loss_r']:.2f}R exp={v['expectancy']:+.3f}R PF={(v['pf'] or 0):.2f}")
    lines+=['','## Top finalists']
    for i,f in enumerate(finals[:10],1):
      h=f['holdout'];s=f['stress'];lines.append(f"{i}. holdout {h['avg_win_r']:.2f}R/{h['expectancy']:+.3f}R/PF{(h['pf'] or 0):.2f}; 2026 {s['avg_win_r']:.2f}R/{s['expectancy']:+.3f}R/PF{(s['pf'] or 0):.2f}; {json.dumps(f['config'],sort_keys=True)}")
    Path('r2-targeted.md').write_text('\n'.join(lines)+'\n');print(Path('r2-targeted.md').read_text())
if __name__=='__main__':main()
