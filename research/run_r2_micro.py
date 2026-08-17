from __future__ import annotations
import hashlib,json,math,os
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass,asdict
from datetime import date
from pathlib import Path
from daily_alpha.backtest import fetch_orats_history,indicators
SYMS=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","AMD","QCOM","TXN","AMAT","KLAC","CRM","NOW","ADBE","ORCL","IBM","CSCO","PANW","CRWD","JPM","BAC","WFC","GS","MS","AXP","SCHW","BLK","SPGI","UNH","LLY","PFE","ABBV","TMO","DHR","ISRG","AMGN","GILD","CAT","DE","GE","RTX","BA","HON","ETN","PH","EMR","PWR","XOM","CVX","COP","EOG","SLB","MPC","WMT","COST","HD","LOW","MCD","SBUX","BKNG","TSLA","NFLX","DIS","NEE","AMT","PLD","EQIX","LIN","FCX","NEM"]
def buck(s):return int(hashlib.md5(s.encode()).hexdigest()[:6],16)%100
S=[x for x in SYMS if buck(x)<65];H=[x for x in SYMS if buck(x)>=65]
FS=date(2021,1,1);FE=date(2026,7,31);TR=(date(2022,1,1),date(2024,12,31));VA=(date(2025,1,1),date(2025,12,31));ST=(date(2026,1,1),date(2026,7,31));FU=(date(2022,1,1),date(2025,12,31))
@dataclass(frozen=True)
class C: bo:int;eff:float;turtle:int;fw:int;hv:float;flip:bool

def hi(b,i,n):return max(x.high for x in b[i-n:i]) if i>=n else None
def lo(b,i,n):return min(x.low for x in b[i-n:i]) if i>=n else None
def fr(b,i,n):
 u=hi(b,i,n)
 if u is None:return None,False
 p=i>=n+1 and b[i-1].close>max(x.high for x in b[i-n-1:i-1])
 return u,b[i].close>u and not p

def run(b,ind,c,p):
 q=0.;av=0.;eb=None;ei=None;base=None;a0=None;a1=a2=hv=False;a1i=a2i=None;cur=None;rs=[]
 for i,(bar,r) in enumerate(zip(b,ind)):
  inside=p[0]<=bar.trade_date<=p[1];u,f=fr(b,i,c.bo);l10=lo(b,i,10);lx=lo(b,i,c.turtle);atr=float(r['atr']) if r['atr'] is not None else None;adx=float(r['adx']) if r['adx'] is not None else None;eff=float(r['efficiency']) if r['efficiency'] is not None else None;rsi=float(r['rsi']) if r['rsi'] is not None else None
  adxok=adx is not None and adx>=17 and i>0 and ind[i-1]['adx'] is not None and adx>float(ind[i-1]['adx']);mat=i>=2 and int(ind[i-1]['trend_state'])==1 and int(ind[i-2]['trend_state'])==1
  normal=inside and q==0 and f and not bool(r['is_earnings_up_gap']) and int(r['trend_state'])==1 and mat and bar.close>=25 and eff is not None and eff>=c.eff and rsi is not None and rsi<=80 and adxok
  gap=inside and q==0 and bool(r['gap_go']) and bool(r['fresh_breakout']) and bar.close>=25;ent=normal or gap;sig=float(r['upper20']) if gap and r['upper20'] is not None else u
  if ent:eb=float(sig);ei=i;base=bar.close;a0=atr;a1=a2=hv=False;a1i=a2i=None
  bs=i-ei if ei is not None else None;fail=q>0 and c.fw>0 and eb is not None and bs is not None and 1<=bs<=c.fw and bar.close<eb
  tok=int(r['trend_state'])==1 and adx is not None and adx>=17;ad1=q>0 and not a1 and base is not None and a0 is not None and tok and bar.close>=base+a0
  if ad1:a1=True;a1i=i
  ad2=q>0 and a1 and not a2 and a1i is not None and i>a1i and base is not None and a0 is not None and tok and bar.close>=base+2*a0
  if ad2:a2=True;a2i=i
  har=q>0 and c.hv>0 and a2 and not hv and a2i is not None and i>a2i and base is not None and a0 is not None and bar.close>=base+c.hv*a0
  if har:hv=True
  tx=q>0 and lx is not None and bar.close<lx;fx=q>0 and c.flip and bool(r['bear_flip']);ex=inside and(fail or tx or fx)
  if ent:q=2.;av=bar.close;cur={'pnl':0.,'risk':max(bar.close-l10,0) if l10 is not None else None}
  if ad1 and cur is not None:nq=q+1;av=(av*q+bar.close)/nq;q=nq
  if ad2 and cur is not None:nq=q+1;av=(av*q+bar.close)/nq;q=nq
  if har and cur is not None:cur['pnl']+=bar.close-av;q-=1
  if ex and cur is not None and q>0:
   cur['pnl']+=(bar.close-av)*q;rd=2*cur['risk'] if cur['risk'] and cur['risk']>0 else None
   if rd:rs.append(cur['pnl']/rd)
   q=0;av=0;eb=ei=base=a0=None;a1=a2=hv=False;a1i=a2i=None;cur=None
 if cur is not None and q>0:
  last=max((x for x in b if x.trade_date<=p[1]),key=lambda x:x.trade_date);cur['pnl']+=(last.close-av)*q;rd=2*cur['risk'] if cur['risk'] and cur['risk']>0 else None
  if rd:rs.append(cur['pnl']/rd)
 return rs

