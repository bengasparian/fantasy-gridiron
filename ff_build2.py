import pandas as pd,numpy as np,json,io,urllib.request,datetime
from sklearn.ensemble import HistGradientBoostingRegressor as HGBR
from scipy.stats import spearmanr
POS=['QB','RB','WR','TE']; SEASON=2026
def r(v,d=2): return None if v is None or (isinstance(v,float) and np.isnan(v)) else round(float(v),d)
# ---------- weekly stats
st=pd.concat([pd.read_parquet(f'stats_player_week_{y}.parquet') for y in (2021,2022,2023,2024,2025,2026)]); st=st[(st.season_type=='REG')&st.position.isin(POS)].copy()
st['fp']=st.fantasy_points_ppr; st['fps']=st.fantasy_points
# ---------- expected fantasy points (PPR) from opportunities, learned on 2023-2025 pbp
C=['season','week','game_id','play_type','posteam','receiver_player_id','rusher_player_id','air_yards','yardline_100','complete_pass','yards_gained','touchdown','pass_touchdown','rush_touchdown','qb_kneel','sack','two_point_attempt']
pb=pd.concat([pd.read_parquet(f'pbp_{y}.parquet',columns=C) for y in (2021,2022,2023,2024,2025,2026)]); pb=pb[pb.two_point_attempt!=1]
yb=lambda y:pd.cut(y,[0,5,10,20,50,100],labels=['1-5','6-10','11-20','21-50','51+'])
tg=pb[(pb.play_type=='pass')&pb.receiver_player_id.notna()&(pb.sack!=1)].copy()
tg['ab']=pd.cut(tg.air_yards.fillna(-99),[-100,-50,0,5,10,15,20,30,120],labels=['na','<=0','1-5','6-10','11-15','16-20','21-30','31+']); tg['yb']=yb(tg.yardline_100)
tg['out']=tg.complete_pass.fillna(0)*(1+0.1*tg.yards_gained.fillna(0))+6*tg.pass_touchdown.fillna(0)
ru=pb[(pb.play_type=='run')&pb.rusher_player_id.notna()&(pb.qb_kneel!=1)].copy(); ru['yb']=pd.cut(ru.yardline_100,[0,2,5,10,20,50,100],labels=['1-2','3-5','6-10','11-20','21-50','51+'])
ru['out']=0.1*ru.yards_gained.fillna(0)+6*ru.rush_touchdown.fillna(0)
tr=lambda d:d[d.season.between(2021,2024)]   # learned before the 2025 test season
xt=tr(tg).groupby(['ab','yb'],observed=True).out.mean(); xr=tr(ru).groupby('yb',observed=True).out.mean()
tg['x']=[xt.get((a,b),np.nan) for a,b in zip(tg.ab,tg.yb)]; ru['x']=ru.yb.map(xr).astype(float)
tg['rz']=(tg.yardline_100<=20).astype(int); ru['rz']=(ru.yardline_100<=20).astype(int)
X=pd.concat([tg.groupby(['season','week','receiver_player_id']).agg(xr=('x','sum'),rzt=('rz','sum')).rename_axis(['season','week','player_id']),
             ru.groupby(['season','week','rusher_player_id']).agg(xc=('x','sum'),rzc=('rz','sum')).rename_axis(['season','week','player_id'])],axis=1).fillna(0).reset_index()
X['xfp']=X.xr+X.xc; X['rzo']=X.rzt+X.rzc
st=st.merge(X[['season','week','player_id','xfp','rzo']],on=['season','week','player_id'],how='left'); st[['xfp','rzo']]=st[['xfp','rzo']].fillna(0)
print('xFP model: avg PPR per target by depth/field position learned from',len(tr(tg)),'targets and',len(tr(ru)),'carries',flush=True)
# ---------- snap share (PFR ids -> gsis)
ids=pd.read_csv('db_playerids.csv',low_memory=False); pfr2g=ids.dropna(subset=['pfr_id','gsis_id']).drop_duplicates('pfr_id').set_index('pfr_id').gsis_id.to_dict()
sn=pd.concat([pd.read_parquet(f'snap_counts_{y}.parquet') for y in (2021,2022,2023,2024,2025,2026)]); sn=sn[sn.game_type=='REG']; sn['player_id']=sn.pfr_player_id.map(pfr2g)
st=st.merge(sn[['season','week','player_id','offense_pct']].dropna(subset=['player_id']).drop_duplicates(['season','week','player_id']),on=['season','week','player_id'],how='left')
# team carries per game for carry share
tc=st.groupby(['season','week','team']).carries.sum().rename('team_car').reset_index(); st=st.merge(tc,on=['season','week','team'])
st['car_share']=np.where(st.team_car>0,st.carries/st.team_car,np.nan)
# ---------- schedule, implied team totals
gm=pd.read_csv(io.BytesIO(urllib.request.urlopen('https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv',timeout=120).read()))
gm=gm[gm.season.between(2021,2026)&(gm.game_type=='REG')]
rows=[]
for g in gm.itertuples():
    for t,o,home in ((g.home_team,g.away_team,1),(g.away_team,g.home_team,0)):
        it=np.nan if pd.isna(g.total_line) or pd.isna(g.spread_line) else (g.total_line/2+(g.spread_line/2 if home else -g.spread_line/2))
        rows.append((g.season,g.week,t,o,home,it,g.home_score if home else g.away_score))
SC=pd.DataFrame(rows,columns=['season','week','team','opp','home','it','pts'])
st=st.merge(SC[['season','week','team','home','it']],on=['season','week','team'],how='left')
# ---------- fantasy points allowed by defense to each position
def dvp_table(s,before):
    d=st[(st.season==s)&(st.week<before)]
    a=d.groupby(['opponent_team','position','week']).fp.sum().reset_index().groupby(['opponent_team','position']).fp.agg(['sum','count'])
    lg=d.groupby(['position','week','opponent_team']).fp.sum().groupby('position').mean()
    return a,lg
