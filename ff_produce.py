import os,re,json,pickle,io,urllib.request,datetime
src=open('ff_build2.py').read().split("DTR=build([2021,2022,2023,2024])")[0]; exec(src)
from sklearn.linear_model import HuberRegressor
B='https://github.com/nflverse/nflverse-data/releases/download/'
def get(rel):
    with urllib.request.urlopen(B+rel,timeout=180) as r_: return pd.read_parquet(io.BytesIO(r_.read()))
if os.path.exists('DTR.parquet'): DTR=pd.read_parquet('DTR.parquet'); D25=pd.read_parquet('D25.parquet')
else: DTR=build([2021,2022,2023,2024]); D25=build([2025]); DTR.to_parquet('DTR.parquet'); D25.to_parquet('D25.parquet')
for _d in (DTR,D25):
    for _c in ('bump','qbm','vac_all'):
        if _c not in _d.columns: _d[_c]=0.0
POSAVG={p:float(DTR[DTR.pos==p].y.mean()) for p in POS}
def prep(d):
    d=d.copy(); pa=d.pos.map(POSAVG); pv=d.prev.fillna(pa)
    d['b']=np.where(d.g>0,(d.ppg.fillna(0)*d.g+pv*3)/(d.g+3),pv); d['bx']=np.where(d.g>0,(d.xpg.fillna(0)*d.g+pv*3)/(d.g+3),pv)
    d['l3f']=d.l3.fillna(d.b); d['dv']=d.dvp.fillna(1.0)-1; d['iv']=d.it.fillna(22.5)/22.5-1; d['bd']=d.b*d.dv; d['bi']=d.b*d.iv
    for c in ('bump','qbm','vac_all'):
        d[c]=d[c].fillna(0.0) if c in d.columns else 0.0
    d['bq']=d.b*d.qbm; return d
# situation-aware: vacated opportunity from injured teammates, and games without the starting QB (tested on 2025: better at every position)
L=['b','bx','l3f','bd','bi','bump','bq']; FT=F+['b','bx','bump','qbm','vac_all']
# quarterbacks use only the 'starting QB is out' signal (receiver injuries pushed QB projections the wrong way)
FEAT=lambda pos:(['b','bx','l3f','bd','bi','bq'],F+['b','bx','qbm']) if pos=='QB' else (L,FT)
mk_lin=lambda:HuberRegressor(max_iter=500,epsilon=1.6); mk_tree=lambda:HGBR(max_iter=250,learning_rate=.04,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.0,random_state=0)
res={}; CH={}; RNG={}; QS={}
for pos in POS:
    a=prep(DTR[DTR.pos==pos]); t=prep(D25[D25.pos==pos])
    LL,FF=FEAT(pos); pl=mk_lin().fit(a[LL],a.y).predict(t[LL]); pt=mk_tree().fit(a[FF],a.y).predict(t[FF]); pe=(pl+pt)/2
    def sp(pred): return float(np.nanmean([spearmanr(x.pp,x.y).correlation for w,x in t.assign(pp=pred).groupby('week') if len(x)>8]))
    cand={'blend':t.b.values,'linear':pl,'tree':pt,'ensemble':pe}; sc={k:(float(np.mean(np.abs(v-t.y))),sp(v)) for k,v in cand.items()}
    best=min(['linear','tree','ensemble'],key=lambda k:sc[k][0]-2*sc[k][1])   # favor ranking accuracy (start/sit) as well as error
    CH[pos]=best; res[pos]={'n':int(len(t)),'mae_base':r(sc['blend'][0]),'rank_base':r(sc['blend'][1],3),'mae':r(sc[best][0]),'rank':r(sc[best][1],3),'model':best}
    q=t.assign(pp=cand[best]); q=q[q.pp>=5]; ratio=q.y/q.pp; RNG[pos]=[r(ratio.quantile(.1)),r(ratio.quantile(.9))]
    # full outcome spread (5th..95th percentile of actual / projected), by projection level, for boom and bust chances
    QS.setdefault(pos,{})
    for lo,hi in ((5,10),(10,15),(15,99)):
        qq=t.assign(pp=cand[best]); qq=qq[(qq.pp>=lo)&(qq.pp<hi)]; rt=qq.y/qq.pp
        QS[pos][str(lo)]=[r(rt.quantile(k/20),3) for k in range(1,20)] if len(rt)>=60 else None
    print(pos,{k:(round(v[0],2),round(v[1],3)) for k,v in sc.items()},'->',best,flush=True)
