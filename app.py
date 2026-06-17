import streamlit as str
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import requests
import re

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Controleer de verplichte elementen en inhoud van de flyer matrix")

# 1. Cache de EasyOCR Reader (voorkomt Out of Memory crashes op Streamlit Cloud)
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
                    tijd_blokken = []
                    
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    st.caption("Hieronder zie je exact wat de scanner regel-voor-regel aantreft:")
                    
                    for (bbox, text, prob) in ocr_results:
                        # Toon direct op het scherm wat er gelezen wordt om te debuggen
                        st.write(f"• OCR leest: `{text}`")
                        
                        # --- STAP 1: NORMALISATIE VAN TEXT EN CORRECHTIES ---
                        # Vervang de letter O/o door een nul als het in een cijferreeks staat
                        txt_clean = text.replace("O", "0").replace("o", "0")
                        txt_clean = txt_clean.replace("juii", "juli").replace("juIi", "juli").replace("ju1i", "juli")
                        
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
                        # Accepteert nu ook '1200', '12:00', '12 . 00', etc.
                        tijd_matches = re.findall(r'\b\d{1,2}\s*[:.;]?\s*\d{2}\b', txt_clean)
                        if tijd_matches:
                            tijd_blokken.extend(tijd_matches)
                            # Geef tijdsblokken een opvallend dikker blauw kader
                            cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

                    # Voeg alle regels samen voor de brede matrix-checks
                    volledige_tekst = " ".join(alle_teksten)
                    
                    st.markdown("---")
                    st.markdown("#### 📋 Matrix Checklist")
                    
                    # --- 1. ORGANISATOR CHECK ---
                    organisator_match = re.search(r'(CA\s+[A-Za-z]+|Cocaine\s+Anonymous\s+[A-Za-z]+)', volledige_tekst, re.IGNORECASE)
                    if organisator_match:
                        st.success(f"✅ **Organisator gevonden:** {organisator_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen specifieke CA-groep herkend** (bijv. 'CA Hoorn')")

                    # --- 2. DATUM CHECK ---
                    maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
                    datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
                    if datum_match:
                        st.success(f"✅ **Datum gevonden:** {datum_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen datum gevonden**")

                    # --- 3. TIJDSBEREIK CHECK ---
                    # Check op lopend bereik (zoals '12:00 tot 18:00')
                    bereik_match = re.search(r'\b\d{1,2}\s*[:.;]?\s*\d{2}\s*(tot|-|t/m)\s*\d{1,2}\s*[:.;]?\s*\d{2}\b', volledige_tekst, re.IGNORECASE)
                    
                    if bereik_match:
                        st.success(f"✅ **Tijdsbereik gevonden:** {bereik_match.group(0)}")
                    elif len(tijd_blokken) >= 2:
                        st.success(f"✅ **Tijdsbereik gevonden (uit losse blokken):** {tijd_blokken[0]} tot {tijd_blokken[1]}")
                    elif len(tijd_blokken) == 1:
                        st.info(f"ℹ️ **Enkele tijd gevonden:** {tijd_blokken[0]} (Geen eindtijd herleid)")
                    else:
                        st.warning("⚠️ **Geen tijdstip of bereik kunnen detecteren**")

                    # --- 4. TELEFOONNUMMER CHECK ---
                    telefoon_match = re.search(r'(06[- ]*\d{8}|\+31[- ]*6[- ]*\d{8})', volledige_tekst)
                    if telefoon_match:
                        st.success(f"✅ **Telefoonnummer gevonden:** {telefoon_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen telefoonnummer gevonden**")

                    # --- 5. 6E TRADITIE CHECK ---
                    if any(w in volledige_tekst.lower() for w in ["6e traditie", "traditie", "niet verbonden aan", "kerken"]):
                        st.success("✅ **6e traditie aanwezig:** Disclaimer succesvol gedetecteerd.")
                    else:
                        st.error("❌ **6e traditie ontbreekt of is onleesbaar:** Denk aan de verplichte CA-disclaimer!")

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")
                    volledige_tekst = ""

        # ---- LOGO CHECK ----
        st.markdown("### 🖼️ CA-Logo Controle")
        if logos:
            with st.spinner("Zoeken naar CA-logo..."):
                logo_gevonden = False
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
        
        # Toon de bewerkte afbeelding met alle getekende kaders overzichtelijk in beeld
        st.image(img_canvas, use_column_width=True, caption="Flyer met live omlijning van de gedetecteerde matrix-elementen")
        
        if volledige_tekst:
            with st.expander("Bekijk volledige opgeschoonde tekst (ruw)"):
                st.write(volledige_tekst)
