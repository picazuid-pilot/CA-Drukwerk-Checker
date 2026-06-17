import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import requests
import re
from difflib import SequenceMatcher

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Controleer de verplichte elementen en inhoud van de flyer matrix")

# 1. Cache de EasyOCR Reader
@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# 2. Functie om logo's veilig te downloaden van GitHub
@st.cache_data
def download_official_logos():
    logos = []
    urls = [
        "https://raw.githubusercontent.com/picazuid-pilot/CA-Drukwerk-Checker/main/logo1.png",
        "https://raw.githubusercontent.com/picazuid-pilot/CA-Drukwerk-Checker/main/logo2.png"
    ]
    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                img_bytes = np.frombuffer(response.content, dtype=np.uint8)
                img = cv2.imdecode(img_bytes, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    logos.append(img)
        except Exception:
            pass
    return logos

logos = download_official_logos()

# 3. Helperfunctie voor tekstgelijkenis (Fuzzy Match per woord)
def word_similarity(a, b):
    """Bereken hoe sterk twee woorden op elkaar lijken (0.0 - 1.0)"""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

# 4. Geavanceerde OCR-voorwerking
def preprocess_for_ocr(image):
    """Genereert geoptimaliseerde varianten voor de Multi-Pass OCR"""
    # 1. Opgeschaalde versie (Cubic interpolatie voor scherpte)
    scale = 2
    img_scaled = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    
    # 2. Grayscale & Adaptieve drempelwaarde (voor lichte tekst op lichte achtergrond)
    gray_scaled = cv2.cvtColor(img_scaled, cv2.COLOR_RGB2GRAY)
    img_enhanced = cv2.adaptiveThreshold(
        gray_scaled,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2
    )
    return img_scaled, img_enhanced

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # Voorbewerking uitvoeren
        img_ocr_scaled, img_ocr_enhanced = preprocess_for_ocr(img_np)
        
        # Canvas bepalen op basis van de opgeschaalde variant (zorgt voor scherpe kaders rechts)
        img_canvas = img_ocr_scaled.copy()
        img_gray_scaled = cv2.cvtColor(img_ocr_scaled, cv2.COLOR_RGB2GRAY)
        
    except Exception as e:
        st.error(f"❌ Fout bij het openen van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geladen. Multi-Pass Analyse start...")

    # Twee kolommen: links de Checklist Matrix, rechts het Voorbeeldscherm
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Matrix Resultaten")
        
        # --- INITIALISEER SCRIPTS EN LINKERBLOKKEN ---
        alle_opgeschoonde_woorden = []
        tijd_regels = []
        ruwe_regels_debug = []
        
        if reader is None:
            st.error("OCR-module is offline.")
        else:
            with st.spinner("Uitvoeren van Multi-Pass OCR (Origineel + Opgeschaald + Enhanced)..."):
                try:
                    # --- MULTI-PASS STRATEGIE ---
                    # Pass 1: Het origineel
                    res1 = reader.readtext(img_np, detail=1)
                    # Pass 2: De opgeschaalde variant
                    res2 = reader.readtext(img_ocr_scaled, detail=1)
                    # Pass 3: De adaptieve contrast variant (Cruciaal voor de zon/lichtblauwe tekst)
                    res3 = reader.readtext(img_ocr_enhanced, detail=1)
                    
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    st.caption("Gedetecteerde tekstflarden uit alle passes (inclusief normalisatie):")
                    
                    # Verwerk alle passes in één centrale loop
                    # Let op: Voor het tekenen van kaders gebruiken we res2 en res3 omdat die op de juiste schaal (x2) zitten
                    for pass_idx, ocr_res in enumerate([res1, res2, res3]):
                        # Bepaal de schaalfactor van deze specifieke pass ten opzichte van ons x2 canvas
                        # res1 moet x2 vermenigvuldigd worden om te matchen op het canvas, res2 en res3 zijn al x2.
                        scale_multiplier = 2.0 if pass_idx == 0 else 1.0
                        
                        for (bbox, text, prob) in ocr_res:
                            ruwe_regels_debug.append(f"[Pass {pass_idx+1}] {text}")
                            
                            # --- STAP 1: KRUCHTIGE TEXT-CLEANING EN NORMALISATIE ---
                            txt_clean = text.upper() # Naar uppercase voor makkelijkere vervangingen
                            txt_clean = txt_clean.replace("O", "0").replace("o", "0")
                            txt_clean = txt_clean.replace("JUII", "JULI").replace("JUII", "JULI").replace("JU1I", "JULI")
                            txt_clean = txt_clean.replace("T0 T", "TOT").replace("T0T", "TOT")
                            
                            # Tijdsnotaties opschonen (spaties tackelen)
                            txt_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', txt_clean)
                            txt_clean = txt_clean.replace(" : ", ":").replace(": ", ":").replace(" :", ":")
                            txt_clean = txt_clean.replace(" . ", ":").replace(". ", ":").replace(" .", ":")
                            txt_clean = re.sub(r'(\d{1,2})\s+(\d{2})', r'\1:\2', txt_clean)
                            txt_clean = txt_clean.replace(';', ':').replace('.', ':')
                            
                            # Log de schone variant live op het scherm
                            st.write(f"• `{txt_clean.lower()}`")
                            
                            # Sla de losse woorden op voor de trefwoorden-matrix
                            alle_opgeschoonde_woorden.extend(txt_clean.lower().split())
                            
                            # --- STAP 2: KADERS TEKENEN OP CANVAS ---
                            tl = (int(bbox[0][0] * scale_multiplier), int(bbox[0][1] * scale_multiplier))
                            br = (int(bbox[2][0] * scale_multiplier), int(bbox[2][1] * scale_multiplier))
                            cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 1) # Dunne groene lijn voor basis-tekst
                            
                            # --- STAP 3: TIJD DETECTIE ---
                            tijd_matches = re.findall(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean)
                            if tijd_matches:
                                tijd_regels.append(txt_clean.lower())
                                cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3) # Dikker blauw kader om tijden

                    # Maak één grote string van alle gevonden woorden voor regex-patronen
                    volledige_tekst_plat = " ".join(alle_opgeschoonde_woorden)

                    st.markdown("---")
                    st.markdown("#### 📋 Matrix Checklist")
                    
                    # --- CHECK 1: ROBUUSTE 6E TRADITIE MATRIX ---
                    st.markdown("##### 🔴 Kritieke Controles")
                    
                    traditie_keywords = ["6e", "traditie", "verbonden", "kerken", "sekten", "politieke", "hulpverlenende", "instanties"]
                    gevonden_traditie_woorden = []
                    
                    # Check elk trefwoord met een tolerantie van 75% (pakt ook typefouten als 'hulperlenende')
                    for kw in traditie_keywords:
                        kw_match = False
                        for woord in alle_opgeschoonde_woorden:
                            if kw in woord or word_similarity(kw, woord) >= 0.75:
                                kw_match = True
                                gevonden_traditie_woorden.append(kw)
                                break
                    
                    traditie_score = len(set(gevonden_traditie_woorden))
                    totaal_keywords = len(traditie_keywords)
                    
                    if traditie_score >= 5:
                        st.success(f"✅ **6e traditie aanwezig** (Trefwoorden gecoverd: {traditie_score}/{totaal_keywords})")
                    elif traditie_score >= 3:
                        st.warning(f"⚠️ **6e traditie mogelijk incompleet of slecht leesbaar** (Gevonden: {traditie_score}/{totaal_keywords} -> {', '.join(set(gevonden_traditie_woorden))})")
                    else:
                        st.error(f"❌ **6e traditie ontbreekt of is onleesbaar** (Slechts {traditie_score}/{totaal_keywords} trefwoorden herkend. Controleer de verplichte disclaimer!)")

                    # --- CHECK 2: ORGANISATOR ---
                    st.markdown("##### 🏢 Evenementgegevens")
                    organisator_match = re.search(r'ca[\s\-]+[a-z0-9]+', volledige_tekst_plat, re.IGNORECASE)
                    if organisator_match:
                        st.success(f"✅ **Organisator gevonden:** {organisator_match.group(0).upper()}")
                    else:
                        st.warning("⚠️ **Geen specifieke CA-groep herkend** (bijv. 'CA Hoorn')")

                    # --- CHECK 3: EVENEMENTNAAM ---
                    evenement_woorden = ["event", "bbq", "fundraiser", "conventie", "feest", "zomer", "winter", "lente", "herfst", "workshop", "meeting", "speaker", "countdown", "bijeenkomst"]
                    if any(woord in alle_opgeschoonde_woorden for woord in evenement_woorden):
                        st.success(f"✅ **Evenementnaam/type gevonden**")
                    else:
                        st.info("ℹ️ **Geen duidelijke evenementnaam herkend**")

                    # --- CHECK 4: DATUM ---
                    maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
                    datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst_plat, re.IGNORECASE)
                    if datum_match:
                        st.success(f"✅ **Datum gevonden:** {datum_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen datum gevonden**")

                    # --- CHECK 5: TIJD ---
                    tijd_regels = list(set(tijd_regels)) # Unieke tijden filteren
                    if len(tijd_regels) >= 2:
                        st.success(f"✅ **Tijdsbereik gevonden:** {tijd_regels[0]} tot {tijd_regels[1]}")
                    elif len(tijd_regels) == 1:
                        st.info(f"ℹ️ **Enkele tijd gevonden:** {tijd_regels[0]}")
                    else:
                        st.warning("⚠️ **Geen tijdstip of bereik kunnen detecteren**")

                    # --- CHECK 6: LOCATIE ---
                    postcode_match = re.search(r'\d{4}\s*[a-z]{2}', volledige_tekst_plat, re.IGNORECASE)
                    locatie_woorden = ["strand", "centrum", "kerk", "zaal", "hotel", "gebouw", "buurthuis", "community", "hoorn", "amsterdam", "rotterdam", "utrecht", "haarlem"]
                    
                    if postcode_match or any(l_w in alle_opgeschoonde_woorden for l_w in locatie_woorden):
                        st.success(f"✅ **Locatie of plaatsnaam gevonden**")
                    else:
                        st.warning(f"⚠️ **Locatie niet duidelijk herkend**")

                    # --- CHECK 7 & 8: CONTACT & E-MAIL ---
                    st.markdown("##### 📞 Contactgegevens")
                    telefoon_match = re.search(r'(06[- ]*\d{8}|\+31[- ]*6[- ]*\d{8})', volledige_tekst_plat)
                    if telefoon_match: st.success(f"✅ **Telefoonnummer gevonden:** {telefoon_match.group(0)}")
                    else: st.info("ℹ️ **Geen telefoonnummer gevonden**")

                    email_match = re.search(r'[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}', volledige_tekst_plat, re.IGNORECASE)
                    if email_match: st.success(f"✅ **E-mailadres gevonden:** {email_match.group(0)}")
                    else: st.info("ℹ️ **Geen e-mailadres gevonden**")

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")

        # ---- LOGO CHECK (FUZZY WOORDENBOEK) ----
        st.markdown("### 🖼️ CA-Logo Controle")
        
        logo_gevonden = False
        logo_score = 0
        
        # Methode 1: Template Matching (Toleranter gemaakt door lagere drempelwaarden te proberen)
        if logos:
            with st.spinner("Zoeken naar CA-logo via grafische matching..."):
                try:
                    for logo in logos:
                        # We testen vanaf 0.50 vanwege mogelijke kleur- en schaalverschillen op de flyer
                        for threshold in [0.50, 0.55, 0.60]:
                            res = cv2.matchTemplate(img_gray_scaled, logo, cv2.TM_CCOEFF_NORMED)
                            loc = np.where(res >= threshold)
                            
                            if len(loc[0]) > 0:
                                h, w = logo.shape
                                pt = (loc[1][0], loc[0][0])
                                # Blauw vierkant om gedetecteerd logo
                                cv2.rectangle(img_canvas, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), 5)
                                logo_score += 2.5
                                logo_gevonden = True
                                break
                        if logo_gevonden:
                            break
                except Exception as logo_err:
                    pass

        # Methode 2: Cirkeltekst fuzzy herkenning ("hoop", "vertrouwen", "moed")
        logo_keywords = ["hoop", "vertrouwen", "moed", "cocaine", "anonymous"]
        gevonden_logo_woorden = []
        
        for kw in logo_keywords:
            for woord in alle_opgeschoonde_woorden:
                if word_similarity(kw, woord) >= 0.75: # Accepteert herkenningen als 'ho0p' of 'm0ed'
                    gevonden_logo_woorden.append(kw)
                    break
                    
        logo_tekst_score = len(set(gevonden_logo_woorden))
        if logo_tekst_score >= 2:
            logo_score += 1.5
        if logo_tekst_score >= 3:
            logo_score += 1.0

        # Eindbeoordeling Logo Matrix
        if logo_score >= 3.0:
            logo_gevonden = True
            st.success(f"✅ **CA-logo aanwezig** (Gecorrepoleerde score: {logo_score:.1f}/5.0 - Tekst herkend: {', '.join(set(gevonden_logo_woorden))})")
        elif logo_score >= 1.5:
            logo_gevonden = True
            st.warning(f"⚠️ **CA-logo waarschijnlijk aanwezig (tekst-only match)** (Score: {logo_score:.1f}/5.0 - Tekst: {', '.join(set(gevonden_logo_woorden))})")
        else:
            st.warning(f"⚠️ **Geen officieel CA-logo of cirkeltekst herkend**")

        # --- SAMENVATTEND RAPPORT ---
        st.markdown("---")
        st.markdown("#### 📊 Samenvattend Rapport")
        kritiek_geslaagd = logo_gevonden and traditie_score >= 5
        
        if kritiek_geslaagd:
            st.success("✅ **Kritieke Matrix-controles geslaagd:** Het logo is gedetecteerd en de 6e traditie disclaimer staat er correct op.")
        else:
            if not logo_gevonden: st.error("❌ **Kritieke check mislukt:** CA-logo kon visueel noch tekstueel worden geverifieerd.")
            if traditie_score < 5: st.error(f"❌ **Kritieke check mislukt:** De 6e traditie disclaimer is incompleet of onleesbaar ({traditie_score}/8 trefwoorden).")

    # RECHTERKOLOM: Het visuele voorbeeldscherm met de Multi-Pass resultaten
    with col2:
        st.markdown("### 🖼️ Voorbeeldscherm (Visuele Matrix)")
        st.caption("🟢 Groen = Tekstgedeelten (Alle passes) | 🔵 Blauw = Gevonden tijden / CA-Logo")
        
        st.image(img_canvas, use_column_width=True, caption="Opgeschaald voorbeeldscherm met actieve matrix-omlijningen")
        
        # Uitklapboxen voor debugging
        if alle_opgeschoonde_woorden:
            with st.expander("Bekijk opgeschoonde gedetecteerde tekst (ruw plat)"):
                st.write(volledige_tekst_plat)
        
        if ruwe_regels_debug:
            with st.expander("🔧 Multi-Pass OCR Logbestanden (Debug)"):
                for regel in ruwe_regels_debug:
                    st.write(f"• {regel}")

    # Tijd-sidebar vullen
    if tijd_regels:
        with st.sidebar:
            st.markdown("### ⏰ Gedetecteerde tijden")
            for t in tijd_regels:
                st.write(f"• `{t}`")
