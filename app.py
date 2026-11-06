# AquaSense Pro — Version démo Streamlit Cloud (1 fichier, SQLite intégré)
import streamlit as st
import pandas as pd, numpy as np, sqlite3, random
from sklearn.ensemble import IsolationForest
from datetime import datetime, timedelta
import plotly.express as px

st.set_page_config(page_title="AquaSense Pro", page_icon="💧", layout="wide")

# ---------- INIT DB EN MÉMOIRE ----------
@st.cache_resource
def init_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript("""
    CREATE TABLE clients(id INTEGER PRIMARY KEY, nom TEXT, secteur TEXT, ville TEXT, tarif REAL);
    CREATE TABLE compteurs(id INTEGER PRIMARY KEY, client_id INT, zone TEXT);
    CREATE TABLE releves(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME, vol REAL);
    CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT, pwd TEXT, role TEXT, client_id INT, nom TEXT);
    CREATE TABLE alertes(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME,
                         score REAL, fuite REAL, cout REAL, statut TEXT DEFAULT 'nouvelle');
    """)
    conn.executemany("INSERT INTO clients VALUES(?,?,?,?,?)", [
        (1,'Hôtel Les Palmiers','Hôtellerie','Hammamet',2.8),
        (2,'TextileMed SARL','Textile','Monastir',2.5),
        (3,'AgroPlus','Agroalimentaire','Sfax',2.4),
        (4,'Résidence Marina','Hôtellerie','Sousse',2.8)])
    conn.executemany("INSERT INTO compteurs VALUES(?,?,?)", [
        (1,1,'global'),(2,1,'blanchisserie'),(3,1,'piscine'),
        (4,2,'global'),(5,2,'process'),(6,3,'global'),
        (7,4,'global'),(8,4,'sanitaires')])
    conn.executemany("INSERT INTO users VALUES(?,?,?,?,?,?)", [
        (1,'admin@aquasense.tn','admin123','admin',None,'Admin'),
        (2,'hotel@aquasense.tn','hotel123','client',1,'Hôtel Les Palmiers'),
        (3,'textile@aquasense.tn','textile123','client',2,'TextileMed')])
    random.seed(42); np.random.seed(42)
    start = datetime.utcnow() - timedelta(days=90)
    rows = []
    def profil(h):
        if 2 <= h <= 5: return 0.05
        if 8 <= h <= 18: return 0.40
        return 0.15
    for cid in range(1,9):
        for d in range(90):
            for h in range(24):
                ts = start + timedelta(days=d, hours=h)
                v = max(0, profil(h) + random.uniform(-0.05, 0.05))
                if cid==2 and d>=60 and 2<=h<=5: v += 0.90
                if cid==5 and d>=75 and 0<=h<=6: v += 0.60
                if cid==8 and d>=50 and (h>=22 or h<=3): v += 0.45
                rows.append((cid, ts.strftime('%Y-%m-%d %H:%M:%S'), round(v,3)))
    conn.executemany("INSERT INTO releves(cid,ts,vol) VALUES(?,?,?)", rows)
    conn.commit()
    # --- IA ---
    df = pd.read_sql("""SELECT r.cid, r.ts, r.vol, cl.tarif
                        FROM releves r
                        JOIN compteurs c ON c.id=r.cid
                        JOIN clients cl ON cl.id=c.client_id""", conn)
    df['ts'] = pd.to_datetime(df['ts'])
    df['hour'] = df['ts'].dt.hour
    df['is_night'] = df['hour'].between(2,5).astype(int)
    def feat(g):
        g = g.sort_values('ts').copy()
        g['roll7'] = g['vol'].rolling(168, min_periods=24).mean()
        g['hmean'] = g.groupby('hour')['vol'].transform('mean')
        g['ratio'] = g['vol']/(g['hmean']+0.01)
        return g
    df = df.groupby('cid', group_keys=False).apply(feat).dropna(subset=['roll7'])
    F = ['vol','hour','roll7','ratio','is_night']
    alerts = []
    for cid, g in df.groupby('cid'):
        X = g[F].fillna(0).values
        if len(X) < 50: continue
        m = IsolationForest(contamination=0.02, random_state=42).fit(X)
        g = g.copy(); g['score'] = -m.score_samples(X)
        seuil = np.percentile(g['score'], 98)
        sus = g[(g['score']>seuil) & (g['vol']>0.2)].copy()
        if sus.empty: continue
        sus['date'] = sus['ts'].dt.date
        sus = sus.sort_values('score', ascending=False).drop_duplicates(['cid','date'])
        for _, r in sus.iterrows():
            f = max(0, r['vol'] - r['hmean'])
            alerts.append((int(cid), r['ts'].strftime('%Y-%m-%d %H:%M:%S'),
                           float(r['score']), float(f), float(f*24*30*r['tarif'])))
    conn.executemany("INSERT INTO alertes(cid,ts,score,fuite,cout) VALUES(?,?,?,?,?)", alerts)
    conn.commit()
    return conn

