import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import requests
import re

# Fallback voor fuzzy matching zonder extra dependencies
def simple_fuzzy_match(text1, text2):
    """Eenvoudige fuzzy match zonder rapidfuzz"""
    text1 = text1.lower().strip()
    text2 = text2.lower().strip()
    
    # Check of een tekst de andere bevat
    if text1 in text2 or text2 in text1:
        return 100

    # Check woorden die overlappen
    words1 = set(text1.split())
    words2 = set(text2.split())
    overlap = len(words1.intersection(words2))
    total = max(len(words1), len(words2))

    if total == 0:
        return 0

    return (overlap / total) * 100

# Extra handige helper om OCR-typefouten in losse trefwoorden op te vangen
def word_similarity(w1, w2):
    """Berekent karakteroverlap tussen twee woorden (0.0 - 1.0)"""
    w1, w2 = w1.lower().strip(), w2.lower().strip()
    if w1 in w2 or w2 in w1:
        return 1.0
    # Tel overlappende karakters (eenvoudige letter-voor-letter vergelijking)
    matches = sum(1 for c in w1 if c in w2)
    return matches / max(len(w1), len(w2))

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

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # --- VERBETERING: Genereer contrast-voorwerking voor Multi-Pass OCR ---
        # Dit helpt EasyOCR om de hele kleine, lichte disclaimers op te pikken
        img_gray_orig = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        img_enhanced = cv2.adaptiveThreshold(
            img_gray_orig, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        # We gebruiken de originele afbeelding als basis-canvas om kaders te tekenen
        img_canvas = img_np.copy()
        
    except Exception as e:
        st.error(f"❌ Fout bij het openen van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geladen. Analyse start...")

    # Twee kolommen: links de Checklist Matrix, rechts het Voorbeeldscherm
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Matrix Resultaten")
        
        if reader is None:
            st.error("OCR-module is offline.")
            volledige_tekst = ""
        else:
            with st.spinner("Tekst scannen en analyseren via Multi-Pass OCR..."):
                try:
                    # --- VERBETERING: Multi-Pass OCR (Origineel + Contrast-enhanced) ---
                    ocr_results_orig = reader.readtext(img_np, detail=1)
                    ocr_results_enh = reader.readtext(img_enhanced, detail=1)
                    
                    # Voeg de resultaten slim samen
                    ocr_results = ocr_results_orig + ocr_results_enh
                    
                    alle_teksten = []
                    tijd_regels = []
                    ruwe_regels = []  # Voor debug doeleinden
                    alle_losse_woorden = [] # Voor robuuste keyword matching
                    
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    st.caption("Hieronder zie je exact wat de scanner regel-voor-regel aantreft:")
                    
                    for (bbox, text, prob) in ocr_results:
                        ruwe_regels.append(text)
                        st.write(f"• OCR leest: `{text}`")
                        
                        # --- STAP 1: NORMALISATIE VAN TEKST ---
                        txt_clean = text
                        
                        # Specifieke OCR-correcties
                        txt_clean = txt_clean.replace("O", "0").replace("o", "0")
                        txt_clean = txt_clean.replace("juii", "juli").replace("juIi", "juli").replace("ju1i", "juli")
                        
                        txt_clean = txt_clean.lower()
                        txt_clean = txt_clean.replace("t0 t", "tot")
                        txt_clean = txt_clean.replace("t0t", "tot")
                        
                        # Verwijder spaties binnen tijden
                        txt_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', txt_clean)
                        txt_clean = txt_clean.replace(" : ", ":").replace(": ", ":").replace(" :", ":")
                        txt_clean = txt_clean.replace(" . ", ":").replace(". ", ":").replace(" .", ":")
                        
                        # Herstel tijdsnotaties
                        txt_clean = re.sub(r'(\d{1,2})\s+(\d{2})', r'\1:\2', txt_clean)
                        txt_clean = txt_clean.replace(';', ':').replace('.', ':')
                        
                        alle_teksten.append(txt_clean)
                        alle_losse_woorden.extend(txt_clean.split())
                        
                        # Coördinaten voor het omlijnelement aan de rechterkant
                        tl = tuple(map(int, bbox[0]))
                        br = tuple(map(int, bbox[2]))
                        
                        # Standaard groen kader om elk gedetecteerd tekstveld
                        cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                        
                        # --- STAP 2: ROBUUSTE TIJD REGEX PER BLOK ---
                        tijd_matches = re.findall(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean)
                        if tijd_matches:
                            tijd_regels.append(txt_clean)
                            # Geef tijdsblokken een opvallend dikker blauw kader
                            cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

                    # Voeg alle regels samen voor de brede matrix-checks
                    volledige_tekst = " ".join(alle_teksten)
                    
                    st.markdown("---")
                    st.markdown("#### 📋 Matrix Checklist")
                    
                    # --- INITIALISEER VARIABELEN VOOR RAPPORT ---
                    organisator_gevonden = False
                    evenementnaam_gevonden = False
                    datum_gevonden = False
                    tijd_gevonden = False
                    locatie_gevonden = False
                    telefoon_gevonden = False
                    logo_gevonden = False
                    zesde_traditie_score = 0
                    
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
                    if any(woord in volledige_tekst.lower() for woord in evenement_woorden):
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
                    tijd_regels = list(set(tijd_regels)) # Uniek maken tegen dubbelingen uit multi-pass
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
                    locatie_score = 0
                    for woord in locatie_woorden:
                        if woord in volledige_tekst.lower():
                            locatie_score += 1
                    
                    if "stadsstrand" in volledige_tekst.lower() and "hoorn" in volledige_tekst.lower():
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

                    # --- VERBETERING 7. ROBUUSTE 6E TRADITIE CHECK ---
                    # In plaats van hele zinnen te matchen, controleren we op de aanwezigheid van kernwoorden.
                    # Dit vangt OCR-fouten op zoals "hulperlenende" of "be traditie" in plaats van "6e traditie"
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
                    txt_lower = volledige_tekst.lower()
                    if "zoom" in txt_lower or "meet" in txt_lower:
                        st.success("✅ **Zoom/online link gevonden**")
                    else:
                        st.info("ℹ️ **Geen Zoom-link gedetecteerd** (niet verplicht)")

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")
                    volledige_tekst = ""

        # ---- VERBETERING: ROBUUSTE LOGO CONTROLE ----
        st.markdown("### 🖼️ CA-Logo Controle")
        logo_score = 0
        
        # Stap A: Grafische Template Matching (Toleranter gemaakt door lagere drempelwaarden te proberen)
        if logos:
            with st.spinner("Zoeken naar CA-logo via beeldherkenning..."):
                try:
                    for logo in logos:
                        # We scannen stapsgewijs vanaf een soepelere drempelwaarde om variatie op te vangen
                        for threshold in [0.50, 0.55, 0.65]:
                            res = cv2.matchTemplate(img_gray_orig, logo, cv2.TM_CCOEFF_NORMED)
                            loc = np.where(res >= threshold)
                            if len(loc[0]) > 0:
                                h, w = logo.shape
                                pt = (loc[1][0], loc[0][0])
                                cv2.rectangle(img_canvas, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), 4)
                                logo_score += 2.5  # Bonuspunten voor grafische herkenning
                                break
                        if logo_score > 0:
                            break
                except Exception as logo_err:
                    pass

        # Stap B: Tekstuele herkenning van de cirkeltekst ("hoop", "vertrouwen", "moed")
        logo_keywords = ["hoop", "vertrouwen", "moed", "cocaine", "anonymous"]
        gevonden_logo_woorden = []
        
        for kw in logo_keywords:
            for woord in alle_losse_woorden:
                if word_similarity(kw, woord) >= 0.75: # Accepteert ook 'ho0p' of 'm0ed'
                    gevonden_logo_woorden.append(kw)
                    break
                    
        logo_tekst_score = len(set(gevonden_logo_woorden))
        if logo_tekst_score >= 2:
            logo_score += 1.5
        if logo_tekst_score >= 3:
            logo_score += 1.0

        # Finale beoordeling van het logo op basis van de gecombineerde score
        if logo_score >= 3.0:
            logo_gevonden = True
            st.success(f"✅ **CA-logo aanwezig** (Gevalideerd via gecombineerde matrix-score: {logo_score}/5.0)")
        elif logo_score >= 1.5:
            logo_gevonden = True
            st.warning(f"⚠️ **CA-logo waarschijnlijk aanwezig** (Alleen cirkeltekst herkend: {', '.join(set(gevonden_logo_woorden))})")
        else:
            st.warning("⚠️ **Geen officieel CA-logo of cirkeltekst herkend**")


        # --- TOTAAL RAPPORT (Gebruikt de vernieuwde logica) ---
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
        
        # Detailrapport
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

# RECHTERKOLOM: Het visuele voorbeeldscherm
with col2:
    st.markdown("### 🖼️ Voorbeeldscherm (Visuele Matrix)")
    st.caption("🟢 Groen = Gevonden tekstvlakken | 🔵 Blauw = Gedetecteerde tijden of CA-Logo")
    
    st.image(img_canvas, use_column_width=True, caption="Flyer met live omlijning van de gedetecteerde matrix-elementen")
    
    if volledige_tekst:
        with st.expander("Bekijk volledige opgeschoonde tekst (ruw)"):
            st.write(volledige_tekst)
    
    if 'ruwe_regels' in locals():
        with st.expander("🔧 Ruwe OCR-output (debug)"):
            for i, regel in enumerate(ruwe_regels):
                st.write(f"{i+1}. `{regel}`")

if 'tijd_regels' in locals() and tijd_regels:
    with st.sidebar:
        st.markdown("### ⏰ Gedetecteerde tijden")
        for i, tijd in enumerate(tijd_regels):
            st.write(f"{i+1}. `{tijd}`")
