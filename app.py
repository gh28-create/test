import streamlit as st
import pandas as pd, numpy as np, sqlite3, random, os
from sklearn.ensemble import IsolationForest
from datetime import datetime, timedelta
import plotly.express as px

# ==========================================
# CONFIGURATION & STYLE
# ==========================================
st.set_page_config(page_title="AquaSense Pro | Détection de Fuites", page_icon="💧", layout="wide")

st.markdown("""
<style>
    div[data-testid="metric-container"] {
        background-color: white; border-radius: 10px; padding: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-left: 5px solid #0077b6;
    }
    div[data-testid="metric-container"] > label { color: #555; font-weight: 600; }
    div[data-testid="metric-container"] > div { color: #0077b6; font-size: 1.8rem; font-weight: bold; }
    h1 { color: #023e8a; }
    h2, h3 { color: #0077b6; }
    .custom-warning {
        background-color: #fff3cd; color: #856404; padding: 15px;
        border-radius: 5px; border-left: 5px solid #ffeeba; margin-bottom: 20px; font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# INITIALISATION DB & IA (Dashboard Only)
# ==========================================
DB_FILE = "aquasense.db"

def get_db():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

if not os.path.exists(DB_FILE):
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, nom TEXT, secteur TEXT, ville TEXT, tarif REAL);
    CREATE TABLE IF NOT EXISTS compteurs(id INTEGER PRIMARY KEY, client_id INT, zone TEXT);
    CREATE TABLE IF NOT EXISTS releves(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME, vol REAL);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT, pwd TEXT, role TEXT, client_id INT, nom TEXT);
    CREATE TABLE IF NOT EXISTS alertes(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME, score REAL, fuite REAL, cout REAL, statut TEXT DEFAULT 'nouvelle');
    """)
    
    conn.executemany("INSERT INTO clients VALUES(?,?,?,?,?)", [
        (1,'Hôtel Les Palmiers','Hôtellerie','Hammamet',2.8), (2,'TextileMed SARL','Textile','Monastir',2.5),
        (3,'AgroPlus','Agroalimentaire','Sfax',2.4), (4,'Résidence Marina','Hôtellerie','Sousse',2.8)])
    conn.executemany("INSERT INTO compteurs VALUES(?,?,?)", [
        (1,1,'global'),(2,1,'blanchisserie'),(3,1,'piscine'), (4,2,'global'),(5,2,'process'),(6,3,'global'), (7,4,'global'),(8,4,'sanitaires')])
    conn.executemany("INSERT INTO users VALUES(?,?,?,?,?,?)", [
        (1,'admin@aquasense.tn','admin123','admin',None,'Administrateur AquaSense'),
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
    
    df = pd.read_sql("SELECT r.cid, r.ts, r.vol, cl.tarif FROM releves r JOIN compteurs c ON c.id=r.cid JOIN clients cl ON cl.id=c.client_id", conn)
    df['ts'] = pd.to_datetime(df['ts']); df['hour'] = df['ts'].dt.hour; df['is_night'] = df['hour'].between(2,5).astype(int)
    df = df.sort_values(['cid', 'ts']).reset_index(drop=True)
    df['roll7'] = df.groupby('cid')['vol'].rolling(168, min_periods=24).mean().reset_index(0, drop=True)
    df['hmean'] = df.groupby(['cid', 'hour'])['vol'].transform('mean')
    df['ratio'] = df['vol'] / (df['hmean'] + 0.01); df = df.dropna(subset=['roll7'])
    
    alerts = []
    for cid, g in df.groupby('cid'):
        X = g[['vol','hour','roll7','ratio','is_night']].fillna(0).values
        if len(X) < 50: continue
        m = IsolationForest(contamination=0.02, random_state=42).fit(X)
        g = g.copy(); g['score'] = -m.score_samples(X)
        sus = g[(g['score']>np.percentile(g['score'], 98)) & (g['vol']>0.2)].copy()
        if sus.empty: continue
        sus['date'] = sus['ts'].dt.date; sus = sus.sort_values('score', ascending=False).drop_duplicates(['cid','date'])
        for _, r in sus.iterrows():
            f = max(0, r['vol'] - r['hmean'])
            alerts.append((int(cid), r['ts'].strftime('%Y-%m-%d %H:%M:%S'), float(r['score']), float(f), float(f*24*30*r['tarif'])))
    conn.executemany("INSERT INTO alertes(cid,ts,score,fuite,cout) VALUES(?,?,?,?,?)", alerts)
    conn.commit()
    conn.close()

conn = get_db()

# ==========================================
# INITIALISATION CHAT (Fully In-Memory via Session State)
# ==========================================
if "chat_history" not in st.session_state:
    st.session_state.chat_history = {
        1: [{"role": "client", "sender": "Hôtel Les Palmiers", "text": "Bonjour, j'ai vu la fuite de la blanchisserie. Comment faire pour la réparer ?", "ts": "12:43"}],
        2: [],
        3: [],
        4: []
    }

# ==========================================
# LOGIN
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
            if st.form_submit_button("Se connecter", width='stretch', type="primary"):
                row = pd.read_sql("SELECT * FROM users WHERE email=? AND pwd=?", conn, params=(e, p))
                if not row.empty:
                    st.session_state.update(email=row.iloc[0]['email'], role=row.iloc[0]['role'], nom=row.iloc[0]['nom'], cid=row.iloc[0]['client_id'])
                    st.rerun()
                else: st.error("❌ Identifiants invalides.")
        st.info("💡 **Comptes :**\nAdmin: admin@aquasense.tn / admin123\nClient Hôtel: hotel@aquasense.tn / hotel123\nClient Usine: textile@aquasense.tn / textile123")
    st.stop()

# ==========================================
# SIDEBAR & DASHBOARD
# ==========================================
with st.sidebar:
    st.title("💧 AquaSense Pro")
    st.markdown(f"**Utilisateur :** {st.session_state.nom}")
    st.markdown(f"**Rôle :** {st.session_state.role.capitalize()}")
    st.markdown("---")
    if st.button("🚪 Déconnexion", width='stretch'):
        for k in ("email","role","nom","cid"): st.session_state[k]=None
        st.rerun()

where = "" if st.session_state.role=="admin" else f"WHERE c.client_id={st.session_state.cid}"
st.markdown(f"<h1>Tableau de Bord — {st.session_state.nom}</h1>", unsafe_allow_html=True)

tab_dash, tab_chat = st.tabs(["📊 Tableau de Bord", "💬 Support & Chat"])

# ------------------------------------------
# TAB 1 : DASHBOARD
# ------------------------------------------
with tab_dash:
    k = pd.read_sql(f"SELECT COUNT(*) n, COALESCE(SUM(a.cout),0) c, COALESCE(SUM(a.fuite),0) f, COUNT(DISTINCT a.cid) nc FROM alertes a JOIN compteurs c ON c.id=a.cid {where}", conn).iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🚨 Fuites Détectées", int(k['n']))
    col2.metric("🔧 Zones à Risque", int(k['nc']))
    col3.metric("💧 Débit Perdu (m³/h)", f"{k['f']:.2f}")
    col4.metric("💰 Économies Potentielles", f"{k['c']*12:,.0f} DT")
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("### 🚨 Alertes de Fuites (Analysées par l'IA)")
    al = pd.read_sql(f"SELECT a.id, a.ts AS Date, cl.nom AS Client, c.zone AS Zone, ROUND(a.score,3) AS Score, ROUND(a.fuite,2) AS 'Débit m³/h', ROUND(a.cout,0) AS 'Coût (DT/mois)' FROM alertes a JOIN compteurs c ON c.id=a.cid JOIN clients cl ON cl.id=c.client_id {where} ORDER BY a.cout DESC", conn)
    
    if not al.empty:
        def color_cost(val):
            try:
                v = float(val)
                if v > 1000: return 'background-color: #ffcccc; color: #cc0000; font-weight: bold'
                elif v > 500: return 'background-color: #ffe6cc; color: #cc6600;'
            except: pass
            return 'background-color: #ffffcc;'
        
        st.dataframe(al.drop(columns=['id']).style.map(color_cost, subset=['Coût (DT/mois)']), width='stretch', hide_index=True)
        st.markdown(f'<div class="custom-warning">⚠️ Action Requise : Réparer ces fuites vous permettrait d\'économiser environ {al["Coût (DT/mois)"].sum()*12:,.0f} DT par an.</div>', unsafe_allow_html=True)
    else:
        st.success("✅ Aucune fuite détectée.")

    co = pd.read_sql(f"SELECT r.ts, r.vol, c.zone FROM releves r JOIN compteurs c ON c.id=r.cid {where}", conn)
    co['ts'] = pd.to_datetime(co['ts']); co['hour'] = co['ts'].dt.hour
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        prof = co.groupby('hour')['vol'].mean().reset_index()
        fig1 = px.line(prof, x='hour', y='vol', markers=True, labels={'vol':'Débit Moyen (m³/h)','hour':'Heure'})
        fig1.update_traces(line_color='#0077b6', line_width=3)
        st.plotly_chart(fig1, width='stretch')
    with col_g2:
        if not al.empty:
            by_zone = al.groupby('Zone')['Coût (DT/mois)'].sum().reset_index()
            fig2 = px.pie(by_zone, names='Zone', values='Coût (DT/mois)', hole=0.5, color_discrete_sequence=px.colors.sequential.Reds_r)
            st.plotly_chart(fig2, width='stretch')

# ------------------------------------------
# TAB 2 : CHAT & SUPPORT (100% Bulletproof)
# ------------------------------------------
with tab_chat:
    st.markdown("### 💬 Messagerie avec le Support AquaSense")
    
    if st.session_state.role == "admin":
        st.info("En tant qu'Admin, vous pouvez discuter avec chaque client individuellement.")
        clients_list = pd.read_sql("SELECT id, nom FROM clients", conn)
        selected_client_name = st.selectbox("Sélectionnez un client :", clients_list['nom'])
        chat_cid = int(clients_list[clients_list['nom'] == selected_client_name]['id'].iloc[0])
    else:
        chat_cid = st.session_state.cid
        st.info("Posez vos questions techniques ou demandez de l'aide.")

    # Affichage de l'historique depuis la mémoire
    chat_box = st.container(height=400)
    with chat_box:
        for m in st.session_state.chat_history[chat_cid]:
            with st.chat_message("user" if m['role'] == st.session_state.role else "assistant"):
                st.write(f"**{m['sender']}** ({m['ts']})")
                st.write(m['text'])

    # Boutons rapides
    if st.session_state.role == "client":
        st.markdown("**💡 Questions fréquentes (Cliquez pour envoyer) :**")
        col_b1, col_b2, col_b3 = st.columns(3)
        
        btn_fuite = col_b1.button("🔧 Réparer une fuite", width='stretch')
        btn_prix = col_b2.button("💰 Prix de l'abonnement", width='stretch')
        btn_urgence = col_b3.button("🚨 Intervention urgente", width='stretch')
        
        prompt_btn = None
        if btn_fuite: prompt_btn = "Comment faire pour réparer une fuite ?"
        elif btn_prix: prompt_btn = "Quel est le prix de l'abonnement ?"
        elif btn_urgence: prompt_btn = "J'ai besoin d'une intervention urgente."
        
        if prompt_btn:
            ts_now = datetime.now().strftime('%H:%M')
            # Ajouter message client
            st.session_state.chat_history[chat_cid].append({"role": "client", "sender": st.session_state.nom, "text": prompt_btn, "ts": ts_now})
            
            # Ajouter réponse Bot
            bot_reply = "Un technicien va vous répondre sous peu."
            if "fuite" in prompt_btn.lower(): bot_reply = "Nous avons noté la fuite. L'équipe de maintenance intervient sous 24h."
            elif "prix" in prompt_btn.lower(): bot_reply = "Votre abonnement SaaS est de 500 DT/mois. Contactez admin@aquasense.tn."
            elif "urgence" in prompt_btn.lower(): bot_reply = "Urgence enregistrée. Un technicien vous appellera dans les plus brefs délais."
            
            st.session_state.chat_history[chat_cid].append({"role": "assistant", "sender": "Bot AquaSense (IA)", "text": bot_reply, "ts": ts_now})
            st.rerun()

    # Zone de saisie (st.chat_input howwa elli yekhdem mrigla w y7ell el clavier)
    if prompt := st.chat_input("Tapez votre message ici..."):
        ts_now = datetime.now().strftime('%H:%M')
        
        # Ajouter message client
        st.session_state.chat_history[chat_cid].append({"role": st.session_state.role, "sender": st.session_state.nom, "text": prompt, "ts": ts_now})
        
        # Réponse Bot
        if st.session_state.role == "client":
            bot_reply = "Bonjour ! Un technicien va vérifier ces données. Vérifiez les vannes la nuit."
            if "fuite" in prompt.lower(): bot_reply = "Nous avons bien noté la fuite. L'équipe de maintenance peut intervenir sous 24h."
            elif "prix" in prompt.lower() or "payer" in prompt.lower(): bot_reply = "Votre abonnement SaaS est de 500 DT/mois. Contactez admin@aquasense.tn."
            
            st.session_state.chat_history[chat_cid].append({"role": "assistant", "sender": "Bot AquaSense (IA)", "text": bot_reply, "ts": ts_now})
        
        st.rerun()