conn = init_db()

# ---------- LOGIN ----------
for k in ("email","role","nom","cid"):
    st.session_state.setdefault(k, None)

if not st.session_state.email:
    st.title("💧 AquaSense Pro")
    st.caption("Détection de fuites d'eau par IA — Tunisie")
    with st.form("login"):
        e = st.text_input("Email", "admin@aquasense.tn")
        p = st.text_input("Mot de passe", "admin123", type="password")
        if st.form_submit_button("Se connecter", use_container_width=True):
            row = pd.read_sql(f"SELECT * FROM users WHERE email='{e}' AND pwd='{p}'", conn)
            if row.empty:
                st.error("Identifiants invalides")
            else:
                st.session_state.update(
                    email=row.iloc[0]['email'], role=row.iloc[0]['role'],
                    nom=row.iloc[0]['nom'], cid=row.iloc[0]['client_id'])
                st.rerun()
    st.caption("Comptes : **admin@aquasense.tn/admin123** · **hotel@aquasense.tn/hotel123** · **textile@aquasense.tn/textile123**")
    st.stop()

# ---------- HEADER ----------
c1, c2 = st.columns([4,1])
c1.markdown(f"### 💧 AquaSense Pro — {st.session_state.nom} *({st.session_state.role})*")
if c2.button("Déconnexion"):
    for k in ("email","role","nom","cid"): st.session_state[k]=None
    st.rerun()

where = "" if st.session_state.role=="admin" else f"WHERE c.client_id={st.session_state.cid}"

# ---------- KPIs ----------
k = pd.read_sql(f"""SELECT COUNT(*) n, COALESCE(SUM(a.cout),0) c, COALESCE(SUM(a.fuite),0) f,
                           COUNT(DISTINCT a.cid) nc
                    FROM alertes a JOIN compteurs c ON c.id=a.cid {where}""", conn).iloc[0]
a,b,c,d = st.columns(4)
a.metric("🚨 Alertes", int(k['n']))
b.metric("🔧 Compteurs", int(k['nc']))
c.metric("💧 Fuite m³/h", f"{k['f']:.2f}")
d.metric("💰 Coût/an évitable", f"{k['c']*12:,.0f} DT")

# ---------- ALERTES ----------
st.subheader("🚨 Alertes détectées par l'IA")
al = pd.read_sql(f"""SELECT a.id, a.ts AS Date, cl.nom AS Client, c.zone AS Zone,
                            ROUND(a.score,3) AS 'Score IA', ROUND(a.fuite,2) AS 'Fuite m³/h',
                            ROUND(a.cout,0) AS 'DT/mois'
                     FROM alertes a
                     JOIN compteurs c ON c.id=a.cid
                     JOIN clients cl ON cl.id=c.client_id
                     {where} ORDER BY a.score DESC""", conn)
if al.empty:
    st.info("Aucune alerte.")
else:
    st.dataframe(al.drop(columns=['id']), use_container_width=True, hide_index=True)
    st.warning(f"⚠️ **Coût total évitable : {al['DT/mois'].sum():,.0f} DT/mois ≈ {al['DT/mois'].sum()*12:,.0f} DT/an**")

# ---------- CONSO ----------
st.subheader("📈 Consommation horaire")
co = pd.read_sql(f"""SELECT r.ts, r.vol, c.zone, cl.nom
                     FROM releves r JOIN compteurs c ON c.id=r.cid
                     JOIN clients cl ON cl.id=c.client_id {where}""", conn)
co['ts'] = pd.to_datetime(co['ts']); co['hour']=co['ts'].dt.hour
col1,col2 = st.columns(2)
col1.plotly_chart(px.area(co.groupby('hour')['vol'].mean().reset_index(),
                   x='hour', y='vol', labels={'vol':'m³/h','hour':'Heure'}), use_container_width=True)
col2.plotly_chart(px.pie(co.groupby('zone')['vol'].sum().reset_index(),
                   names='zone', values='vol', hole=0.5), use_container_width=True)