def dvp_factor(s,before,team,pos,k=4):
    a,lg=DV.get((s,before)) or DV.setdefault((s,before),dvp_table(s,before))
    base=lg.get(pos,np.nan)
    if (team,pos) not in a.index or not base==base: return np.nan
    sm,c=a.loc[(team,pos)]; return float((sm+k*base)/(c+k)/base)
DV={}
# ---------- features for each player-week
def feats(s,t,p_rows,team_opp):
    """p_rows: weeks < t of season s for one player; returns feature dict"""
    pr=p_rows; g=len(pr)
    return {'g':g,'ppg':pr.fp.mean() if g else np.nan,'xpg':pr.xfp.mean() if g else np.nan,'l3':pr.fp.tail(3).mean() if g else np.nan,
            'snap':pr.offense_pct.mean() if g and pr.offense_pct.notna().any() else np.nan,'ts':pr.target_share.mean() if g else np.nan,
            'cs':pr.car_share.mean() if g else np.nan,'rz':pr.rzo.mean() if g else np.nan}
st=st.sort_values(['player_id','season','week'])
prev=st.groupby(['player_id','season']).agg(pg=('fp','mean'),gg=('fp','size')).reset_index(); prev['season']+=1; prev=prev[prev.gg>=3].set_index(['player_id','season']).pg
def build(seasons):
    out=[]
    for (pid,s),grp in st[st.season.isin(seasons)].groupby(['player_id','season']):
        grp=grp.sort_values('week')
        for i,row in enumerate(grp.itertuples()):
            if row.week<2: continue
            f=feats(s,row.week,grp.iloc[:i],None); f.update(player_id=pid,season=s,week=row.week,pos=row.position,y=row.fp,prev=prev.get((pid,s),np.nan),
               dvp=dvp_factor(s,row.week,row.opponent_team,row.position) if row.week>2 else np.nan,it=row.it,home=row.home)
            out.append(f)
    return pd.DataFrame(out)
F=['g','ppg','xpg','l3','snap','ts','cs','rz','prev','dvp','it','home']

DTR=build([2021,2022,2023,2024]); D25=build([2025]); print('training rows 2021-24:',len(DTR),'| test rows 2025:',len(D25),flush=True)
from sklearn.linear_model import HuberRegressor
POSAVG={p:float(DTR[DTR.pos==p].y.mean()) for p in POS}
def prep(d):
    d=d.copy(); pa=d.pos.map(POSAVG); pv=d.prev.fillna(pa)
    d['b']=np.where(d.g>0,(d.ppg.fillna(0)*d.g+pv*3)/(d.g+3),pv)          # season average shrunk toward last season
    d['bx']=np.where(d.g>0,(d.xpg.fillna(0)*d.g+pv*3)/(d.g+3),pv)         # opportunity-based expected points, shrunk the same way
    d['l3f']=d.l3.fillna(d.b); d['dv']=d.dvp.fillna(1.0)-1; d['iv']=d.it.fillna(22.5)/22.5-1
    d['bd']=d.b*d.dv; d['bi']=d.b*d.iv; return d
L=['b','bx','l3f','bd','bi']
res={}; MODELS={}; RNG={}; CHOICE={}
for pos in POS:
    a=prep(DTR[DTR.pos==pos]); t=prep(D25[D25.pos==pos])
    lin=HuberRegressor(max_iter=500,epsilon=1.6).fit(a[L],a.y); pl=lin.predict(t[L])
    tree=HGBR(max_iter=250,learning_rate=.04,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.0,random_state=0).fit(a[F+['b','bx']],a.y); pt=tree.predict(t[F+['b','bx']])
    def sp(pred):
        v=[spearmanr(x.pp,x.y).correlation for w,x in t.assign(pp=pred).groupby('week') if len(x)>8]; return float(np.nanmean(v))
    cand={'blend':t.b.values,'linear':pl,'tree':pt}
    sc={k:{'mae':r(np.mean(np.abs(v-t.y))),'rank':r(sp(v),3)} for k,v in cand.items()}
    best=min(sc,key=lambda k:sc[k]['mae']); CHOICE[pos]=best
    res[pos]={'n':int(len(t)),**{f'{k}_{m}':sc[k][m] for k in sc for m in ('mae','rank')},'chosen':best}
    q=t.assign(pp=cand[best]); q=q[q.pp>=5]; ratio=q.y/q.pp; RNG[pos]=[r(ratio.quantile(.1)),r(ratio.quantile(.9))]
    print(pos,res[pos],'range',RNG[pos],flush=True)
DA=pd.concat([DTR,D25])
for pos in POS:
    a=prep(DA[DA.pos==pos])
    MODELS[pos]=('linear',HuberRegressor(max_iter=500,epsilon=1.6).fit(a[L],a.y)) if CHOICE[pos]=='linear' else ('tree',HGBR(max_iter=250,learning_rate=.04,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.0,random_state=0).fit(a[F+['b','bx']],a.y)) if CHOICE[pos]=='tree' else ('blend',None)
    if MODELS[pos][0]=='linear': print(pos,'linear weights',dict(zip(L,np.round(MODELS[pos][1].coef_,3))),'intercept',round(MODELS[pos][1].intercept_,2))
import pickle; pickle.dump({'models':MODELS,'res':res,'rng':RNG,'choice':CHOICE,'posavg':POSAVG,'xt':xt,'xr':xr},open('ff_models.pkl','wb'))
st.to_parquet('ff_weekly.parquet'); SC.to_parquet('ff_sched.parquet'); print('DONE',flush=True)
