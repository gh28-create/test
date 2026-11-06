import streamlit as st
import pandas as pd, numpy as np, sqlite3, random
from sklearn.ensemble import IsolationForest
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# ==========================================
# CONFIGURATION & STYLE
# ==========================================
st.set_page_config(page_title="AquaSense Pro | Détection de Fuites", page_icon="💧", layout="wide")

st.markdown("""
<style>
    /* Style général */
    .reportview-container { background: #f4f7f6; }
    /* Style des cartes KPI */
    div[data-testid="metric-container"] {
        background-color: white;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        border-left: 5px solid #0077b6;
    }
    div[data-testid="metric-container"] > label {
        color: #555;
        font-weight: 600;
    }
    div[data-testid="metric-container"] > div {
        color: #0077b6;
        font-size: 1.8rem;
        font-weight: bold;
    }
    /* Style des titres */
    h1 { color: #023e8a; }
    h2, h3 { color: #0077b6; }
    /* Bandeau d'alerte */
    .custom-warning {
        background-color: #fff3cd;
        color: #856404;
        padding: 15px;
        border-radius: 5px;
        border-left: 5px solid #ffeeba;
        margin-bottom: 20px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# INITIALISATION DB & IA
# ==========================================
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
    
    # Données clients
    conn.executemany("INSERT INTO clients VALUES(?,?,?,?,?)", [
        (1,'Hôtel Les Palmiers','Hôtellerie','Hammamet',2.8),
        (2,'TextileMed SARL','Textile','Monastir',2.5),
        (3,'AgroPlus','Agroalimentaire','Sfax',2.4),
        (4,'Résidence Marina','Hôtellerie','Sousse',2.8)])
    
    # Compteurs
    conn.executemany("INSERT INTO compteurs VALUES(?,?,?)", [
        (1,1,'global'),(2,1,'blanchisserie'),(3,1,'piscine'),
        (4,2,'global'),(5,2,'process'),(6,3,'global'),
        (7,4,'global'),(8,4,'sanitaires')])
    
    # Utilisateurs (Auth)
    conn.executemany("INSERT INTO users VALUES(?,?,?,?,?,?)", [
        (1,'admin@aquasense.tn','admin123','admin',None,'Administrateur AquaSense'),
        (2,'hotel@aquasense.tn','hotel123','client',1,'Hôtel Les Palmiers'),
        (3,'textile@aquasense.tn','textile123','client',2,'TextileMed')])
    
    # Génération des données simulées (90 jours)
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
                # Injection des fuites
                if cid==2 and d>=60 and 2<=h<=5: v += 0.90
                if cid==5 and d>=75 and 0<=h<=6: v += 0.60
                if cid==8 and d>=50 and (h>=22 or h<=3): v += 0.45
                rows.append((cid, ts.strftime('%Y-%m-%d %H:%M:%S'), round(v,3)))
    conn.executemany("INSERT INTO releves(cid,ts,vol) VALUES(?,?,?)", rows)
    conn.commit()
    
    # --- Modèle IA (Isolation Forest) ---
    df = pd.read_sql("""SELECT r.cid AS cid, r.ts AS ts, r.vol AS vol, cl.tarif AS tarif
                        FROM releves r JOIN compteurs c ON c.id=r.cid
                        JOIN clients cl ON cl.id=c.client_id""", conn)
    df['ts'] = pd.to_datetime(df['ts'])
    df['hour'] = df['ts'].dt.hour
    df['is_night'] = df['hour'].between(2,5).astype(int)
    
    df = df.sort_values(['cid', 'ts']).reset_index(drop=True)
    df['roll7'] = df.groupby('cid')['vol'].rolling(168, min_periods=24).mean().reset_index(0, drop=True)
    df['hmean'] = df.groupby(['cid', 'hour'])['vol'].transform('mean')
    df['ratio'] = df['vol'] / (df['hmean'] + 0.01)
    df = df.dropna(subset=['roll7'])
    
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
            alerts.append((int(cid), r['ts'].strftime('%Y-%m-%d %H:%M:%S'), float(r['score']), float(f), float(f*24*30*r['tarif'])))
    conn.executemany("INSERT INTO alertes(cid,ts,score,fuite,cout) VALUES(?,?,?,?,?)", alerts)
    conn.commit()
    return conn

conn = init_db()

# ==========================================
# LOGIN PAGE
# ==========================================
for k in ("email","role","nom","cid"):
    st.session_state.setdefault(k, None)

if not st.session_state.email:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<h1 style='text-align: center;'>💧 AquaSense Pro</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>Plateforme Intelligente de Détection des Fuites d'Eau</p>", unsafe_allow_html=True)
        st.markdown("---")
        with st.form("login"):
            e = st.text_input("📧 Email", "admin@aquasense.tn")
            p = st.text_input("🔒 Mot de passe", "admin123", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True, type="primary"):
                row = pd.read_sql(f"SELECT * FROM users WHERE email='{e}' AND pwd='{p}'", conn)
                if row.empty:
                    st.error("❌ Identifiants invalides.")
                else:
                    st.session_state.update(
                        email=row.iloc[0]['email'], role=row.iloc[0]['role'],
                        nom=row.iloc[0]['nom'], cid=row.iloc[0]['client_id'])
                    st.rerun()
        st.info("💡 **Comptes de démonstration :**\n\n**Admin :** admin@aquasense.tn / admin123\n\n**Client Hôtel :** hotel@aquasense.tn / hotel123\n\n**Client Usine :** textile@aquasense.tn / textile123")
    st.stop()

# ==========================================
# DASHBOARD (Interface Principale)
# ==========================================
# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3100/3100557.png", width=80)
    st.title("AquaSense Pro")
    st.markdown(f"**Utilisateur :** {st.session_state.nom}")
    st.markdown(f"**Rôle :** {st.session_state.role.capitalize()}")
    st.markdown("---")
    st.markdown("### 📖 Guide d'utilisation")
    st.info("""
    1. Consultez vos **indicateurs clés** en haut.
    2. L'IA analyse vos données et détecte les fuites.
    3. Le tableau ci-dessous vous montre **où** et **combien** vous perdez.
    4. Les alertes en **rouge** sont critiques et nécessitent une action rapide.
    """)
    if st.button("🚪 Déconnexion", use_container_width=True):
        for k in ("email","role","nom","cid"): st.session_state[k]=None
        st.rerun()

# Filtre SQL
where = "" if st.session_state.role=="admin" else f"WHERE c.client_id={st.session_state.cid}"

# Titre
st.markdown(f"<h1>Tableau de Bord — {st.session_state.nom}</h1>", unsafe_allow_html=True)

# --- KPIs ---
k = pd.read_sql(f"""SELECT COUNT(*) n, COALESCE(SUM(a.cout),0) c, COALESCE(SUM(a.fuite),0) f,
                           COUNT(DISTINCT a.cid) nc
                    FROM alertes a JOIN compteurs c ON c.id=a.cid {where}""", conn).iloc[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("🚨 Fuites Détectées", int(k['n']), help="Nombre total d'anomalies détectées par l'IA.")
col2.metric("🔧 Zones à Risque", int(k['nc']), help="Nombre de compteurs (zones) concernés par les fuites.")
col3.metric("💧 Débit Perdu (m³/h)", f"{k['f']:.2f}", help="Volume d'eau perdu chaque heure à cause des fuites.")
col4.metric("💰 Économies Potentielles", f"{k['c']*12:,.0f} DT", help="Argent que vous pouvez économiser sur une année en réparant ces fuites.")

st.markdown("<br>", unsafe_allow_html=True)

# --- ALERTES ---
st.markdown("### 🚨 Alertes de Fuites (Analysées par l'IA)")
al = pd.read_sql(f"""SELECT a.id, a.ts AS Date, cl.nom AS Client, c.zone AS Zone,
                            ROUND(a.score,3) AS Score, ROUND(a.fuite,2) AS 'Débit m³/h',
                            ROUND(a.cout,0) AS 'Coût (DT/mois)'
                     FROM alertes a
                     JOIN compteurs c ON c.id=a.cid
                     JOIN clients cl ON cl.id=c.client_id
                     {where} ORDER BY a.cout DESC""", conn)

if al.empty:
    st.success("✅ Excellente nouvelle ! Aucune fuite détectée pour le moment.")
else:
    # Fonction pour colorer le tableau
    def color_cost(val):
        if val > 1000: return 'background-color: #ffcccc; color: #cc0000; font-weight: bold'
        elif val > 500: return 'background-color: #ffe6cc; color: #cc6600;'
        return 'background-color: #ffffcc;'
    
    st.dataframe(al.drop(columns=['id']).style.applymap(color_cost, subset=['Coût (DT/mois)']), 
                 use_container_width=True, hide_index=True)
    
    st.markdown(f"""
    <div class="custom-warning">
        ⚠️ Action Requise : Réparer ces fuites vous permettrait d'économiser environ {al['Coût (DT/mois)'].sum()*12:,.0f} DT par an.
    </div>
    """, unsafe_allow_html=True)

# --- GRAPHIQUES ---
st.markdown("### 📈 Analyse de la Consommation")
co = pd.read_sql(f"""SELECT r.ts, r.vol, c.zone, cl.nom
                     FROM releves r JOIN compteurs c ON c.id=r.cid
                     JOIN clients cl ON cl.id=c.client_id {where}""", conn)
co['ts'] = pd.to_datetime(co['ts'])
co['hour'] = co['ts'].dt.hour

col_g1, col_g2 = st.columns(2)

with col_g1:
    st.markdown("**Profil Horaire Moyen (Courbe Normale vs Fuites)**")
    # On calcule la moyenne normale
    prof = co.groupby('hour')['vol'].mean().reset_index()
    fig1 = px.line(prof, x='hour', y='vol', markers=True, 
                   labels={'vol':'Débit Moyen (m³/h)','hour':'Heure de la journée'})
    fig1.update_traces(line_color='#0077b6', line_width=3)
    fig1.update_layout(plot_bgcolor='white', margin=dict(l=0,r=0,t=20,b=0))
    st.plotly_chart(fig1, use_container_width=True)
    st.caption("💡 Si la courbe reste élevée entre 2h et 5h du matin, cela confirme une fuite nocturne.")

with col_g2:
    st.markdown("**Répartition des Coûts par Zone**")
    by_zone = al.groupby('Zone')['Coût (DT/mois)'].sum().reset_index()
    if not by_zone.empty:
        fig2 = px.pie(by_zone, names='Zone', values='Coût (DT/mois)', hole=0.5, 
                      color_discrete_sequence=px.colors.sequential.Reds_r)
        fig2.update_layout(margin=dict(l=0,r=0,t=20,b=0))
        st.plotly_chart(fig2, use_container_width=True)
        st.caption("💡 Identifiez les zones qui vous coûtent le plus cher en eau.")
    else:
        st.info("Pas de données de coût à afficher.")

