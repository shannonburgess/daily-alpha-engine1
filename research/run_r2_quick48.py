from __future__ import annotations
import hashlib,json,math,os
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass,asdict
from datetime import date
from pathlib import Path
from daily_alpha.backtest import fetch_orats_history,indicators
SYMS=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","AMD","QCOM","TXN","AMAT","KLAC","CRM","NOW","ORCL","IBM","CSCO","PANW","JPM","BAC","WFC","GS","MS","AXP","SCHW","UNH","LLY","ABBV","TMO","DHR","ISRG","AMGN","CAT","DE","GE","RTX","HON","ETN","EMR","PWR","XOM","CVX","COP","EOG","SLB","MPC","WMT","COST","HD","LOW","MCD","BKNG","TSLA","NFLX","NEE","AMT","PLD","EQIX","LIN","FCX"]
def buck(s):return int(hashlib.sha1(s.encode()).hexdigest()[:6],16)%100
S=[x for x in SYMS if buck(x)<62];H=[x for x in SYMS if buck(x)>=62]
FS=date(2021,1,1);FE=date(2026,7,31);TR=(date(2022,1,1),date(2024,12,31));VA=(date(2025,1,1),date(2025,12,31));FU=(date(2022,1,1),date(2025,12,31));ST=(date(2026,1,1),date(2026,7,31))
@dataclass(frozen=True)
class C: bo:int=20;turtle:int=10;fw:int=3;harvest:float=3;be:bool=True;flip:bool=True

def hi(b,i,n):return max(x.high for x in b[i-n:i]) if i>=n else None
def lo(b,i,n):return min(x.low for x in b[i-n:i]) if i>=n else None
def fresh(b,i,n):
 u=hi(b,i,n)
 if u is None:return None,False
 prev=i>=n+1 and b[i-1].close>max(x.high for x in b[i-n-1:i-1])
 return u,b[i].close>u and not prev

def run(b,ind,c,p):
 q=0.;av=0.;eb=None;ei=None;base=None;a0=None;a1=a2=hv=False;a1i=a2i=None;bev=None;cur=None;rs=[]
 for i,(bar,r) in enumerate(zip(b,ind)):
  inside=p[0]<=bar.trade_date<=p[1];u,fr=fresh(b,i,c.bo);l10=lo(b,i,10);lx=lo(b,i,c.turtle);atr=float(r['atr']) if r['atr'] is not None else None;adx=float(r['adx']) if r['adx'] is not None else None;eff=float(r['efficiency']) if r['efficiency'] is not None else None;rsi=float(r['rsi']) if r['rsi'] is not None else None
  adxok=adx is not None and adx>=17 and i>0 and ind[i-1]['adx'] is not None and adx>float(ind[i-1]['adx']);mat=i>=2 and int(ind[i-1]['trend_state'])==1 and int(ind[i-2]['trend_state'])==1
  normal=inside and q==0 and fr and not bool(r['is_earnings_up_gap']) and int(r['trend_state'])==1 and mat and bar.close>=25 and eff is not None and eff>=.20 and rsi is not None and rsi<=80 and adxok
  gap=inside and q==0 and bool(r['gap_go']) and bool(r['fresh_breakout']) and bar.close>=25;ent=normal or gap;sig=float(r['upper20']) if gap and r['upper20'] is not None else u
  if ent:eb=float(sig);ei=i;base=bar.close;a0=atr;a1=a2=hv=False;a1i=a2i=None;bev=None
  bs=i-ei if ei is not None else None;fail=q>0 and c.fw>0 and eb is not None and bs is not None and 1<=bs<=c.fw and bar.close<eb
  tok=int(r['trend_state'])==1 and adx is not None and adx>=17;ad1=q>0 and not a1 and base is not None and a0 is not None and tok and bar.close>=base+a0
  if ad1:a1=True;a1i=i
  ad2=q>0 and a1 and not a2 and a1i is not None and i>a1i and base is not None and a0 is not None and tok and bar.close>=base+2*a0
  if ad2:a2=True;a2i=i
  har=q>0 and c.harvest>0 and a2 and not hv and a2i is not None and i>a2i and base is not None and a0 is not None and bar.close>=base+c.harvest*a0
  if har:hv=True;bev=av if c.be else None
  bx=q>0 and c.be and hv and bev is not None and bar.close<=bev;tx=q>0 and lx is not None and bar.close<lx;fx=q>0 and c.flip and bool(r['bear_flip']);ex=inside and(fail or bx or tx or fx)
  if ent:q=2.;av=bar.close;cur={'p':0.,'risk':max(bar.close-l10,0) if l10 is not None else None}
  if ad1 and cur is not None:nq=q+1;av=(av*q+bar.close)/nq;q=nq
  if ad2 and cur is not None:nq=q+1;av=(av*q+bar.close)/nq;q=nq
  if har and cur is not None:cur['p']+=bar.close-av;q-=1
  if ex and cur is not None and q>0:
   cur['p']+=(bar.close-av)*q;rd=2*cur['risk'] if cur['risk'] and cur['risk']>0 else None
   if rd:rs.append(cur['p']/rd)
   q=0;av=0;eb=ei=base=a0=None;a1=a2=hv=False;a1i=a2i=None;bev=None;cur=None
 if cur is not None and q>0:
  last=max((x for x in b if x.trade_date<=p[1]),key=lambda x:x.trade_date);cur['p']+=(last.close-av)*q;rd=2*cur['risk'] if cur['risk'] and cur['risk']>0 else None
  if rd:rs.append(cur['p']/rd)
 return rs

