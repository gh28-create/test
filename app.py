# ------------------------------------------
# TAB 1 : DASHBOARD (FIX 100% : st.dataframe + Formulaire)
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
    
    al = pd.read_sql(f"SELECT a.id, a.ts AS Date, cl.nom AS Client, c.zone AS Zone, ROUND(a.score,3) AS Score, ROUND(a.fuite,2) AS Debit, ROUND(a.cout,0) AS Cout, a.statut AS Statut FROM alertes a JOIN compteurs c ON c.id=a.cid JOIN clients cl ON cl.id=c.client_id {where} ORDER BY a.cout DESC", conn)
    
    if not al.empty:
        # 1. NDHADHROU EL DATA (Bch ma ykounch famma ay None)
        al['Date'] = pd.to_datetime(al['Date'])
        al['Client'] = al['Client'].astype(str)
        al['Zone'] = al['Zone'].astype(str)
        al['Score'] = pd.to_numeric(al['Score'], errors='coerce').fillna(0)
        al['Debit'] = pd.to_numeric(al['Debit'], errors='coerce').fillna(0)
        al['Cout'] = pd.to_numeric(al['Cout'], errors='coerce').fillna(0)
        al['Statut'] = al['Statut'].astype(str).replace('None', 'Nouvelle')
        al = al.reset_index(drop=True)

        # 2. BOUTON PDF
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

        # 3. AFFICHAGE B' st.dataframe (MCH data_editor) - Ma fihch el bug mte3 None
        display_al = al.drop(columns=['id']).copy()
        
        # Nformatiw les colonnes bch ybanou behyin w ma yetblech Streamlit
        display_al['Date'] = display_al['Date'].dt.strftime('%d/%m/%Y %H:%M')
        display_al['Score'] = display_al['Score'].apply(lambda x: f"{x:.3f}")
        display_al['Debit'] = display_al['Debit'].apply(lambda x: f"{x:.2f} m³/h")
        display_al['Cout'] = display_al['Cout'].apply(lambda x: f"{x:,.0f} DT")
        
        # Nbaddlou esma2 el colonnes lel affichage
        display_al = display_al.rename(columns={
            'Debit': 'Débit', 
            'Cout': 'Coût (DT/mois)', 
            'Score': 'Confiance IA'
        })
        
        st.dataframe(display_al, use_container_width=True, hide_index=True)

        # 4. FORMULAIRE POUR BADDEL EL STATUT
        st.markdown("---")
        st.markdown("### ✏️ Mettre à jour le statut d'une fuite")
        
        al_actives = al[al['Statut'] != 'Résolue']
        if not al_actives.empty:
            al_actives['Option'] = al_actives['Zone'] + " (Détecté le " + al_actives['Date'].dt.strftime('%d/%m/%Y') + ")"
            
            with st.form("update_status_form"):
                col_sel, col_stat = st.columns(2)
                with col_sel:
                    selected_fuite = st.selectbox("Choisir la fuite :", al_actives['Option'].tolist())
                with col_stat:
                    new_status = st.selectbox("Nouveau statut :", ["En cours", "Résolue"])
                
                if st.form_submit_button("Mettre à jour", type="primary"):
                    fuite_id = al_actives[al_actives['Option'] == selected_fuite]['id'].values[0]
                    conn.execute("UPDATE alertes SET statut = ? WHERE id = ?", (new_status, fuite_id))
                    conn.commit()
                    if new_status == 'Résolue':
                        cout_sauve = al_actives[al_actives['id'] == fuite_id]['Cout'].values[0]
                        litres_sauves = al_actives[al_actives['id'] == fuite_id]['Debit'].values[0] * 24 * 30 * 1000
                        st.toast(f"🎉 Excellente décision ! Vous venez d'économiser {litres_sauves:,.0f} L d'eau et {cout_sauve:,.0f} DT/mois.", icon="✅")
                    st.rerun()
        else:
            st.success("✅ Toutes les fuites sont résolues.")

        st.markdown(f'<div class="custom-warning">⚠️ <b>Action Requise :</b> Ces fuites vous coûtent de l\'argent. Passez le statut à "Résolue" une fois réparées.</div>', unsafe_allow_html=True)
    else:
        st.success("✅ Aucune fuite active. Votre installation est optimale.")