DA=prep(pd.concat([DTR,D25])); FIN={}
for pos in POS:
    a=DA[DA.pos==pos]; LL,FF=FEAT(pos); FIN[pos]=(mk_lin().fit(a[LL],a.y),mk_tree().fit(a[FF],a.y))
def predict(pos,d):
    lin,tree=FIN[pos]; d=prep(d); pl=lin.predict(d[FEAT(pos)[0]]); pt=tree.predict(d[FEAT(pos)[1]])
    return np.maximum(0,{'linear':pl,'tree':pt,'ensemble':(pl+pt)/2}[CH[pos]])
# ---------------- 2026 state
S26=st[st.season==SEASON]; LAST=int(S26.week.max())
wr=get(f'weekly_rosters/roster_weekly_{SEASON}.parquet'); wr=wr.dropna(subset=['gsis_id']).sort_values('week'); cur=wr.groupby('gsis_id').tail(1).set_index('gsis_id')
dc=get(f'depth_charts/depth_charts_{SEASON}.parquet'); dc=dc[dc.dt==dc.dt.max()]
inj=get(f'injuries/injuries_{SEASON}.parquet'); inj=inj[inj.report_status.isin(['Out','Doubtful','Questionable'])]; inj=inj[inj.week==inj.groupby('team').week.transform('max')]
injs=inj.drop_duplicates('gsis_id',keep='last').set_index('gsis_id')
injall=get(f'injuries/injuries_{SEASON}.parquet'); injall=injall[injall.week==injall.groupby('team').week.transform('max')]
def short_prac(v):
    v=str(v or ''); return 'DNP' if 'Did Not' in v else 'Limited' if 'Limited' in v else 'Full' if 'Full' in v else None
PRAC={r.gsis_id:short_prac(r.practice_status) for r in injall.itertuples() if short_prac(r.practice_status)}
P26=pd.read_parquet(f'pbp_{SEASON}.parquet',columns=['week','posteam','play_type','qb_kneel','qb_spike','epa']); P26=P26[P26.play_type.isin(['pass','run'])&(P26.qb_kneel!=1)&(P26.qb_spike!=1)]
TV=P26.groupby(['posteam','week']).agg(pl=('epa','size'),pr=('play_type',lambda x:(x=='pass').mean())).groupby('posteam').mean()
RMAP={'QB':'QB','RB':'RB','HB':'RB','FB':'RB','WR':'WR','LWR':'WR','RWR':'WR','SWR':'WR','TE':'TE'}
dc2=dc[dc.pos_abb.isin(RMAP)].copy(); dc2['pg']=dc2.pos_abb.map(RMAP); role=dc2.sort_values('pos_rank').drop_duplicates('gsis_id').set_index('gsis_id')
# pool: anyone with 2026 fantasy activity at QB/RB/WR/TE, plus depth-chart starters/backups
pool={x for x in set(S26.player_id)|set(dc2[dc2.pos_rank<=(3)].gsis_id) if isinstance(x,str) and x}
info=st.sort_values(['season','week']).groupby('player_id').tail(1).set_index('player_id')
idx=ids.dropna(subset=['gsis_id']).drop_duplicates('gsis_id').set_index('gsis_id')
dv=pd.read_csv('values.csv'); dvm=dv.set_index('fp_id').value_1qb.to_dict(); dvm2=dv.set_index('fp_id').value_2qb.to_dict() if 'value_2qb' in dv.columns else {}
SC26=SC[SC.season==SEASON]; import sys
if SC26.pts.isna().sum()==0: print('Regular season complete: no unplayed games, keeping the current page.'); sys.exit(0)
NEXT=int(SC26[SC26.pts.isna()].week.min()); byes={}   # current NFL week = earliest week with an unplayed game
for t in SC26.team.unique():
    wk=set(SC26[SC26.team==t].week); byes[t]=[w for w in range(1,19) if w not in wk]
def team_of(pid):
    if pid in cur.index and cur.loc[pid,'status'] in ('ACT','RES','INA','DEV'): return cur.loc[pid,'team'],cur.loc[pid,'status']
    if pid in role.index: return role.loc[pid,'team'],'ACT'
    return (info.loc[pid,'team'] if pid in info.index else None),None
