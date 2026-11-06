import streamlit as st
import pandas as pd, numpy as np, sqlite3, random, os
from sklearn.ensemble import IsolationForest
from datetime import datetime, timedelta
import plotly.express as px
from groq import Groq

# ==========================================
# CONFIGURATION & STYLE PREMIUM
# ==========================================
st.set_page_config(page_title="AquaSense Pro | Gestion Intelligente de l'Eau", page_icon="💧", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Style des cartes KPI (Effet Glassmorphism) */
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 8px 16px rgba(0, 119, 182, 0.1);
        border: 1px solid #e1e8ed;
        border-left: 6px solid #0077b6;
        transition: transform 0.2s;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
    }
    div[data-testid="metric-container"] > label {
        color: #475569;
        font-weight: 600;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    div[data-testid="metric-container"] > div {
        color: #023e8a;
        font-size: 2rem;
        font-weight: 700;
    }
    
    /* Titres */
    h1 { color: #023e8a; font-weight: 700; letter-spacing: -0.5px; }
    h2, h3 { color: #0077b6; font-weight: 600; }
    
    /* Bannière de sensibilisation à l'eau */
    .water-banner {
        background: linear-gradient(90deg, #0077b6 0%, #00b4d8 100%);
        color: white;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 25px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 12px rgba(0, 180, 216, 0.3);
    }
    .water-banner-text { font-size: 1.1rem; font-weight: 500; }
    .water-banner-icon { font-size: 2rem; margin-right: 15px; }
    
    /* Bandeau d'alerte rouge/jaune */
    .custom-warning {
        background-color: #fff3cd; color: #856404; padding: 15px;
        border-radius: 8px; border-left: 5px solid #ffeeba; margin-bottom: 20px; font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# INITIALISATION DB & IA (IN-MEMORY)
# ==========================================
@st.cache_resource(show_spinner="Initialisation de la base de données et de l'IA...")
def init_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, nom TEXT, secteur TEXT, ville TEXT, tarif REAL);
    CREATE TABLE IF NOT EXISTS compteurs(id INTEGER PRIMARY KEY, client_id INT, zone TEXT);
    CREATE TABLE IF NOT EXISTS releves(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME, vol REAL);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT, pwd TEXT, role TEXT, client_id INT, nom TEXT);
    CREATE TABLE IF NOT EXISTS alertes(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME, score REAL, fuite REAL, cout REAL, statut TEXT DEFAULT 'Nouvelle');
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
    
    generate_alerts(conn)
    return conn

def generate_alerts(conn):
    conn.execute("DELETE FROM alertes")
    df = pd.read_sql("SELECT r.cid, r.ts, r.vol, cl.tarif FROM releves r JOIN compteurs c ON c.id=r.cid JOIN clients cl ON cl.id=c.client_id", conn)
    if df.empty: return
    
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

conn = init_db()

# ==========================================
# INITIALISATION CHAT
# ==========================================
if "chat_history" not in st.session_state:
    st.session_state.chat_history = {1: [], 2: [], 3: [], 4: []}

# ==========================================
# LOGIN (Design Amélioré)
# ==========================================
for k in ("email","role","nom","cid"):
    st.session_state.setdefault(k, None)

if not st.session_state.email:
    col1, col2, col3 = st.columns([1,1.5,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center; color: #0077b6;'>💧 AquaSense Pro</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #64748b; font-size: 1.1rem;'>La gestion intelligente de l'eau pour les entreprises.</p>", unsafe_allow_html=True)
        
        with st.container(border=True):
            st.markdown("<h3 style='text-align: center;'>Connexion à votre espace</h3>", unsafe_allow_html=True)
            with st.form("login"):
                e = st.text_input("📧 Email professionnel", "admin@aquasense.tn")
                p = st.text_input("🔒 Mot de passe", "admin123", type="password")
                if st.form_submit_button("Accéder au tableau de bord", width='stretch', type="primary"):
                    row = pd.read_sql("SELECT * FROM users WHERE email=? AND pwd=?", conn, params=(e, p))
                    if not row.empty:
                        st.session_state.update(email=row.iloc[0]['email'], role=row.iloc[0]['role'], nom=row.iloc[0]['nom'], cid=row.iloc[0]['client_id'])
                        st.rerun()
                    else: st.error("❌ Identifiants invalides.")
        st.info("💡 **Comptes de démo :**\nAdmin: admin@aquasense.tn / admin123\nClient Hôtel: hotel@aquasense.tn / hotel123")
    st.stop()

# ==========================================
# SIDEBAR & DASHBOARD
# ==========================================
with st.sidebar:
    st.markdown("<h2>💧 AquaSense</h2>", unsafe_allow_html=True)
    st.markdown(f"**👤 Utilisateur :** {st.session_state.nom}")
    st.markdown(f"**🛡️ Rôle :** {st.session_state.role.capitalize()}")
    
    if st.session_state.role == "admin":
        st.markdown("---")
        st.markdown("### 📤 Importer des données (Admin)")
        uploaded_file = st.file_uploader("Fichier Excel / CSV", type=["csv", "xlsx"])
        if uploaded_file is not None:
            if st.button("Remplacer & Relancer l'IA", width='stretch'):
                try:
                    df_new = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                    if not {'cid', 'ts', 'vol'}.issubset(df_new.columns):
                        st.error("Colonnes requises : cid, ts, vol")
                    else:
                        conn.execute("DELETE FROM releves")
                        conn.executemany("INSERT INTO releves(cid,ts,vol) VALUES(?,?,?)", df_new[['cid', 'ts', 'vol']].values.tolist())
                        conn.commit()
                        generate_alerts(conn)
                        st.success("✅ Données importées et IA relancée !")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {e}")
        st.markdown("---")

    if st.button("🚪 Déconnexion", width='stretch'):
        for k in ("email","role","nom","cid"): st.session_state[k]=None
        st.rerun()

# ==========================================
# MAIN DASHBOARD
# ==========================================
where = "" if st.session_state.role=="admin" else f"WHERE c.client_id={st.session_state.cid}"

# Bannière de sensibilisation
st.markdown("""
<div class="water-banner">
    <div style="display: flex; align-items: center;">
        <div class="water-banner-icon">🌍</div>
        <div class="water-banner-text">
            <b>Le saviez-vous ?</b> En Tunisie, une fuite non détectée peut gaspiller jusqu'à <b>200 litres d'eau par jour</b>. 
            Chaque goutte sauvée est un pas vers la durabilité.
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown(f"<h1>Tableau de Bord — {st.session_state.nom}</h1>", unsafe_allow_html=True)

tab_dash, tab_chat = st.tabs(["📊 Tableau de Bord", "💬 Support & Chat"])

with tab_dash:
    # Calcul des KPIs
    where_kpi = where + (" AND " if where else "WHERE ") + "a.statut != 'Résolue'"
    k = pd.read_sql(f"SELECT COUNT(*) n, COALESCE(SUM(a.cout),0) c, COALESCE(SUM(a.fuite),0) f, COUNT(DISTINCT a.cid) nc FROM alertes a JOIN compteurs c ON c.id=a.cid {where_kpi}", conn).iloc[0]
    
    # Conversion m³ -> Litres (1 m³ = 1000 L)
    litres_perdus_mois = k['f'] * 24 * 30 * 1000 
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🚨 Fuites Actives", int(k['n']), help="Nombre de fuites nécessitant une action.")
    col2.metric("💧 Eau Perdue (Litres/mois)", f"{litres_perdus_mois:,.0f} L", help="Équivalent en bouteilles d'eau de 1.5L.")
    col3.metric("💸 Coût Mensuel", f"{k['c']:,.0f} DT", help="Argent perdu ce mois-ci à cause des fuites.")
    col4.metric("💰 Économies / An", f"{k['c']*12:,.0f} DT", help="Ce que vous pourriez économiser en réparant ces fuites.")
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("### 🚨 Alertes & Actions Correctives")
    
    al = pd.read_sql(f"SELECT a.id, a.ts AS Date, cl.nom AS Client, c.zone AS Zone, ROUND(a.score,3) AS Score, ROUND(a.fuite,2) AS 'Débit m³/h', ROUND(a.cout,0) AS 'Coût (DT/mois)', a.statut AS Statut FROM alertes a JOIN compteurs c ON c.id=a.cid JOIN clients cl ON cl.id=c.client_id {where} ORDER BY a.cout DESC", conn)
    
    if not al.empty:
        al['Date'] = pd.to_datetime(al['Date'])
        
        edited_al = st.data_editor(
            al,
            column_config={
                "id": None, 
                "Date": st.column_config.DatetimeColumn("Date de détection", format="D MMM YYYY, HH:mm"),
                "Score": st.column_config.NumberColumn("Confiance IA", format="%.3f"),
                "Débit m³/h": st.column_config.NumberColumn("Débit (m³/h)", format="%.2f"),
                "Coût (DT/mois)": st.column_config.NumberColumn("Coût (DT/mois)", format="%.0f DT"),
                "Statut": st.column_config.SelectboxColumn(
                    "État de la fuite",
                    help="Mettre à jour l'état",
                    options=["Nouvelle", "En cours", "Résolue"],
                    required=True,
                )
            },
            hide_index=True,
            width='stretch',
            key="alerts_editor"
        )
        
        changed = False
        for i in range(len(al)):
            if al.loc[i, 'Statut'] != edited_al.loc[i, 'Statut']:
                conn.execute("UPDATE alertes SET statut = ? WHERE id = ?", (edited_al.loc[i, 'Statut'], al.loc[i, 'id']))
                
                # Notification "Toast" (Hédha elli bch y3ajbek)
                if edited_al.loc[i, 'Statut'] == 'Résolue':
                    cout_sauve = al.loc[i, 'Coût (DT/mois)']
                    litres_sauves = al.loc[i, 'Débit m³/h'] * 24 * 30 * 1000
                    st.toast(f"🎉 Excellente décision ! Vous venez d'économiser {litres_sauves:,.0f} Litres d'eau et {cout_sauve:,.0f} DT/mois.", icon="✅")
                changed = True
        
        if changed:
            conn.commit()
            st.rerun()

        st.markdown(f'<div class="custom-warning">⚠️ <b>Action Requise :</b> Les fuites "Nouvelles" vous coûtent de l\'argent chaque jour. Passez le statut à "Résolue" une fois le plombier intervenu.</div>', unsafe_allow_html=True)
    else:
        st.success("✅ Félicitations ! Aucune fuite active. Votre installation est optimale.")

    # Graphes
    co = pd.read_sql(f"SELECT r.ts, r.vol, c.zone FROM releves r JOIN compteurs c ON c.id=r.cid {where}", conn)
    co['ts'] = pd.to_datetime(co['ts']); co['hour'] = co['ts'].dt.hour
    
    st.markdown("### 📈 Analyse de la Consommation")
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        prof = co.groupby('hour')['vol'].mean().reset_index()
        fig1 = px.line(prof, x='hour', y='vol', markers=True, labels={'vol':'Débit Moyen (m³/h)','hour':'Heure de la journée'})
        fig1.update_traces(line_color='#0077b6', line_width=3)
        fig1.update_layout(plot_bgcolor='white', margin=dict(l=0,r=0,t=20,b=0), title="Profil de consommation (24h)")
        st.plotly_chart(fig1, width='stretch')
    with col_g2:
        al_active = al[al['Statut'] != 'Résolue']
        if not al_active.empty:
            by_zone = al_active.groupby('Zone')['Coût (DT/mois)'].sum().reset_index()
            fig2 = px.pie(by_zone, names='Zone', values='Coût (DT/mois)', hole=0.5, color_discrete_sequence=px.colors.sequential.Blues_r, title="Répartition des pertes par zone")
            st.plotly_chart(fig2, width='stretch')

# ------------------------------------------
# TAB 2 : CHAT & SUPPORT
# ------------------------------------------
with tab_chat:
    st.markdown("### 💬 Messagerie avec le Support AquaSense")
    
    if st.session_state.role == "admin":
        st.info("Mode Admin : Sélectionnez un client pour voir sa conversation.")
        clients_list = pd.read_sql("SELECT id, nom FROM clients", conn)
        selected_client_name = st.selectbox("Sélectionnez un client :", clients_list['nom'])
        chat_cid = int(clients_list[clients_list['nom'] == selected_client_name]['id'].iloc[0])
    else:
        chat_cid = st.session_state.cid
        st.info("Notre assistant IA est disponible 24h/24 pour vous aider.")

    chat_box = st.container(height=400)
    with chat_box:
        for m in st.session_state.chat_history[chat_cid]:
            with st.chat_message("user" if m['role'] == st.session_state.role else "assistant"):
                st.write(f"**{m['sender']}** ({m['ts']})")
                st.write(m['text'])

    # Boutons Rapides
    if st.session_state.role == "client":
        st.markdown("**💡 Actions rapides :**")
        col_b1, col_b2, col_b3 = st.columns(3)
        btn_fuite = col_b1.button("🔧 Réparer une fuite", width='stretch')
        btn_prix = col_b2.button("💰 Tarifs", width='stretch')
        btn_urgence = col_b3.button("🚨 Urgence", width='stretch')
        
        prompt_btn = None
        if btn_fuite: prompt_btn = "Comment faire pour réparer une fuite ?"
        elif btn_prix: prompt_btn = "Quel est le prix de l'abonnement ?"
        elif btn_urgence: prompt_btn = "J'ai besoin d'une intervention urgente."
        
        if prompt_btn:
            ts_now = datetime.now().strftime('%H:%M')
            st.session_state.chat_history[chat_cid].append({"role": "client", "sender": st.session_state.nom, "text": prompt_btn, "ts": ts_now})
            
            bot_reply = "Un technicien va vous répondre sous peu."
            if "fuite" in prompt_btn.lower(): bot_reply = "Nous avons noté la fuite. L'équipe de maintenance intervient sous 24h."
            elif "prix" in prompt_btn.lower(): bot_reply = "L'abonnement SaaS est de 500 DT/mois (ROI x10)."
            elif "urgence" in prompt_btn.lower(): bot_reply = "Urgence enregistrée. Un technicien vous appellera dans les plus brefs délais."
            
            st.session_state.chat_history[chat_cid].append({"role": "assistant", "sender": "Bot AquaSense (IA)", "text": bot_reply, "ts": ts_now})
            st.rerun()

    # Chat IA (Groq)
    if prompt := st.chat_input("Posez votre question ici..."):
        ts_now = datetime.now().strftime('%H:%M')
        st.session_state.chat_history[chat_cid].append({"role": st.session_state.role, "sender": st.session_state.nom, "text": prompt, "ts": ts_now})
        
        if st.session_state.role == "client":
            query_top = pd.read_sql(f"SELECT c.zone, a.cout FROM alertes a JOIN compteurs c ON c.id=a.cid WHERE c.client_id={chat_cid} AND a.statut != 'Résolue' ORDER BY a.cout DESC LIMIT 3", conn)
            
            if not query_top.empty:
                data_context = "Voici les fuites ACTIVES détectées pour ce client : \n"
                for _, row in query_top.iterrows():
                    data_context += f"- Zone: {row['zone']}, Coût: {row['cout']:.0f} DT/mois\n"
            else:
                data_context = "Aucune fuite active détectée pour ce client."

            try:
                api_key = st.secrets.get("GROQ_API_KEY", "")
                if api_key == "":
                    bot_reply = "Erreur technique : Veuillez configurer votre clé API Groq dans les secrets."
                else:
                    client_ai = Groq(api_key=api_key)
                    system_prompt = f"Tu es le 'Bot AquaSense', un assistant professionnel spécialisé dans la gestion de l'eau. Tu parles à : {st.session_state.nom}. Voici ses données ACTIVES :\n{data_context}\nRéponds de manière professionnelle, empathique et précise."
                    
                    chat_completion = client_ai.chat.completions.create(
                        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                        model="openai/gpt-oss-120b",
                    )
                    bot_reply = chat_completion.choices[0].message.content
            except Exception as e:
                bot_reply = f"Erreur technique : {str(e)}"
            
            st.session_state.chat_history[chat_cid].append({"role": "assistant", "sender": "Bot AquaSense (IA)", "text": bot_reply, "ts": ts_now})
        
        st.rerun()
