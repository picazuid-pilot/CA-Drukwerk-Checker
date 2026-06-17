import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import requests
import re
from rapidfuzz import fuzz

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
        
        # Kopie maken voor het visuele voorbeeldscherm met omlijningen
        img_canvas = img_np.copy()
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
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
            with st.spinner("Tekst scannen en analyseren..."):
                try:
                    ocr_results = reader.readtext(img_np, detail=1)
                    
                    alle_teksten = []
                    tijd_regels = []
                    ruwe_regels = []  # Voor debug doeleinden
                    
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    st.caption("Hieronder zie je exact wat de scanner regel-voor-regel aantreft:")
                    
                    for (bbox, text, prob) in ocr_results:
                        # Toon direct op het scherm wat er gelezen wordt om te debuggen
                        ruwe_regels.append(text)
                        st.write(f"• OCR leest: `{text}`")
                        
                        # --- STAP 1: NORMALISATIE VAN TEXT ---
                        txt_clean = text
                        
                        # Specifieke OCR-correcties
                        txt_clean = txt_clean.replace("O", "0").replace("o", "0")
                        txt_clean = txt_clean.replace("juii", "juli").replace("juIi", "juli").replace("ju1i", "juli")
                        
                        # Verbetering 2: "t0 t" wordt "tot"
                        txt_clean = txt_clean.lower()
                        txt_clean = txt_clean.replace("t0 t", "tot")
                        txt_clean = txt_clean.replace("t0t", "tot")
                        
                        # Verbetering 1: Verwijder ALLE spaties binnen tijden
                        txt_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', txt_clean)
                        txt_clean = txt_clean.replace(" : ", ":")
                        txt_clean = txt_clean.replace(": ", ":")
                        txt_clean = txt_clean.replace(" :", ":")
                        txt_clean = txt_clean.replace(" . ", ":")
                        txt_clean = txt_clean.replace(". ", ":")
                        txt_clean = txt_clean.replace(" .", ":")
                        
                        # Herstel tijdsnotaties met spaties (bijv. '12 00' naar '12:00')
                        txt_clean = re.sub(r'(\d{1,2})\s+(\d{2})', r'\1:\2', txt_clean)
                        txt_clean = txt_clean.replace(';', ':')
                        txt_clean = txt_clean.replace('.', ':')
                        
                        alle_teksten.append(txt_clean)
                        
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
                    
                    # --- 1. ORGANISATOR CHECK (Verbetering 4) ---
                    organisator_match = re.search(r'CA[\s\-]+[A-Za-z0-9]+', volledige_tekst, re.IGNORECASE)
                    if organisator_match:
                        organisator_gevonden = True
                        st.success(f"✅ **Organisator gevonden:** {organisator_match.group(0)}")
                    else:
                        # Fallback: fuzzy matching op "CA" + plaatsnaam
                        ca_pattern = re.search(r'CA\s+([A-Za-z]+)', volledige_tekst, re.IGNORECASE)
                        if ca_pattern:
                            organisator_gevonden = True
                            st.success(f"✅ **Organisator gevonden (fuzzy):** {ca_pattern.group(0)}")
                        else:
                            st.warning("⚠️ **Geen specifieke CA-groep herkend** (bijv. 'CA Hoorn')")

                    # --- 2. EVENEMENTNAAM CHECK (Verbetering 8) ---
                    evenement_woorden = ["workshop", "bijeenkomst", "ontmoeting", "spreker", "meeting", "actie"]
                    if any(woord in volledige_tekst.lower() for woord in evenement_woorden):
                        evenementnaam_gevonden = True
                        st.success(f"✅ **Evenementnaam gevonden**")
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

                    # --- 4. TIJD CHECK (Verbetering 3) ---
                    if len(tijd_regels) >= 2:
                        tijd_gevonden = True
                        st.success(f"✅ **Tijdsbereik gevonden:** {tijd_regels[0]} tot {tijd_regels[1]}")
                    elif len(tijd_regels) == 1:
                        tijd_gevonden = True
                        st.info(f"ℹ️ **Enkele tijd gevonden:** {tijd_regels[0]} (Geen eindtijd herleid)")
                    else:
                        st.warning("⚠️ **Geen tijdstip of bereik kunnen detecteren**")

                    # --- 5. LOCATIE CHECK (Verbetering 5) ---
                    locatie_woorden = ["strand", "centrum", "kerk", "zaal", "hotel", "gebouw", "hoorn", "stadsstrand"]
                    locatie_score = 0
                    for woord in locatie_woorden:
                        if woord in volledige_tekst.lower():
                            locatie_score += 1
                    
                    # Fuzzy match voor "Stadsstrand Hoorn"
                    if fuzz.partial_ratio(volledige_tekst.lower(), "stadsstrand hoorn") > 70:
                        locatie_score += 2
                    
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

                    # --- 7. 6E TRADITIE CHECK (Verbetering 6) ---
                    txt_lower = volledige_tekst.lower()
                    if "6e traditie" in txt_lower:
                        zesde_traditie_score += 2
                    if "niet verbonden" in txt_lower:
                        zesde_traditie_score += 2
                    if "kerken" in txt_lower:
                        zesde_traditie_score += 1
                    if "instantie" in txt_lower:
                        zesde_traditie_score += 1
                    
                    if zesde_traditie_score >= 3:
                        st.success("✅ **6e traditie aanwezig:** Disclaimer succesvol gedetecteerd.")
                    elif zesde_traditie_score >= 1:
                        st.warning(f"⚠️ **6e traditie gedeeltelijk herkend** (score: {zesde_traditie_score}/3)")
                    else:
                        st.error("❌ **6e traditie ontbreekt of is onleesbaar:** Denk aan de verplichte CA-disclaimer!")

                    # --- 8. ONLINE ELEMENTEN (Verbetering 8) ---
                    st.markdown("---")
                    st.markdown("#### 🌐 Online Elementen")
                    
                    if "zoom" in txt_lower or "meet" in txt_lower:
                        st.success("✅ **Zoom/online link gevonden**")
                    else:
                        st.info("ℹ️ **Geen Zoom-link gedetecteerd** (niet verplicht)")

                    # --- TOTAAL RAPPORT (Verbetering 8) ---
                    st.markdown("---")
                    st.markdown("#### 📊 Samenvattend Rapport")
                    
                    kritiek_geslaagd = logo_gevonden and zesde_traditie_score >= 3
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
                        st.write(f"{'✅' if zesde_traditie_score >= 3 else '⚠️' if zesde_traditie_score >= 1 else '❌'} 6e traditie (score: {zesde_traditie_score}/3)")
                        
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

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")
                    volledige_tekst = ""

        # ---- LOGO CHECK ----
        st.markdown("### 🖼️ CA-Logo Controle")
        if logos:
            with st.spinner("Zoeken naar CA-logo..."):
                try:
                    for logo in logos:
                        res = cv2.matchTemplate(img_gray, logo, cv2.TM_CCOEFF_NORMED)
                        threshold = 0.65
                        loc = np.where(res >= threshold)
                        
                        if len(loc[0]) > 0:
                            h, w = logo.shape
                            pt = (loc[1][0], loc[0][0])
                            # Blauw kader om het logo op het voorbeeldscherm
                            cv2.rectangle(img_canvas, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), 4)
                            logo_gevonden = True
                            break
                    
                    if logo_gevonden:
                        st.success("✅ **CA-logo aanwezig**")
                    else:
                        st.warning("⚠️ **Geen officieel CA-logo herkend**")
                except Exception as logo_err:
                    st.error(f"Fout bij logo-scan: {logo_err}")

    # RECHTERKOLOM: Het visuele voorbeeldscherm
    with col2:
        st.markdown("### 🖼️ Voorbeeldscherm (Visuele Matrix)")
        st.caption("🟢 Groen = Gevonden tekstvlakken | 🔵 Blauw = Gedetecteerde tijden of CA-Logo")
        
        # Toon de bewerkte afbeelding met alle getekende kaders
        st.image(img_canvas, use_column_width=True, caption="Flyer met live omlijning van de gedetecteerde matrix-elementen")
        
        if volledige_tekst:
            with st.expander("Bekijk volledige opgeschoonde tekst (ruw)"):
                st.write(volledige_tekst)
        
        # Toon ruwe OCR-output voor debugging
        if 'ruwe_regels' in locals():
            with st.expander("🔧 Ruwe OCR-output (debug)"):
                for i, regel in enumerate(ruwe_regels):
                    st.write(f"{i+1}. `{regel}`")

    # Toon de tijdregels die gevonden zijn voor debugging
    if 'tijd_regels' in locals() and tijd_regels:
        with st.sidebar:
            st.markdown("### ⏰ Gedetecteerde tijden")
            for i, tijd in enumerate(tijd_regels):
                st.write(f"{i+1}. `{tijd}`")