players=[]; prev_pg=prev
# ---- teammates expected to miss games: Out/Doubtful on the latest injury report for the next game; injured reserve for every remaining week
OUTN=set(injs[injs.report_status.isin(['Out','Doubtful'])].index) if len(injs) else set()
IRS=set(cur[cur.status=='RES'].index)
SIT={}
for tm_,G_ in S26.groupby('team'):
    wks_=sorted(G_.week.unique())[-3:]; rec_=G_[G_.week.isin(wks_)].groupby('player_id').agg(xpg=('xfp','mean'),gp=('week','nunique'),pos=('position','first'),att=('attempts','sum'),name=('player_display_name','first'))
    rec_=rec_[rec_.gp>=min(2,len(wks_))]
    def _sit(outset,rec=rec_):
        miss=rec[rec.index.isin(outset)]; pres=rec[~rec.index.isin(outset)]; qb=rec[rec.pos=='QB'].sort_values('att',ascending=False)
        qbm=int(len(qb)>0 and qb.index[0] in outset and qb.att.iloc[0]>=40)
        return dict(pres=pres,vr=float(miss[(miss.pos=='RB')&(miss.xpg>=4)].xpg.sum()),vw=float(miss[miss.pos.isin(['WR','TE'])&(miss.xpg>=4)].xpg.sum()),qbm=qbm,
                    names=[n for n,x in zip(miss.name,miss.xpg) if x>=4],qbname=(qb.name.iloc[0] if qbm else None))
    SIT[tm_]={'next':_sit(OUTN|IRS),'later':_sit(IRS)}
def sit_feats(pid,pos,tm,which):
    s_=(SIT.get(tm) or {}).get(which)
    if not s_: return 0.0,0,0.0
    pres=s_['pres']
    if pid not in pres.index: return 0.0,s_['qbm'],s_['vr']+s_['vw']
    grp=['RB'] if pos=='RB' else ['WR','TE'] if pos in ('WR','TE') else []
    vac=s_['vr'] if pos=='RB' else s_['vw'] if pos in ('WR','TE') else 0.0
    tot=float(pres[pres.pos.isin(grp)].xpg.sum()) if grp else 0.0
    return (vac*float(pres.loc[pid,'xpg'])/tot if tot>0 else 0.0),s_['qbm'],s_['vr']+s_['vw']
