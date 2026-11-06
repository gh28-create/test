import streamlit as st
import pandas as pd, numpy as np, sqlite3, random, os, io
from sklearn.ensemble import IsolationForest
from datetime import datetime, timedelta
import plotly.express as px
from groq import Groq
from fpdf import FPDF

# ==========================================
# CONFIGURATION & STYLE PREMIUM
# ==========================================
st.set_page_config(page_title="AquaSense Pro | Gestion Intelligente de l'Eau", page_icon="💧", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
        border-radius: 12px; padding: 20px;
        box-shadow: 0 8px 16px rgba(0, 119, 182, 0.1);
        border: 1px solid #e1e8ed; border-left: 6px solid #0077b6;
    }
    div[data-testid="metric-container"] > label { color: #475569; font-weight: 600; text-transform: uppercase; }
    div[data-testid="metric-container"] > div { color: #023e8a; font-size: 2rem; font-weight: 700; }
    
    .water-banner {
        background: linear-gradient(90deg, #0077b6 0%, #00b4d8 100%);
        color: white; padding: 20px; border-radius: 10px; margin-bottom: 25px;
        display: flex; align-items: center; justify-content: space-between;
    }
    .custom-warning { background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 8px; border-left: 5px solid #ffeeba; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# FONCTIONS POUR GÉNÉRER LES PDF
# ==========================================
def create_pdf(dataframe, client_name):
    """PDF mte3 el tableau mte3 les alertes (Tab 1)"""
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(0, 119, 182)
    pdf.cell(0, 10, "AquaSense Pro - Rapport d'Audit", ln=True, align="C")
    
    pdf.set_font("Helvetica", "I", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, f"Client : {client_name} | Date : {datetime.now().strftime('%d/%m/%Y')}", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(0, 119, 182)
    pdf.set_text_color(255, 255, 255)
    
    col_widths = [25, 35, 30, 30, 50]
    headers = ["Date", "Zone", "Débit (m3/h)", "Coût (DT)", "Statut"]
    
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, header, border=1, fill=True, align="C")
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(0, 0, 0)
    fill = False
    
    for _, row in dataframe.iterrows():
        date_str = row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else ''
        zone = str(row['Zone'])
        debit = f"{row['Débit m³/h']:.2f}"
        cout = f"{row['Coût (DT/mois)']:.0f}"
        statut = str(row['Statut'])
        
        pdf.set_fill_color(240, 247, 255) if fill else pdf.set_fill_color(255, 255, 255)
        
        pdf.cell(col_widths[0], 8, date_str, border=1, fill=fill, align="C")
        pdf.cell(col_widths[1], 8, zone, border=1, fill=fill, align="C")
        pdf.cell(col_widths[2], 8, debit, border=1, fill=fill, align="C")
        pdf.cell(col_widths[3], 8, cout, border=1, fill=fill, align="C")
        pdf.cell(col_widths[4], 8, statut, border=1, fill=fill, align="C")
        pdf.ln()
        fill = not fill
        
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    total = dataframe[dataframe['Statut'] != 'Résolue']['Coût (DT/mois)'].sum()
    pdf.cell(0, 10, f"Total des pertes actives : {total:,.0f} DT / mois", ln=True, align="R")
    
    return bytes(pdf.output())

def create_roi_pdf(pct_fix, eau_sauvee, argent_sauve, bouteilles, piscines, personnes, client_name):
    """PDF mte3 el simulation (Tab 2)"""
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(0, 119, 182)
    pdf.cell(0, 10, "AquaSense Pro - Rapport de Simulation ROI", ln=True, align="C")
    
    pdf.set_font("Helvetica", "I", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, f"Client : {client_name} | Date : {datetime.now().strftime('%d/%m/%Y')}", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, f"Scenario de reparation : {pct_fix}% des fuites", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"- Eau sauvee par mois : {eau_sauvee:,.0f} Litres", ln=True)
    pdf.cell(0, 10, f"- Argent sauve par mois : {argent_sauve:,.0f} DT", ln=True)
    pdf.cell(0, 10, f"- Economies sur 1 an : {argent_sauve*12:,.0f} DT", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Impact Environnemental :", ln=True)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"- {bouteilles:,.0f} bouteilles d'eau de 1.5L", ln=True)
    pdf.cell(0, 10, f"- {piscines:.1f} piscines olympiques", ln=True)
    pdf.cell(0, 10, f"- Consommation annuelle de {personnes:.0f} personnes", ln=True)
    
    return bytes(pdf.output())

# ==========================================
# INITIALISATION DB & IA (IN-MEMORY)
# ==========================================
@st.cache_resource(show_spinner="Initialisation de la base de données...")
def init_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, nom TEXT, secteur TEXT, ville TEXT, tarif REAL);
    CREATE TABLE IF NOT EXISTS compteurs(id INTEGER PRIMARY KEY, client_id INT, zone TEXT);
    CREATE TABLE IF NOT EXISTS releves(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME, vol REAL);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT, pwd TEXT, role TEXT, client_id INT, nom TEXT);
    CREATE TABLE IF NOT EXISTS alertes(id INTEGER PRIMARY KEY AUTOINCREMENT, cid INT, ts DATETIME, score REAL, fuite REAL, cout REAL, statut TEXT DEFAULT 'Nouvelle', maintenance_note TEXT DEFAULT '');
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
# LOGIN
# ==========================================
for k in ("email","role","nom","cid"):
    st.session_state.setdefault(k, None)

if not st.session_state.email:
    col1, col2, col3 = st.columns([1,1.5,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center; color: #0077b6;'>💧 AquaSense Pro</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #64748b;'>La gestion intelligente de l'eau pour les entreprises.</p>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("<h3 style='text-align: center;'>Connexion</h3>", unsafe_allow_html=True)
            with st.form("login"):
                e = st.text_input("📧 Email", "admin@aquasense.tn")
                p = st.text_input("🔒 Mot de passe", "admin123", type="password")
                if st.form_submit_button("Accéder au tableau de bord", width='stretch', type="primary"):
                    row = pd.read_sql("SELECT * FROM users WHERE email=? AND pwd=?", conn, params=(e, p))
                    if not row.empty:
                        st.session_state.update(email=row.iloc[0]['email'], role=row.iloc[0]['role'], nom=row.iloc[0]['nom'], cid=row.iloc[0]['client_id'])
                        st.rerun()
                    else: st.error("❌ Identifiants invalides.")
        st.info("💡 **Comptes :**\nAdmin: admin@aquasense.tn / admin123\nClient Hôtel: hotel@aquasense.tn / hotel123")
    st.stop()

# ==========================================
# SIDEBAR
# ==========================================
with st.sidebar:
    st.markdown("<h2>💧 AquaSense</h2>", unsafe_allow_html=True)
    st.markdown(f"**👤 {st.session_state.nom}** ({st.session_state.role.capitalize()})")
    
    if st.session_state.role == "admin":
        st.markdown("---")
        st.markdown("### 📤 Importer données")
        uploaded_file = st.file_uploader("Excel / CSV", type=["csv", "xlsx"])
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
                except Exception as e: st.error(f"Erreur : {e}")
        st.markdown("---")

    if st.button("🚪 Déconnexion", width='stretch'):
        for k in ("email","role","nom","cid"): st.session_state[k]=None
        st.rerun()

# ==========================================
# MAIN DASHBOARD & TABS
# ==========================================
where = "" if st.session_state.role=="admin" else f"WHERE c.client_id={st.session_state.cid}"

st.markdown("""
<div class="water-banner">
    <div style="display: flex; align-items: center;">
        <div style="font-size: 2rem; margin-right: 15px;">🌍</div>
        <div><b>Le saviez-vous ?</b> En Tunisie, une fuite non détectée gaspille jusqu'à <b>200 Litres/jour</b>. Chaque goutte compte.</div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown(f"<h1>Tableau de Bord — {st.session_state.nom}</h1>", unsafe_allow_html=True)

tab_dash, tab_roi, tab_chat = st.tabs(["📊 Tableau de Bord", "💰 Impact & ROI", "💬 Support & Chat"])

# ------------------------------------------
# TAB 1 : DASHBOARD (M3a PDF mte3 les alertes)
# ------------------------------------------
with tab_dash:
    where_kpi = where + (" AND " if where else "WHERE ") + "a.statut != 'Résolue'"
    k = pd.read_sql(f"SELECT COUNT(*) n, COALESCE(SUM(a.cout),0) c, COALESCE(SUM(a.fuite),0) f FROM alertes a JOIN compteurs c ON c.id=a.cid {where_kpi}", conn).iloc[0]
    
    litres_perdus_mois = k['f'] * 24 * 30 * 1000 
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🚨 Fuites Actives", int(k['n']))
    col2.metric("💧 Eau Perdue / mois", f"{litres_perdus_mois:,.0f} L")
    col3.metric("💸 Coût Mensuel", f"{k['c']:,.0f} DT")
    col4.metric("💰 Économies / An", f"{k['c']*12:,.0f} DT")
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("### 🚨 Alertes & Actions")
    al = pd.read_sql(f"SELECT a.id, a.ts AS Date, cl.nom AS Client, c.zone AS Zone, ROUND(a.score,3) AS Score, ROUND(a.fuite,2) AS 'Débit m³/h', ROUND(a.cout,0) AS 'Coût (DT/mois)', a.statut AS Statut, a.maintenance_note AS 'Note Maintenance' FROM alertes a JOIN compteurs c ON c.id=a.cid JOIN clients cl ON cl.id=c.client_id {where} ORDER BY a.cout DESC", conn)
    
    if not al.empty:
        al['Date'] = pd.to_datetime(al['Date'])
        al['Note Maintenance'] = al['Note Maintenance'].fillna('') 
        al['Statut'] = al['Statut'].fillna('Nouvelle')
        al = al.reset_index(drop=True)
        
        col_pdf, col_csv = st.columns([1, 4])
        with col_pdf:
            pdf_bytes = create_pdf(al, st.session_state.nom)
            st.download_button(
                label="📄 Télécharger le rapport (PDF)",
                data=pdf_bytes,
                file_name='rapport_aquasense.pdf',
                mime='application/pdf',
                type="primary"
            )

        edited_al = st.data_editor(
            al,
            column_config={
                "id": None, 
                "Date": st.column_config.DatetimeColumn("Date", format="D MMM YYYY, HH:mm"),
                "Score": st.column_config.NumberColumn("Confiance IA", format="%.3f"),
                "Débit m³/h": st.column_config.NumberColumn("Débit", format="%.2f"),
                "Coût (DT/mois)": st.column_config.NumberColumn("Coût", format="%.0f DT"),
                "Statut": st.column_config.SelectboxColumn("État", options=["Nouvelle", "En cours", "Résolue"], required=True),
                "Note Maintenance": st.column_config.TextColumn("Note Maintenance", disabled=True) 
            },
            hide_index=True, width='stretch'
        )
        
        changed = False
        for i in range(len(al)):
            if al.loc[i, 'Statut'] != edited_al.loc[i, 'Statut']:
                conn.execute("UPDATE alertes SET statut = ? WHERE id = ?", (edited_al.loc[i, 'Statut'], al.loc[i, 'id']))
                if edited_al.loc[i, 'Statut'] == 'Résolue':
                    cout_sauve = al.loc[i, 'Coût (DT/mois)']
                    litres_sauves = al.loc[i, 'Débit m³/h'] * 24 * 30 * 1000
                    st.toast(f"🎉 Excellente décision ! Vous venez d'économiser {litres_sauves:,.0f} L d'eau et {cout_sauve:,.0f} DT/mois.", icon="✅")
                changed = True
        if changed:
            conn.commit()
            st.rerun()

        st.markdown("---")
        st.markdown("### 🛠️ Assigner un Ticket de Maintenance")
        st.info("Sélectionnez une fuite active pour assigner un technicien et ajouter une note.")
        
        al_actives = al[al['Statut'] != 'Résolue']
        if not al_actives.empty:
            al_actives['Option'] = al_actives['Zone'] + " (Détecté le " + al_actives['Date'].dt.strftime('%d/%m/%Y') + ")"
            
            with st.form("maintenance_form"):
                selected_fuite = st.selectbox("Choisir la fuite :", al_actives['Option'].tolist())
                technicien = st.text_input("Nom du technicien / Plombier :")
                note = st.text_area("Détails de l'intervention :")
                
                if st.form_submit_button("Créer le Ticket & Passer en 'En cours'", type="primary"):
                    if technicien and note:
                        fuite_id = al_actives[al_actives['Option'] == selected_fuite]['id'].values[0]
                        full_note = f"[{technicien}] : {note}"
                        conn.execute("UPDATE alertes SET statut = 'En cours', maintenance_note = ? WHERE id = ?", (full_note, fuite_id))
                        conn.commit()
                        st.success("✅ Ticket créé avec succès ! Le statut a été mis à jour.")
                        st.rerun()
                    else:
                        st.error("Veuillez remplir le nom du technicien et les détails.")
        else:
            st.success("✅ Toutes les fuites ont été résolues. Aucun ticket à créer.")

        st.markdown(f'<div class="custom-warning">⚠️ <b>Action Requise :</b> Ces fuites vous coûtent de l\'argent. Passez le statut à "Résolue" une fois réparées.</div>', unsafe_allow_html=True)
    else:
        st.success("✅ Aucune fuite active. Votre installation est optimale.")

# ------------------------------------------
# TAB 2 : IMPACT & ROI (M3a PDF mte3 el simulation)
# ------------------------------------------
with tab_roi:
    st.markdown("### 📈 Simulateur d'Impact Environnemental & Financier")
    st.info("Utilisez ce simulateur pour présenter les bénéfices de la réparation à votre direction.")
    
    al_active = pd.read_sql(f"SELECT ROUND(a.cout,0) AS cout, ROUND(a.fuite,2) AS fuite FROM alertes a JOIN compteurs c ON c.id=a.cid {where_kpi}", conn)
    
    if not al_active.empty:
        total_cout_mois = al_active['cout'].sum()
        total_eau_mois = al_active['fuite'].sum() * 24 * 30 * 1000 
        
        col_r1, col_r2 = st.columns([1, 1])
        
        with col_r1:
            st.markdown("#### 🎯 Simulateur de Réparation")
            pct_fix = st.slider("Pourcentage de fuites réparées", 0, 100, 50, step=10)
            
            eau_sauvee = total_eau_mois * (pct_fix / 100)
            argent_sauve = total_cout_mois * (pct_fix / 100)
            
            st.metric("💧 Eau Sauvée / mois", f"{eau_sauvee:,.0f} Litres")
            st.metric("💰 Argent Sauvé / mois", f"{argent_sauve:,.0f} DT")

            st.markdown("<br>", unsafe_allow_html=True)
            
            bouteilles = eau_sauvee / 1.5 
            piscines = eau_sauvee / 2500000 
            personnes = eau_sauvee/365/150
            
            # BOUTON PDF JDID (Badalna el CSV b' PDF)
            pdf_roi_bytes = create_roi_pdf(pct_fix, eau_sauvee, argent_sauve, bouteilles, piscines, personnes, st.session_state.nom)
            st.download_button(
                label="📄 Télécharger ce rapport de simulation (PDF)",
                data=pdf_roi_bytes,
                file_name='rapport_roi_aquasense.pdf',
                mime='application/pdf',
                type="primary",
                width='stretch'
            )
            
        with col_r2:
            st.markdown("#### 🌍 Impact Environnemental")
            st.markdown(f"En réparant **{pct_fix}%** des fuites, votre entreprise économise :")
            
            st.success(f"💧 **{bouteilles:,.0f}** bouteilles d'eau de 1.5L")
            st.success(f"🏊 **{piscines:.1f}** piscines olympiques d'eau")
            st.success(f"🌳 L'équivalent de la consommation annuelle de **{personnes:.0f}** personnes")
            
            st.caption("Ces chiffres peuvent être intégrés dans votre rapport RSE.")
    else:
        st.success("✅ Vous n'avez aucune fuite active. Impact maximal !")

# ------------------------------------------
# TAB 3 : CHAT & SUPPORT
# ------------------------------------------
with tab_chat:
    st.markdown("### 💬 Support & Assistant IA")
    
    if st.session_state.role == "admin":
        clients_list = pd.read_sql("SELECT id, nom FROM clients", conn)
        selected_client_name = st.selectbox("Sélectionnez un client :", clients_list['nom'])
        chat_cid = int(clients_list[clients_list['nom'] == selected_client_name]['id'].iloc[0])
    else:
        chat_cid = st.session_state.cid

    chat_box = st.container(height=400)
    with chat_box:
        for m in st.session_state.chat_history[chat_cid]:
            with st.chat_message("user" if m['role'] == st.session_state.role else "assistant"):
                st.write(f"**{m['sender']}** ({m['ts']})")
                st.write(m['text'])

    if st.session_state.role == "client":
        st.markdown("**💡 Actions rapides :**")
        col_b1, col_b2, col_b3 = st.columns(3)
        prompt_btn = None
        if col_b1.button("🔧 Réparer une fuite", width='stretch'): prompt_btn = "Comment faire pour réparer une fuite ?"
        elif col_b2.button("💰 Tarifs", width='stretch'): prompt_btn = "Quel est le prix de l'abonnement ?"
        elif col_b3.button("🚨 Urgence", width='stretch'): prompt_btn = "J'ai besoin d'une intervention urgente."
        
        if prompt_btn:
            ts_now = datetime.now().strftime('%H:%M')
            st.session_state.chat_history[chat_cid].append({"role": "client", "sender": st.session_state.nom, "text": prompt_btn, "ts": ts_now})
            st.session_state.chat_history[chat_cid].append({"role": "assistant", "sender": "Bot AquaSense (IA)", "text": "Un technicien va vous répondre sous peu.", "ts": ts_now})
            st.rerun()

    if prompt := st.chat_input("Posez votre question ici..."):
        ts_now = datetime.now().strftime('%H:%M')
        st.session_state.chat_history[chat_cid].append({"role": st.session_state.role, "sender": st.session_state.nom, "text": prompt, "ts": ts_now})
        
        if st.session_state.role == "client":
            query_top = pd.read_sql(f"SELECT c.zone, a.cout FROM alertes a JOIN compteurs c ON c.id=a.cid WHERE c.client_id={chat_cid} AND a.statut != 'Résolue' ORDER BY a.cout DESC LIMIT 3", conn)
            data_context = "Voici les fuites ACTIVES détectées : \n"
            if not query_top.empty:
                for _, row in query_top.iterrows():
                    data_context += f"- Zone: {row['zone']}, Coût: {row['cout']:.0f} DT/mois\n"
            else:
                data_context = "Aucune fuite active."

            try:
                api_key = st.secrets.get("GROQ_API_KEY", "")
                if api_key == "":
                    bot_reply = "Erreur technique : Veuillez configurer votre clé API Groq."
                else:
                    client_ai = Groq(api_key=api_key)
                    system_prompt = f"Tu es le 'Bot AquaSense'. Tu parles à : {st.session_state.nom}. Données ACTIVES :\n{data_context}\nRéponds de manière professionnelle."
                    chat_completion = client_ai.chat.completions.create(
                        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                        model="openai/gpt-oss-120b",
                    )
                    bot_reply = chat_completion.choices[0].message.content
            except Exception as e:
                bot_reply = f"Erreur technique : {str(e)}"
            
            st.session_state.chat_history[chat_cid].append({"role": "assistant", "sender": "Bot AquaSense (IA)", "text": bot_reply, "ts": ts_now})
        
        st.rerun()