def met(rs):
 w=[x for x in rs if x>0];l=[-x for x in rs if x<0];wr=len(w)/len(rs) if rs else 0;aw=sum(w)/len(w) if w else 0;al=sum(l)/len(l) if l else 0
 return {'trades':len(rs),'win':wr*100,'avgw':aw,'avgl':al,'exp':wr*aw-(1-wr)*al if rs else 0,'pf':sum(w)/sum(l) if l and sum(l)>0 else None,'best':max(rs) if rs else 0,'worst':min(rs) if rs else 0}
def ev(d,sy,c,p):return met([r for s in sy for r in run(d[s][0],d[s][1],c,p)])
def fet(s,t):b,_=fetch_orats_history(s,start=FS,end=FE,token=t);return s,b,indicators(b)
def main():
 t=os.environ['ORATS_TOKEN'];d={}
 with ThreadPoolExecutor(max_workers=5) as pool:
  fs={pool.submit(fet,s,t):s for s in SYMS}
  for f in as_completed(fs):
   try:s,b,i=f.result();d[s]=(b,i)
   except Exception:pass
 ss=[x for x in S if x in d];hh=[x for x in H if x in d];base=C();bm={k:ev(d,sy,base,p) for k,sy,p in [('tr',ss,TR),('va',ss,VA),('ho',hh,FU),('st',list(d),ST)]}
 arr=[]
 for bo in (20,30,55):
  for tu in (30,55):
   for fw in (0,1,3):
    for hv,be in ((0,False),(5,False),(5,True)):
     for fl in (True,False):
      c=C(bo,tu,fw,hv,be,fl);tr=ev(d,ss,c,TR)
      if tr['trades']>=60 and tr['exp']>0 and (tr['pf'] or 0)>1:
       va=ev(d,ss,c,VA)
       if va['trades']>=12 and va['exp']>0:
        ho=ev(d,hh,c,FU);st=ev(d,list(d),c,ST);arr.append({'c':asdict(c),'tr':tr,'va':va,'ho':ho,'st':st,'q':ho['avgw']>=2 and ho['exp']>0 and (ho['pf'] or 0)>1})
 arr.sort(key=lambda x:(x['q'],x['ho']['avgw']>=2,x['ho']['exp'],x['st']['exp']),reverse=True);qs=[x for x in arr if x['q'] and x['st']['exp']>0];champ=qs[0] if qs else(arr[0] if arr else None);res={'n':len(d),'search':len(ss),'holdout':len(hh),'baseline':bm,'qualifying':len(qs),'champion':champ,'models':arr[:15]};Path('r2-quick48.json').write_text(json.dumps(res,indent=2));print(json.dumps(res,indent=2))
if __name__=='__main__':main()