for pid in pool:
    tm,status=team_of(pid)
    if tm is None: continue
    pos=(info.loc[pid,'position'] if pid in info.index else (role.loc[pid,'pg'] if pid in role.index else None))
    if pos not in POS: continue
    name=(info.loc[pid,'player_display_name'] if pid in info.index else role.loc[pid,'player_name'])
    if (not isinstance(name,str) or not name.strip()) and pid in cur.index: name=cur.loc[pid,'full_name']
    if not isinstance(name,str) or not name.strip(): continue
    rows=S26[S26.player_id==pid].sort_values('week')
    base=feats(SEASON,99,rows,None); pv=prev_pg.get((pid,SEASON),np.nan)
    sched=SC26[(SC26.team==tm)&SC26.pts.isna()].sort_values('week')   # this team's unplayed games
    wk_rows=[]
    for gi_,g in enumerate(sched.itertuples()):
        bmp_,qm_,va_=sit_feats(pid,pos,tm,'next' if gi_==0 else 'later')
        f=dict(base); f.update(pos=pos,prev=pv,dvp=dvp_factor(SEASON,99,g.opp,pos),it=g.it,home=g.home,bump=bmp_,qbm=qm_,vac_all=va_); wk_rows.append((g.week,g.opp,g.home,g.it,f))
    if not wk_rows: continue
    FR=pd.DataFrame([w[4] for w in wk_rows]); P=predict(pos,FR)
    Pm=predict(pos,FR.iloc[:1].assign(dvp=np.nan))[0]; Pv=predict(pos,FR.iloc[:1].assign(it=np.nan))[0]; Pt=predict(pos,FR.iloc[:1].assign(bump=0.0,qbm=0,vac_all=0.0))[0]
    out=injs.loc[pid,'report_status'] if pid in injs.index else None; ir=status=='RES'
    nxt=wk_rows[0]; proj_next=float(P[0])
    if out=='Out' or ir: proj_next=0.0
    rec_pg=float(rows.receptions.mean()) if len(rows) else float(st[(st.player_id==pid)&(st.season==SEASON-1)].receptions.mean() or 0)
    ros=[[int(w[0]),w[1],r(P[i],1)] for i,w in enumerate(wk_rows) if w[0]<=17]
    rl=role.loc[pid] if pid in role.index else None
    players.append({'id':pid,'n':name,'p':pos,'t':tm,'age':r(idx.loc[pid,'age'],1) if pid in idx.index and 'age' in idx.columns else None,
      'role':f"{rl['pg']}{int(rl['pos_rank'])}" if rl is not None and rl['team']==tm else None,'inj':('IR' if ir else out),
      'num':int(cur.loc[pid,'jersey_number']) if pid in cur.index and pd.notna(cur.loc[pid,'jersey_number']) else None,'g':int(len(rows)),'fp':r(rows.fp.sum(),1),'fpg':r(rows.fp.mean(),1) if len(rows) else None,'xfpg':r(rows.xfp.mean(),1) if len(rows) else None,
      'snap':r(rows.offense_pct.mean(),3) if len(rows) and rows.offense_pct.notna().any() else None,'ts':r(rows.target_share.mean(),3) if len(rows) else None,
      'ays':r(rows.air_yards_share.mean(),3) if len(rows) else None,'wopr':r(rows.wopr.mean(),3) if len(rows) else None,'tpg':r(rows.targets.mean(),1) if len(rows) else None,
      'cpg':r(rows.carries.mean(),1) if len(rows) else None,'cs':r(rows.car_share.mean(),3) if len(rows) else None,'rz':r(rows.rzo.mean(),1) if len(rows) else None,
      'rpg':r(rec_pg,2),'prev':r(pv,1),
      'wk':[[int(x.week),r(x.fp,1),r(x.xfp,1),r(x.offense_pct,2),int(x.targets),int(x.carries),x.opponent_team] for x in rows.itertuples()],
      'proj':r(proj_next,1),'nw':int(nxt[0]),'opp':nxt[1],'home':int(nxt[2]),'it':r(nxt[3],1),
      'dvp':r(nxt[4]['dvp'],3),'adjm':r(P[0]-Pm,1),'adjv':r(P[0]-Pv,1),'adjt':(0.0 if (out=='Out' or ir) else r(P[0]-Pt,1)),'tmo':[n for n in (SIT.get(tm,{}).get('next',{}).get('names') or []) if n!=name][:4],'qbo':(lambda q:q if q and q!=name else None)(SIT.get(tm,{}).get('next',{}).get('qbname')),'prac':PRAC.get(pid),'tpl':r(TV.pl.get(tm,np.nan),1),'tpr':r(TV.pr.get(tm,np.nan),3),'ros':ros,'bye':byes.get(tm,[None])[0],
      'sid':str(int(idx.loc[pid,'sleeper_id'])) if pid in idx.index and pd.notna(idx.loc[pid,'sleeper_id']) else None,
      'eid':str(int(idx.loc[pid,'espn_id'])) if pid in idx.index and pd.notna(idx.loc[pid,'espn_id']) else None,
      'yid':str(int(idx.loc[pid,'yahoo_id'])) if pid in idx.index and pd.notna(idx.loc[pid,'yahoo_id']) else None,
      'dv':int(dvm[idx.loc[pid,'fantasypros_id']]) if pid in idx.index and idx.loc[pid,'fantasypros_id'] in dvm else None,
      'dv2':int(dvm2[idx.loc[pid,'fantasypros_id']]) if pid in idx.index and idx.loc[pid,'fantasypros_id'] in dvm2 and dvm2[idx.loc[pid,'fantasypros_id']]==dvm2[idx.loc[pid,'fantasypros_id']] else None})
players.sort(key=lambda p:-(p['proj'] or 0))
# defense vs position, 2026 to date (PPR points allowed per game) with ranks (1 = allows the fewest)
a26,lg26=dvp_table(SEASON,99); DVP={}
for t in sorted(SC26.team.unique()):
    DVP[t]={}
    for pos in POS:
        if (t,pos) in a26.index: sm,c=a26.loc[(t,pos)]; DVP[t][pos]=[r(sm/c,1),int(c),r(dvp_factor(SEASON,99,t,pos),3)]
for pos in POS:
    order=sorted([t for t in DVP if pos in DVP[t]],key=lambda t:DVP[t][pos][0])
    for k,t in enumerate(order): DVP[t][pos].append(k+1)
