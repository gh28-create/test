import streamlit as st
import pandas as pd, numpy as np, sqlite3, random, os
from sklearn.ensemble import IsolationForest
from datetime import datetime, timedelta
import plotly.express as px
from groq import Groq
from fpdf import FPDF  # <-- JDID

st.set_page_config(page_title="AquaSense Pro", page_icon="💧", layout="wide")

# ==========================================
# FONCTION PDF
# ==========================================
def create_pdf(dataframe, client_name):
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
    headers = ["Date", "Zone", "Debit (m3/h)", "Cout (DT)", "Statut"]
    
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, header, border=1, fill=True, align="C")
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(0, 0, 0)
    fill = False
    for _, row in dataframe.iterrows():
        date_str = row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else ''
        pdf.set_fill_color(240, 247, 255) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.cell(col_widths[0], 8, date_str, border=1, fill=fill, align="C")
        pdf.cell(col_widths[1], 8, str(row['Zone']), border=1, fill=fill, align="C")
        pdf.cell(col_widths[2], 8, f"{row['Debit']:.2f}", border=1, fill=fill, align="C")
        pdf.cell(col_widths[3], 8, f"{row['Cout']:.0f}", border=1, fill=fill, align="C")
        pdf.cell(col_widths[4], 8, str(row['Statut']), border=1, fill=fill, align="C")
        pdf.ln()
        fill = not fill
        
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    total = dataframe[dataframe['Statut'] != 'Résolue']['Cout'].sum()
    pdf.cell(0, 10, f"Total des pertes actives : {total:,.0f} DT / mois", ln=True, align="R")
    return bytes(pdf.output())

# ==========================================
# INITIALISATION DB (Bla Maintenance Note)
# ==========================================
@st.cache_resource(show_spinner="Chargement...")
def init_db_test1():
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
    
    # Generate Alerts
    conn.execute("DELETE FROM alertes")
    df = pd.read_sql("SELECT r.cid, r.ts, r.vol, cl.tarif FROM releves r JOIN compteurs c ON c.id=r.cid JOIN clients cl ON cl.id=c.client_id", conn)
    if not df.empty:
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
    return conn

conn = init_db_test1()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = {1: [], 2: [], 3: [], 4: []}

for k in ("email","role","nom","cid"):
    st.session_state.setdefault(k, None)

if not st.session_state.email:
    st.title("💧 AquaSense Pro — Test PDF")
    with st.form("login"):
        e = st.text_input("Email", "admin@aquasense.tn")
        p = st.text_input("Mot de passe", "admin123", type="password")
        if st.form_submit_button("Connexion"):
            row = pd.read_sql("SELECT * FROM users WHERE email=? AND pwd=?", conn, params=(e, p))
            if not row.empty:
                st.session_state.update(email=row.iloc[0]['email'], role=row.iloc[0]['role'], nom=row.iloc[0]['nom'], cid=row.iloc[0]['client_id'])
                st.rerun()
    st.stop()

with st.sidebar:
    st.write(f"👤 {st.session_state.nom}")
    if st.button("Déconnexion", use_container_width=True):
        for k in ("email","role","nom","cid"): st.session_state[k]=None
        st.rerun()

where = "" if st.session_state.role=="admin" else f"WHERE c.client_id={st.session_state.cid}"
st.title(f"Tableau de Bord — {st.session_state.nom}")

tab_dash, tab_roi, tab_chat = st.tabs(["📊 Tableau de Bord", "💰 Impact & ROI", "💬 Chat"])

with tab_dash:
    where_kpi = where + (" AND " if where else "WHERE ") + "a.statut != 'Résolue'"
    
    # Jbna el données (Bla Note Maintenance)
    al = pd.read_sql(f"SELECT a.id, a.ts AS Date, cl.nom AS Client, c.zone AS Zone, ROUND(a.score,3) AS Score, ROUND(a.fuite,2) AS Debit, ROUND(a.cout,0) AS Cout, a.statut AS Statut FROM alertes a JOIN compteurs c ON c.id=a.cid JOIN clients cl ON cl.id=c.client_id {where} ORDER BY a.cout DESC", conn)
    
    if not al.empty:
        al['Date'] = pd.to_datetime(al['Date'])
        al['Client'] = al['Client'].astype(str)
        al['Zone'] = al['Zone'].astype(str)
        al['Score'] = pd.to_numeric(al['Score'], errors='coerce').fillna(0)
        al['Debit'] = pd.to_numeric(al['Debit'], errors='coerce').fillna(0)
        al['Cout'] = pd.to_numeric(al['Cout'], errors='coerce').fillna(0)
        al['Statut'] = al['Statut'].astype(str).replace('None', 'Nouvelle')
        al = al.reset_index(drop=True)

        # BOUTON PDF HNA
        col_pdf, _ = st.columns([1, 4])
        with col_pdf:
            pdf_bytes = create_pdf(al, st.session_state.nom)
            st.download_button(
                label="📄 Télécharger PDF",
                data=pdf_bytes,
                file_name='rapport.pdf',
                mime='application/pdf',
                type="primary"
            )

        # DATA EDITOR (Bla Maintenance)
        edited_al = st.data_editor(
            al,
            column_config={
                "Date": st.column_config.DatetimeColumn("Date", format="D MMM YYYY, HH:mm"),
                "Score": st.column_config.NumberColumn("Confiance IA", format="%.3f"),
                "Debit": st.column_config.NumberColumn("Débit (m³/h)", format="%.2f"),
                "Cout": st.column_config.NumberColumn("Coût (DT/mois)", format="%.0f DT"),
                "Statut": st.column_config.SelectboxColumn("État", options=["Nouvelle", "En cours", "Résolue"], required=True)
            },
            disabled=["id", "Date", "Client", "Zone", "Score", "Debit", "Cout"],
            hide_index=True, 
            use_container_width=True, 
            key="editor_alertes_test1"
        )
        
        changed = False
        for i in range(len(al)):
            if al.loc[i, 'Statut'] != edited_al.loc[i, 'Statut']:
                conn.execute("UPDATE alertes SET statut = ? WHERE id = ?", (edited_al.loc[i, 'Statut'], al.loc[i, 'id']))
                changed = True
        if changed:
            conn.commit()
            st.rerun()
    else:
        st.success("✅ Aucune fuite.")

with tab_roi:
    st.write("ROI (Kima 9bal)")
    
with tab_chat:
    st.write("Chat (Kima 9bal)")
