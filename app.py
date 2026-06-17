import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import requests
import re

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Matrix Checker",
    page_icon="📐",
    layout="wide"
)

st.title("📐 C.A. Bleed & CMYK Matrix Checker")
st.subheader("Controleer de lay-out, kleurruimte en visuele inhoud van je flyer")

# 1. Cache de EasyOCR Reader (voorkomt Out of Memory crashes op Streamlit)
@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# 2. Functie om logo's veilig te downloaden
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
uploaded_file = st.file_uploader("Upload hier je flyer of drukwerkbestand (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # Maak een kopie om de gekleurde kaders (omlijningen) op te tekenen
        img_canvas = img_np.copy()
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    except Exception as e:
        st.error(f"❌ Fout bij het verwerken van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geüpload. Analyse start...")

    # Kolommen opzetten: Links de checklist, Rechts het visuele voorbeeldscherm met omlijningen
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Inhoudelijke Controle (Flyer Matrix)")
        
        if reader is None:
            st.error("OCR is niet beschikbaar.")
            volledige_tekst = ""
        else:
            with st.spinner("Tekst scannen en omlijnen..."):
                try:
                    # detail=1 geeft ook de coördinaten van de tekst terug voor het omlijnen
                    ocr_results = reader.readtext(img_np, detail=1)
                    
                    alle_teksten = []
                    for (bbox, text, prob) in ocr_results:
                        alle_teksten.append(text)
                        
                        # Coördinaten uitpakken voor OpenCV (top-left en bottom-right)
                        tl = tuple(map(int, bbox[0]))
                        br = tuple(map(int, bbox[2]))
                        
                        # Teken een GROEN kader om elk gedetecteerd tekstblok
                        cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                    
                    volledige_tekst = " ".join(alle_teksten)
                    
                    # --- CONTROLES OP BASIS VAN TEKST ---
                    # 1. Organisator
                    organisator_match = re.search(r'(CA\s+[A-Za-z]+|Cocaine\s+Anonymous\s+[A-Za-z]+)', volledige_tekst, re.IGNORECASE)
                    if organisator_match:
                        st.success(f"✅ **Organisator gevonden:** {organisator_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen specifieke CA-groep herkend** (bijv. 'CA Hoorn')")

                    # 2. Datum & Tijd
                    maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
                    datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
                    tijd_match = re.search(r'(\d{2}[:.]\d{2})\s*(tot|u|uur)?\s*(\d{2}[:.]\d{2})?', volledige_tekst, re.IGNORECASE)
                    
                    if datum_match: st.success(f"✅ **Datum gevonden:** {datum_match.group(0)}")
                    else: st.warning("⚠️ **Geen datum gevonden**")
                        
                    if tijd_match: st.success(f"✅ **Tijd gevonden:** {tijd_match.group(0)}")
                    else: st.warning("⚠️ **Geen tijdstip gevonden**")

                    # 3. Telefoonnummer
                    telefoon_match = re.search(r'(06[- ]*\d{8}|\+31[- ]*6[- ]*\d{8})', volledige_tekst)
                    if telefoon_match: st.success(f"✅ **Telefoonnummer gevonden:** {telefoon_match.group(0)}")
                    else: st.warning("⚠️ **Geen telefoonnummer gevonden**")

                    # 4. 6e Traditie
                    if any(w in volledige_tekst.lower() for w in ["6e traditie", "traditie", "niet verbonden aan"]):
                        st.success("✅ **6e traditie aanwezig:** Disclaimer gedetecteerd.")
                    else:
                        st.error("❌ **6e traditie ontbreekt of onleesbaar!**")

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
                        threshold = 0.7
                        loc = np.where(res >= threshold)
                        
                        # Als er een match is, neem de eerste locatie en omlijn deze
                        if len(loc[0]) > 0:
                            h, w = logo.shape
                            pt = (loc[1][0], loc[0][0])
                            # Teken een BLAUW kader om het gevonden logo
                            cv2.rectangle(img_canvas, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), 3)
                            logo_gevonden = True
                            break
                    
                    if logo_gevonden: st.success("✅ **CA-logo aanwezig**")
                    else: st.warning("⚠️ **Geen officieel CA-logo herkend**")
                except Exception as logo_err:
                    st.error(f"Fout bij logo-scan: {logo_err}")

    # RECHTERKOLOM: Het visuele voorbeeldscherm met de omlijningen
    with col2:
        st.markdown("### 🖼️ Voorbeeldscherm (Gedetecteerde Elementen)")
        st.caption("🟢 Groen = Gedetecteerde tekstblokken | 🔵 Blauw = Gevonden CA-Logo")
        
        # Toon de bewerkte afbeelding met de getekende kaders
        st.image(img_canvas, use_column_width=True, caption="Flyer met visuele omlijning van de checker")
        
        if volledige_tekst:
            with st.expander("Bekijk ruwe gedetecteerde tekst"):
                st.write(volledige_tekst)
