import streamlit as set_page_config
import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import re
from difflib import SequenceMatcher

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker v1.1",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Geoptimaliseerde Flyer Matrix Controle & Validatie")

# 1. Betrouwbare woord-overeenkomst (Punt 1)
def word_similarity(w1, w2):
    """Berekent de werkelijke gelijkenis ratio tussen twee woorden"""
    return SequenceMatcher(None, w1.lower().strip(), w2.lower().strip()).ratio()

# 2. Cache de EasyOCR Reader
@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# Systeemonderhoud & Statusmelding (Punt 4)
st.info("⚙️ **Systeemstatus:** Multi-Pass OCR-module online. Logo-detectie overgeschakeld op OCR-trefwoordenanalyse (Locatie-onafhankelijk).")

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # --- RGBA NAAR RGB CONVERSIE (Punt 7 - Crashpreventie) ---
        if len(img_np.shape) == 3 and img_np.shape[2] == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            
        img_gray_orig = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        
        # Pass 2: Adaptive Threshold
        img_enhanced = cv2.adaptiveThreshold(
            img_gray_orig, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        # Pass 3: CLAHE (Voor contrastarme tekst onderaan)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        img_clahe = clahe.apply(img_gray_orig)
        
        img_canvas = img_np.copy()
        
    except Exception as e:
        st.error(f"❌ Fout bij het verwerken van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geladen. Analyse start...")

    # =====================================================================
    # INITIALISATIE (Voorkomt crashes en NameErrors)
    # =====================================================================
    volledige_tekst = ""
    alle_teksten = []
    tijd_regels = []
    alle_losse_woorden = []
    gevonden_keys = set()  # Voor de-duplicatie (Punt 2)
    
    # Status variabelen
    organisator_gevonden = False
    evenementnaam_gevonden = False
    datum_gevonden = False
    tijd_gevonden = False
    locatie_gevonden = False
    telefoon_gevonden = False
    logo_gevonden = False
    
    organisator_naam = ""
    datum_waarde = ""
    telefoon_waarde = ""
    # =====================================================================

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Matrix Analyse")
        
        if reader is None:
            st.error("OCR-module is offline.")
        else:
            with st.spinner("Scannen via Multi-Pass OCR & Deduplicatie..."):
                try:
                    # Multi-Pass OCR scans verzamelen
                    ocr_results_orig = reader.readtext(img_np, detail=1)
                    ocr_results_enh = reader.readtext(img_enhanced, detail=1)
                    ocr_results_clahe = reader.readtext(img_clahe, detail=1)
                    
                    ocr_results = ocr_results_orig + ocr_results_enh + ocr_results_clahe
                    
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    
                    for (bbox, text, prob) in ocr_results:
                        # 1. Confidence filter (Negeer onleesbare ruis)
                        if prob < 0.30:
                            continue
                            
                        # 2. DEDUPLICATIE (Punt 2)
                        key = text.lower().strip()
                        if key in gevonden_keys:
                            continue
                        gevonden_keys.add(key)
                        
                        st.write(f"• OCR gedetecteerd (conf: {prob:.2f}): `{text}`")
                        
                        # Normalisatie van tekstfouten
                        txt_clean = text.lower()
                        txt_clean = txt_clean.replace("juii", "juli").replace("juIi", "juli").replace("ju1i", "juli")
                        txt_clean = txt_clean.replace("t0 t", "tot").replace("t0t", "tot")
                        
                        # Spatiering in tijden herstellen
                        txt_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', txt_clean)
                        txt_clean = txt_clean.replace(" : ", ":").replace(": ", ":")
                        
                        alle_teksten.append(txt_clean)
                        alle_losse_woorden.extend(txt_clean.split())
                        
                        # Teken kaders op canvas
                        tl = tuple(map(int, bbox[0]))
                        br = tuple(map(int, bbox[2]))
                        cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                        
                        # Tijd-herkenning check (Blauw kader)
                        if re.search(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean):
                            tijd_regels.append(txt_clean)
                            cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

                    # Voeg de schone, unieke tekst samen
                    volledige_tekst = " ".join(alle_teksten)
                    txt_lower = volledige_tekst.lower()
                    
                    st.markdown("---")
                    st.markdown("#### 📋 Matrix Checklist Resultaten")
                    
                    # --- 1. ORGANISATOR CHECK ---
                    organisator_match = re.search(r'ca[\s\-]+[a-z0-9]+', volledige_tekst, re.IGNORECASE)
                    if organisator_match:
                        organisator_gevonden = True
                        organisator_naam = organisator_match.group(0).upper()
                        st.success(f"✅ **Organisator:** {organisator_naam}")
                    else:
                        ca_pattern = re.search(r'ca\s+([a-z]+)', volledige_tekst, re.IGNORECASE)
                        if ca_pattern:
                            organisator_gevonden = True
                            organisator_naam = ca_pattern.group(0).upper()
                            st.success(f"✅ **Organisator (fuzzy):** {organisator_naam}")
                        else:
                            st.warning("⚠️ **Geen specifieke CA-groep herkend** (bijv. 'CA Hoorn')")

                    # --- 2. EVENEMENTNAAM CHECK ---
                    evenement_woorden = ["workshop", "bijeenkomst", "ontmoeting", "spreker", "meeting", "bbq", "fundraiser", "conventie", "feest", "countdown", "activity"]
                    if any(woord in txt_lower for woord in evenement_woorden):
                        evenementnaam_gevonden = True
                        st.success(f"✅ **Evenementnaam/Type geïdentificeerd**")
                    else:
                        st.info("ℹ️ **Geen specifiek evenementtype herkend**")

                    # --- 3. DATUM CHECK ---
                    maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
                    datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
                    if datum_match:
                        datum_gevonden = True
                        datum_waarde = datum_match.group(0)
                        st.success(f"✅ **Datum gevonden:** {datum_waarde}")
                    else:
                        st.warning("⚠️ **Geen datum gevonden**")

                    # --- 4. TIJD CHECK ---
                    tijd_regels = list(set(tijd_regels))
                    if len(tijd_regels) >= 2:
                        tijd_gevonden = True
                        st.success(f"✅ **Tijdsbereik gevonden:** {tijd_regels[0]} tot {tijd_regels[1]}")
                    elif len(tijd_regels) == 1:
                        tijd_gevonden = True
                        st.info(f"ℹ️ **Enkele tijd gevonden:** {tijd_regels[0]}")
                    else:
                        st.warning("⚠️ **Geen tijdstip of bereik gedetecteerd**")

                    # --- 5. LOCATIE CHECK ---
                    locatie_score = 0
                    locatie_woorden = ["strand", "centrum", "kerk", "zaal", "hotel", "gebouw", "hoorn", "stadsstrand", "buurthuis", "plein", "adres"]
                    for woord in locatie_woorden:
                        if woord in txt_lower:
                            locatie_score += 1
                    if locatie_score >= 2:
                        locatie_gevonden = True
                        st.success(f"✅ **Locatie herleid** (Trefwoorden match)")
                    else:
                        st.warning("⚠️ **Locatie niet sluitend herkend**")

                    # --- 6. GEOPTIMALISEERDE TELEFOON REGEX (Punt 5) ---
                    # Herkent: 06 37 61 27 51, 06-37-61-27-51, +31 6 37 61 27 51, etc.
                    tel_pattern = r'(\+31\s?6|06)[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}'
                    telefoon_match = re.search(tel_pattern, volledige_tekst)
                    if telefoon_match:
                        telefoon_gevonden = True
                        telefoon_waarde = telefoon_match.group(0)
                        st.success(f"✅ **Telefoonnummer gevonden:** {telefoon_waarde}")
                    else:
                        st.warning("⚠️ **Geen telefoonnummer gevonden**")

                    # --- 7. VERBETERDE 6E TRADITIE CHECK (Punt 6) ---
                    traditie_keywords = ["6e", "traditie", "verbonden", "kerken", "sekten", "politieke", "hulpverlenende", "instanties"]
                    gevonden_traditie_woorden = []
                    
                    for kw in traditie_keywords:
                        for woord in alle_losse_woorden:
                            if kw in woord or word_similarity(kw, woord) >= 0.80: # Strengere SequenceMatcher
                                gevonden_traditie_woorden.append(kw)
                                break
                    
                    zesde_traditie_score = len(set(gevonden_traditie_woorden))
                    if zesde_traditie_score >= 4: # Grens verlaagd van 5 naar 4 (Punt 6)
                        st.success(f"✅ **6e traditie aanwezig** ({zesde_traditie_score}/{len(traditie_keywords)} trefwoorden)")
                    else:
                        st.error(f"❌ **6e traditie incompleet of afwezig** ({zesde_traditie_score}/{len(traditie_keywords)} trefwoorden gevonden)")

                    # --- 8. VOLLEDIG OCR-GEBASEERDE LOGODETECTIE (Punt 3) ---
                    st.markdown("---")
                    st.markdown("#### 🖼️ CA-Logo Woordenherkenning")
                    logo_keywords = ["hoop", "vertrouwen", "moed"]
                    gevonden_logo_woorden = []
                    
                    for kw in logo_keywords:
                        for woord in alle_losse_woorden:
                            if word_similarity(kw, woord) >= 0.80:
                                gevonden_logo_woorden.append(kw)
                                break
                                
                    logo_tekst_score = len(set(gevonden_logo_woorden))
                    if logo_tekst_score >= 3:
                        logo_gevonden = True
                        st.success(f"✅ **CA-Logo GEGARANDEERD aanwezig** (Alle 3 de kernwoorden gelezen: *{', '.join(gevonden_logo_woorden)}*)")
                    elif logo_tekst_score == 2:
                        logo_gevonden = True
                        st.success(f"✅ **CA-Logo aanwezig** (2 van de 3 kernwoorden gelezen: *{', '.join(gevonden_logo_woorden)}*)")
                    else:
                        st.warning(f"⚠️ **Logo onzeker** ({logo_tekst_score}/3 kernwoorden gevonden). Mist de cirkeltekst?")

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")

        # =====================================================================
        # 📊 BEREKENING MATRIX SCORE EN GEWICHTEN (Punt 8)
        # =====================================================================
        st.markdown("---")
        st.markdown("### 📊 Matrix Score Rapport")
        
        # Berekening scores op basis van gewichten
        score = 0
        if logo_gevonden: score += 25             # Kritiek
        if zesde_traditie_score >= 4: score += 25  # Kritiek
        if organisator_gevonden: score += 15      # Essentieel
        if datum_gevonden: score += 15            # Essentieel
        if tijd_gevonden: score += 10             # Essentieel
        if locatie_gevonden: score += 5           # Essentieel
        if telefoon_gevonden: score += 5           # Aanbevolen bonus
        
        # Score visualisatie via een progressiebalk
        st.metric(label="Totale Matrix Score", value=f"{score} / 100")
        st.progress(score / 100)
        
        if score == 100:
            st.success("🎉 **UITMUNTEND:** De flyer voldoet aan álle matrix-eisen én aanbevelingen!")
        elif score >= 80:
            st.warning("⚠️ **VOLDOET:** De flyer is bruikbaar en bevat de kritieke onderdelen, maar mist details of aanbevelingen.")
        else:
            st.error("❌ **AFGEKEURD:** Deze flyer mist cruciale matrix-elementen en mag zo niet gedrukt worden.")

        # Prachtig dynamisch overzicht (Punt 8)
        with st.expander("📋 Bekijk gedetailleerde score-opbouw"):
            st.markdown("**🚨 KRITIEKE CONTROLES (Verplicht voor drukwerk)**")
            st.write(f"{'✅ (+25 pt)' if logo_gevonden else '❌ (+0 pt)'} C.A. Logo (Unieke tekst)")
            st.write(f"{'✅ (+25 pt)' if zesde_traditie_score >= 4 else '❌ (+0 pt)'} 6e Traditie Disclaimer ({zesde_traditie_score}/8 woorden)")
            
            st.markdown("**📅 EVENEMENT GEGEVENS**")
            st.write(f"{'✅ (+15 pt)' if organisator_gevonden else '❌ (+0 pt)'} Groepsnaam / Organisator ({organisator_naam if organisator_gevonden else 'Onbekend'})")
            st.write(f"{'✅ (+15 pt)' if datum_gevonden else '❌ (+0 pt)'} Datum ({datum_waarde if datum_gevonden else 'Onbekend'})")
            st.write(f"{'✅ (+10 pt)' if tijd_gevonden else '❌ (+0 pt)'} Tijdstip / Bereik")
            st.write(f"{'✅ (+5 pt)' if locatie_gevonden else '❌ (+0 pt)'} Locatie-indicatie")
            
            st.markdown("**📞 AANBEVOLEN ONDERDELEN**")
            st.write(f"{'✅ (+5 pt)' if telefoon_gevonden else '❌ (+0 pt)'} Telefoonnummer bereikbaarheid")

    with col2:
        st.markdown("### 🖼️ Live Geannoteerde Preview")
        st.caption("Gedetecteerde unieke tekstregels (groen) en tijdsindicaties (blauw).")
        st.image(img_canvas, channels="RGB", use_container_width=True)