def met(rs):
 w=[x for x in rs if x>0];l=[-x for x in rs if x<0];wr=len(w)/len(rs) if rs else 0;aw=sum(w)/len(w) if w else 0;al=sum(l)/len(l) if l else 0
 return {'trades':len(rs),'win':wr*100,'avgw':aw,'avgl':al,'exp':wr*aw-(1-wr)*al if rs else 0,'pf':sum(w)/sum(l) if l and sum(l)>0 else None,'best':max(rs) if rs else 0,'worst':min(rs) if rs else 0}
def ev(d,sy,c,p):return met([r for s in sy for r in run(d[s][0],d[s][1],c,p)])
def fet(s,t):
 b,_=fetch_orats_history(s,start=FS,end=FE,token=t);return s,b,indicators(b)
def main():
 t=os.environ['ORATS_TOKEN'];d={}
 with ThreadPoolExecutor(max_workers=4) as pool:
  fs={pool.submit(fet,s,t):s for s in SYMS}
  for f in as_completed(fs):
   try:s,b,i=f.result();d[s]=(b,i)
   except Exception:pass
 ss=[x for x in S if x in d];hh=[x for x in H if x in d]
 base=C(20,.2,10,3,3,True);bm={k:ev(d,sy,base,p) for k,sy,p in [('train',ss,TR),('valid',ss,VA),('holdout',hh,FU),('stress',list(d),ST)]}
 ar=[]
 for bo in (20,30,55):
  for ef in (.2,.25):
   for tu in (20,30,55):
    for fw in (0,1,3):
     for hv in (0,5):
      for fl in (True,False):
       c=C(bo,ef,tu,fw,hv,fl);m=ev(d,ss,c,TR)
       if m['trades']>=80 and m['exp']>0 and (m['pf'] or 0)>1:ar.append((m['exp']+.1*min(m['avgw'],4),c,m))
 ar.sort(key=lambda x:x[0],reverse=True);out=[]
 for sc,c,tr in ar[:25]:
  va=ev(d,ss,c,VA)
  if va['trades']<15 or va['exp']<=0:continue
  ho=ev(d,hh,c,FU);st=ev(d,list(d),c,ST);out.append({'c':asdict(c),'tr':tr,'va':va,'ho':ho,'st':st,'q':ho['avgw']>=2 and ho['exp']>0 and (ho['pf'] or 0)>1})
 qs=[x for x in out if x['q'] and x['st']['exp']>0];qs.sort(key=lambda x:(x['st']['avgw']>=2,x['ho']['exp'],x['st']['exp']),reverse=True);champ=qs[0] if qs else(out[0] if out else None)
 res={'n':len(d),'search':len(ss),'holdout':len(hh),'baseline':bm,'qualifying':len(qs),'champion':champ,'top':out[:10]};Path('r2-micro.json').write_text(json.dumps(res,indent=2));print(json.dumps(res,indent=2))
if __name__=='__main__':main()
