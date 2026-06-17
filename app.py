# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # --- Genereer contrast-voorwerking voor Multi-Pass OCR ---
        img_gray_orig = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        img_enhanced = cv2.adaptiveThreshold(
            img_gray_orig, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        img_canvas = img_np.copy()
        
    except Exception as e:
        st.error(f"❌ Fout bij het openen van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geladen. Analyse start...")

    # =====================================================================
    # CRUCIALE VERBETERING: Initialiseer ALLE variabelen vooraf om NameErrors te voorkomen!
    # =====================================================================
    volledige_tekst = ""
    txt_lower = ""
    alle_teksten = []
    tijd_regels = []
    ruwe_regels = []
    alle_losse_woorden = []
    
    organisator_gevonden = False
    evenementnaam_gevonden = False
    datum_gevonden = False
    tijd_gevonden = False
    locatie_gevonden = False
    telefoon_gevonden = False
    logo_gevonden = False
    zesde_traditie_score = 0
    locatie_score = 0
    # =====================================================================

    # Twee kolommen: links de Checklist Matrix, rechts het Voorbeeldscherm
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Matrix Resultaten")
        
        if reader is None:
            st.error("OCR-module is offline.")
        else:
            with st.spinner("Tekst scannen en analyseren via Multi-Pass OCR..."):
                try:
                    # Multi-Pass OCR
                    ocr_results_orig = reader.readtext(img_np, detail=1)
                    ocr_results_enh = reader.readtext(img_enhanced, detail=1)
                    ocr_results = ocr_results_orig + ocr_results_enh
                    
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    st.caption("Hieronder zie je exact wat de scanner regel-voor-regel aantreft:")
                    
                    for (bbox, text, prob) in ocr_results:
                        ruwe_regels.append(text)
                        st.write(f"• OCR leest: `{text}`")
                        
                        # Normalisatie van tekst
                        txt_clean = text
                        txt_clean = txt_clean.replace("O", "0").replace("o", "0")
                        txt_clean = txt_clean.replace("juii", "juli").replace("juIi", "juli").replace("ju1i", "juli")
                        
                        txt_clean = txt_clean.lower()
                        txt_clean = txt_clean.replace("t0 t", "tot").replace("t0t", "tot")
                        
                        # Spaties binnen tijden herstellen
                        txt_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', txt_clean)
                        txt_clean = txt_clean.replace(" : ", ":").replace(": ", ":").replace(" :", ":")
                        txt_clean = txt_clean.replace(" . ", ":").replace(". ", ":").replace(" .", ":")
                        txt_clean = re.sub(r'(\d{1,2})\s+(\d{2})', r'\1:\2', txt_clean)
                        txt_clean = txt_clean.replace(';', ':').replace('.', ':')
                        
                        alle_teksten.append(txt_clean)
                        alle_losse_woorden.extend(txt_clean.split())
                        
                        # Coördinaten en kaders
                        tl = tuple(map(int, bbox[0]))
                        br = tuple(map(int, bbox[2]))
                        cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                        
                        # Tijd regex
                        tijd_matches = re.findall(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean)
                        if tijd_matches:
                            tijd_regels.append(txt_clean)
                            cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

                    # Zet de hoofdstrings direct klaar
                    volledige_tekst = " ".join(alle_teksten)
                    txt_lower = volledige_tekst.lower() # <-- Nu direct veilig gevuld!
                    
                    st.markdown("---")
                    st.markdown("#### 📋 Matrix Checklist")
                    
                    # --- 1. ORGANISATOR CHECK ---
                    organisator_match = re.search(r'CA[\s\-]+[A-Za-z0-9]+', volledige_tekst, re.IGNORECASE)
                    if organisator_match:
                        organisator_gevonden = True
                        st.success(f"✅ **Organisator gevonden:** {organisator_match.group(0).upper()}")
                    else:
                        ca_pattern = re.search(r'CA\s+([A-Za-z]+)', volledige_tekst, re.IGNORECASE)
                        if ca_pattern:
                            organisator_gevonden = True
                            st.success(f"✅ **Organisator gevonden (fuzzy):** {ca_pattern.group(0).upper()}")
                        else:
                            st.warning("⚠️ **Geen specifieke CA-groep herkend** (bijv. 'CA Hoorn')")

                    # --- 2. EVENEMENTNAAM CHECK ---
                    evenement_woorden = ["workshop", "bijeenkomst", "ontmoeting", "spreker", "meeting", "actie", "bijeen", "bbq", "fundraiser", "conventie", "feest", "countdown"]
                    if any(woord in txt_lower for woord in evenement_woorden):
                        evenementnaam_gevonden = True
                        st.success(f"✅ **Evenementnaam/type gevonden**")
                    else:
                        st.info("ℹ️ **Geen duidelijke evenementnaam herkend**")

                    # --- 3. DATUM CHECK ---
                    maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
                    datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
                    if datum_match:
                        datum_gevonden = True
                        st.success(f"✅ **Datum gevonden:** {datum_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen datum gevonden**")

                    # --- 4. TIJD CHECK ---
                    tijd_regels = list(set(tijd_regels))
                    if len(tijd_regels) >= 2:
                        tijd_gevonden = True
                        st.success(f"✅ **Tijdsbereik gevonden:** {tijd_regels[0]} tot {tijd_regels[1]}")
                    elif len(tijd_regels) == 1:
                        tijd_gevonden = True
                        st.info(f"ℹ️ **Enkele tijd gevonden:** {tijd_regels[0]} (Geen eindtijd herleid)")
                    else:
                        st.warning("⚠️ **Geen tijdstip of bereik kunnen detecteren**")

                    # --- 5. LOCATIE CHECK ---
                    locatie_woorden = ["strand", "centrum", "kerk", "zaal", "hotel", "gebouw", "hoorn", "stadsstrand", "buurthuis", "plein"]
                    for woord in locatie_woorden:
                        if woord in txt_lower:
                            locatie_score += 1
                    
                    if "stadsstrand" in txt_lower and "hoorn" in txt_lower:
                        locatie_score += 2
                    elif simple_fuzzy_match("stadsstrand hoorn", volledige_tekst) > 50:
                        locatie_score += 1
                    
                    if locatie_score >= 2:
                        locatie_gevonden = True
                        st.success(f"✅ **Locatie gevonden** (score: {locatie_score}/2+)")
                    else:
                        st.warning(f"⚠️ **Locatie niet duidelijk herkend** (score: {locatie_score}/2+)")

                    # --- 6. TELEFOONNUMMER CHECK ---
                    telefoon_match = re.search(r'(06[- ]*\d{8}|\+31[- ]*6[- ]*\d{8})', volledige_tekst)
                    if telefoon_match:
                        telefoon_gevonden = True
                        st.success(f"✅ **Telefoonnummer gevonden:** {telefoon_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen telefoonnummer gevonden**")

                    # --- 7. ROBUUSTE 6E TRADITIE CHECK ---
                    traditie_keywords = ["6e", "traditie", "verbonden", "kerken", "sekten", "politieke", "hulpverlenende", "instanties"]
                    gevonden_traditie_woorden = []
                    
                    for kw in traditie_keywords:
                        for woord in alle_losse_woorden:
                            if kw in woord or word_similarity(kw, woord) >= 0.75:
                                gevonden_traditie_woorden.append(kw)
                                break
                    
                    zesde_traditie_score = len(set(gevonden_traditie_woorden))
                    if zesde_traditie_score >= 5:
                        st.success(f"✅ **6e traditie aanwezig:** Disclaimer succesvol gedetecteerd ({zesde_traditie_score}/{len(traditie_keywords)} trefwoorden).")
                    elif zesde_traditie_score >= 3:
                        st.warning(f"⚠️ **6e traditie gedeeltelijk of slecht leesbaar herkend** (Gevonden trefwoorden: {', '.join(set(gevonden_traditie_woorden))})")
                    else:
                        st.error("❌ **6e traditie ontbreekt of is onleesbaar:** Denk aan de verplichte CA-disclaimer!")

                    # --- 8. ONLINE ELEMENTEN ---
                    st.markdown("---")
                    st.markdown("#### 🌐 Online Elementen")
                    if "zoom" in txt_lower or "meet" in txt_lower:
                        st.success("✅ **Zoom/online link gevonden**")
                    else:
                        st.info("ℹ️ **Geen Zoom-link gedetecteerd** (niet verplicht)")

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")

        # ---- LOGO CONTROLE ----
        st.markdown("### 🖼️ CA-Logo Controle")
        logo_score = 0
        
        if logos:
            with st.spinner("Zoeken naar CA-logo via beeldherkenning..."):
                try:
                    for logo in logos:
                        for threshold in [0.50, 0.55, 0.65]:
                            res = cv2.matchTemplate(img_gray_orig, logo, cv2.TM_CCOEFF_NORMED)
                            loc = np.where(res >= threshold)
                            if len(loc[0]) > 0:
                                h, w = logo.shape
                                pt = (loc[1][0], loc[0][0])
                                cv2.rectangle(img_canvas, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), 4)
                                logo_score += 2.5
                                break
                        if logo_score > 0:
                            break
                except Exception:
                    pass

        # Tekstuele herkenning logo
        logo_keywords = ["hoop", "vertrouwen", "moed", "cocaine", "anonymous"]
        gevonden_logo_woorden = []
        for kw in logo_keywords:
            for woord in alle_losse_woorden:
                if word_similarity(kw, woord) >= 0.75:
                    gevonden_logo_woorden.append(kw)
                    break
                    
        logo_tekst_score = len(set(gevonden_logo_woorden))
        if logo_tekst_score >= 2:
            logo_score += 1.5
        if logo_tekst_score >= 3:
            logo_score += 1.0

        if logo_score >= 3.0:
            logo_gevonden = True
            st.success(f"✅ **CA-logo aanwezig** (Gevalideerd via gecombineerde matrix-score: {logo_score}/5.0)")
        elif logo_score >= 1.5:
            logo_gevonden = True
            st.warning(f"⚠️ **CA-logo waarschijnlijk aanwezig** (Alleen cirkeltekst herkend: {', '.join(set(gevonden_logo_woorden))})")
        else:
            st.warning("⚠️ **Geen officieel CA-logo of cirkeltekst herkend**")

        # --- TOTAAL RAPPORT ---
        st.markdown("---")
        st.markdown("#### 📊 Samenvattend Rapport")
        
        kritiek_geslaagd = logo_gevonden and zesde_traditie_score >= 5
        evenement_geslaagd = organisator_gevonden and datum_gevonden and tijd_gevonden and locatie_gevonden
        
        if kritiek_geslaagd and evenement_geslaagd:
            st.success("🎉 **FLYER VOLDOET AAN ALLE MATRIX-EISEN!**")
        elif kritiek_geslaagd:
            st.warning("⚠️ **Flyer voldoet aan kritieke eisen, maar mist enkele evenementdetails**")
        else:
            st.error("❌ **Flyer voldoet NIET aan de matrix-eisen**")
        
        with st.expander("📋 Bekijk gedetailleerd rapport"):
            st.markdown("**KRITIEKE CONTROLES**")
            st.write(f"{'✅' if logo_gevonden else '❌'} CA-logo")
            st.write(f"{'✅' if zesde_traditie_score >= 5 else '⚠️' if zesde_traditie_score >= 3 else '❌'} 6e traditie (Trefwoorden: {zesde_traditie_score}/8)")
            
            st.markdown("**EVENEMENT**")
            st.write(f"{'✅' if organisator_gevonden else '❌'} Organisator")
            st.write(f"{'✅' if evenementnaam_gevonden else 'ℹ️'} Evenementnaam")
            st.write(f"{'✅' if datum_gevonden else '❌'} Datum")
            st.write(f"{'✅' if tijd_gevonden else '❌'} Tijd")
            st.write(f"{'✅' if locatie_gevonden else '⚠️'} Locatie (score: {locatie_score}/2+)")
            
            st.markdown("**CONTACT**")
            st.write(f"{'✅' if telefoon_gevonden else '⚠️'} Telefoon")
            
            st.markdown("**ONLINE**")
            if "zoom" in txt_lower or "meet" in txt_lower:
                st.write("✅ Zoom-link")
            else:
                st.write("ℹ️ Geen Zoom-link")

# En vanaf hier pakt jouw bestaande `with col2:` de draad weer probleemloos op!