from zoneinfo import ZoneInfo
def _i(v):
    try: return 0 if v is None or (isinstance(v,float) and np.isnan(v)) else int(v)
    except Exception: return 0
def box_from_stats(rows):
    """Official-style box score for a finished game, built from nflverse player stats."""
    players=[];cats={};ts={}
    for t,R in rows.groupby('team'):
        P_=[x for x in R.itertuples() if (_i(x.attempts) or _i(x.carries) or _i(x.targets))]
        for x in P_:
            players.append({'n':x.player_display_name,'t':t,'p':x.position,'pc':_i(x.completions),'pa':_i(x.attempts),'py':_i(x.passing_yards),'ptd':_i(x.passing_tds),'int':_i(x.passing_interceptions),
              'ra':_i(x.carries),'ry':_i(x.rushing_yards),'rtd':_i(x.rushing_tds),'rec':_i(x.receptions),'tg':_i(x.targets),'ty':_i(x.receiving_yards),'rectd':_i(x.receiving_tds),
              'fl':_i(getattr(x,'rushing_fumbles_lost',0))+_i(getattr(x,'receiving_fumbles_lost',0))+_i(getattr(x,'sack_fumbles_lost',0))})
        C=[]
        pa=[x for x in P_ if _i(x.attempts)]
        if pa: C.append({'n':'passing','t':f'{t} Passing','l':['C/ATT','YDS','TD','INT','SACKS'],'r':[[x.player_display_name,f"{_i(x.completions)}/{_i(x.attempts)}",str(_i(x.passing_yards)),str(_i(x.passing_tds)),str(_i(x.passing_interceptions)),f"{_i(getattr(x,'sacks_suffered',0))}-{_i(getattr(x,'sack_yards_lost',0))}"] for x in pa],'tot':[]})
        ru=sorted([x for x in P_ if _i(x.carries)],key=lambda x:-_i(x.rushing_yards))
        if ru: C.append({'n':'rushing','t':f'{t} Rushing','l':['CAR','YDS','AVG','TD'],'r':[[x.player_display_name,str(_i(x.carries)),str(_i(x.rushing_yards)),f"{_i(x.rushing_yards)/max(1,_i(x.carries)):.1f}",str(_i(x.rushing_tds))] for x in ru],'tot':[]})
        rc=sorted([x for x in P_ if _i(x.targets)],key=lambda x:-_i(x.receiving_yards))
        if rc: C.append({'n':'receiving','t':f'{t} Receiving','l':['REC','TGTS','YDS','AVG','TD'],'r':[[x.player_display_name,str(_i(x.receptions)),str(_i(x.targets)),str(_i(x.receiving_yards)),f"{_i(x.receiving_yards)/max(1,_i(x.receptions)):.1f}",str(_i(x.receiving_tds))] for x in rc],'tot':[]})
        fu=[p for p in players if p['t']==t and p['fl']]
        if fu: C.append({'n':'fumbles','t':f'{t} Fumbles lost','l':['LOST'],'r':[[p['n'],str(p['fl'])] for p in fu],'tot':[]})
        cats[t]=C
        py=sum(_i(x.passing_yards) for x in pa); ry=sum(_i(x.rushing_yards) for x in ru); to=sum(_i(x.passing_interceptions) for x in pa)+sum(p['fl'] for p in players if p['t']==t)
        ts[t]=[['Passing yards',str(py)],['Rushing yards',str(ry)],['Total yards',str(py+ry)],['Turnovers',str(to)]]
    return {'players':players,'cats':cats,'ts':ts}
GW=gm[(gm.season==SEASON)&(gm.week==NEXT)].sort_values(['gameday','gametime']); LGAMES=[]; LBOX={}
for g in GW.itertuples():
    kick=datetime.datetime.strptime(f"{g.gameday} {g.gametime}","%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo('America/New_York')).isoformat() if isinstance(g.gametime,str) else None
    done=not pd.isna(g.home_score)
    fav=None if pd.isna(g.spread_line) else (f"{g.home_team} -{abs(g.spread_line):g}" if g.spread_line>0 else f"{g.away_team} -{abs(g.spread_line):g}" if g.spread_line<0 else 'Pick em')
    LGAMES.append({'id':g.game_id,'away':g.away_team,'home':g.home_team,'as':None if not done else int(g.away_score),'hs':None if not done else int(g.home_score),
                   'state':'post' if done else 'pre','detail':'Final' if done else None,'kick':kick,'venue':g.stadium if isinstance(g.stadium,str) else None,'odds':fav,'ou':None if pd.isna(g.total_line) else float(g.total_line)})
    if done:
        rows=S26[S26.game_id==g.game_id]; LBOX[g.game_id]=box_from_stats(rows)
from ff_news import build_news
REL={p['id'] for p in players if (p.get('prev') or 0)>=6 or (p.get('fpg') or 0)>=6 or (p.get('role') or 'X9')[-1] in '12'}
NEWS=build_news(SEASON,REL)
try:
    from news_update import fetch_headlines
    HEAD={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),'items':fetch_headlines()}
except Exception as e:
    print('headlines unavailable:',e); HEAD=None
# ---- projection history: each player's projection is refreshed every run until his game kicks off, then it stays frozen
PI_POS={p['id']:p['p'] for p in players}
HP='proj_history.json'
try: H=json.load(open(HP)) if os.path.exists(HP) else {}
except Exception: H={}
HS=H.setdefault(str(SEASON),{})
for p in players:
    if p['nw']==NEXT and p.get('proj') is not None: HS.setdefault(str(NEXT),{})[p['id']]=[p['proj'],p.get('rpg') or 0]
json.dump(H,open(HP,'w'),separators=(',',':'))
# ---- accuracy of the frozen projections against what actually happened, week by week
ACC=[]
for wk,pr in sorted(HS.items(),key=lambda x:int(x[0])):
    act=S26[S26.week==int(wk)].set_index('player_id').fp
    rows=[(v[0],float(act[pid]),PI_POS.get(pid)) for pid,v in pr.items() if pid in act.index and v[0] is not None and v[0]>0]
    if len(rows)<30: continue
    dfa=pd.DataFrame(rows,columns=['p','a','pos']); rk=[spearmanr(x.p,x.a).correlation for _,x in dfa.groupby('pos') if len(x)>=10]
    ACC.append({'wk':int(wk),'n':len(dfa),'mae':r(float((dfa.p-dfa.a).abs().mean()),2),'rank':r(float(np.nanmean(rk)),3) if rk else None})
LIVE={'week':NEXT,'at':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='minutes'),'src':'official stats','games':LGAMES,'box':LBOX}
SCHED={t:[[int(g.week),g.opp,int(g.home),r(g.it,1),None if pd.isna(g.pts) else int(g.pts)] for g in SC26[SC26.team==t].sort_values('week').itertuples()] for t in SC26.team.unique()}
OUT={'asof':{'season':SEASON,'last_week':LAST,'next_week':NEXT,'built':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),'depth':str(dc.dt.max())[:10],'dp_values':str(dv.scrape_date.iloc[0])},
     'players':players,'live':LIVE,'news':NEWS,'headlines':HEAD,'ph':HS.get(str(NEXT),{}),'acc':ACC,'trendsval':json.load(open('trends_val.json')) if os.path.exists('trends_val.json') else None,'dvp':DVP,'lgpos':{p:r(lg26.get(p,np.nan),1) for p in POS},'sched':SCHED,'byes':byes,'model':{'test':res,'range':RNG,'qs':QS,'posavg':{k:r(v,1) for k,v in POSAVG.items()}}}
def clean(o):
    if isinstance(o,float) and (o!=o or abs(o)==float('inf')): return None
    if isinstance(o,(np.floating,)): return clean(float(o))
    if isinstance(o,(np.integer,)): return int(o)
    if isinstance(o,dict): return {str(k):clean(v) for k,v in o.items()}
    if isinstance(o,(list,tuple)): return [clean(v) for v in o]
    return o
json.dump(clean(OUT),open('ff_data.json','w'),separators=(',',':'),allow_nan=False)
print('players',len(players),'| next week',NEXT,'| json KB',os.path.getsize('ff_data.json')//1024,flush=True)
for p in players[:12]: print(f"{p['n']:24s} {p['p']} {p['t']} wk{p['nw']} vs {p['opp']} proj {p['proj']} (fpg {p['fpg']}, xfpg {p['xfpg']}, it {p['it']}, dvp {p['dvp']}) role {p['role']} inj {p['inj']}")
