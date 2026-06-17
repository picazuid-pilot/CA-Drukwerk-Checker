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
st.subheader("Controleer de lay-out, kleurruimte en inhoud van je flyer")

# 1. Cache de EasyOCR Reader zodat deze niet telkens opnieuw laadt (voorkomt Out of Memory)
@st.cache_resource
def load_ocr_reader():
    try:
        # Laadt het model eenmalig in het geheugen
        return easyocr.Reader(['nl'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# 2. Functie om logo's veilig te downloaden met een timeout
@st.cache_data
def download_official_logos():
    logos = []
    # Pas deze URLs aan naar de werkelijke locaties van je referentielogo's op GitHub
    urls = [
        "https://raw.githubusercontent.com/picazuid-pilot/CA-Drukwerk-Checker/main/logo1.png",
        "https://raw.githubusercontent.com/picazuid-pilot/CA-Drukwerk-Checker/main/logo2.png"
    ]
    
    st.write("🔄 Controleren van officiële logo-bestanden...")
    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                img_bytes = np.frombuffer(response.content, dtype=np.uint8)
                img = cv2.imdecode(img_bytes, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    logos.append(img)
        except Exception as e:
            st.warning(f"⚠️ Kon logo van {url} niet laden: {e}")
    
    st.write(f"✅ {len(logos)} referentielogo's succesvol stand-by.")
    return logos

# Laad de logo's
logos = download_official_logos()

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier je flyer of drukwerkbestand (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Lees bytes voor inspectie
    file_bytes = uploaded_file.read()
    
    # Probeer afbeelding te openen
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    except Exception as e:
        st.error(f"❌ Fout bij het verwerken van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geüpload. Analyse start...")

    # ---- INHOUDSANALYSE VIA OCR ----
    st.markdown("### 📝 Inhoudelijke Controle (Flyer Matrix)")
    
    if reader is None:
        st.error("OCR-functionaliteit is niet beschikbaar vanwege een eerdere laadfout.")
    else:
        with st.spinner("Tekst van de flyer lezen..."):
            try:
                # Voer OCR uit op de afbeelding
                ocr_results = reader.readtext(img_np, detail=0)
                volledige_tekst = " ".join(ocr_results)
                
                st.write("---")
                st.write("**Gedetecteerde tekst op de flyer:**")
                st.caption(volledige_tekst)
                st.write("---")
                
                # --- CONTROLES OP BASIS VAN REGEX / ZOEKTERMEN ---
                
                # 1. Organisator / CA Groep
                organisator_match = re.search(r'(CA\s+[A-Za-z]+|Cocaine\s+Anonymous\s+[A-Za-z]+)', volledige_tekst, re.IGNORECASE)
                if organisator_match:
                    st.success(f"✅ **Organisator gevonden:** {organisator_match.group(0)}")
                else:
                    st.warning("⚠️ **Geen specifieke CA-groep / organisator herkend** (bijv. 'CA Hoorn')")

                # 2. Datum & Tijd
                # Zoekt naar patronen zoals "26 juli", "26-07", etc.
                maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
                datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
                tijd_match = re.search(r'(\d{2}[:.]\d{2})\s*(tot|u|uur)?\s*(\d{2}[:.]\d{2})?', volledige_tekst, re.IGNORECASE)
                
                if datum_match:
                    st.success(f"✅ **Datum gevonden:** {datum_match.group(0)}")
                else:
                    st.warning("⚠️ **Geen datum gevonden**")
                    
                if tijd_match:
                    st.success(f"✅ **Tijd gevonden:** {tijd_match.group(0)}")
                else:
                    st.warning("⚠️ **Geen tijdstip gevonden**")

                # 3. Locatie indikatoren
                locatie_woorden = ["stadsstrand", "park", "straat", "weg", "buurtcentrum", "kerk", "club", "cafe", "bbq"]
                gevonden_locatie = [woord for woord in locatie_woorden if woord in volledige_tekst.lower()]
                if gevonden_locatie or "hoorn" in volledige_tekst.lower():
                    # Simpele extractie rondom het trefwoord
                    st.success("✅ **Mogelijke locatie/evenement-indicatie gevonden** (bevat trefwoorden zoals 'Hoorn' of 'BBQ')")
                else:
                    st.warning("⚠️ **Geen duidelijke locatie kunnen herleiden**")

                # 4. Telefoonnummer
                telefoon_match = re.search(r'(06[- ]*\d{8}|\+31[- ]*6[- ]*\d{8})', volledige_tekst)
                if telefoon_match:
                    st.success(f"✅ **Telefoonnummer gevonden:** {telefoon_match.group(0)}")
                else:
                    st.warning("⚠️ **Geen telefoonnummer gevonden**")

                # 5. 6e Traditie
                if "6e traditie" in volledige_tekst.lower() or "traditie" in volledige_tekst.lower() or "niet verbonden aan" in volledige_tekst.lower():
                    st.success("✅ **6e traditie aanwezig:** Verwijzing of disclaimer gedetecteerd.")
                else:
                    st.error("❌ **6e traditie ontbreekt of is onleesbaar:** Denk aan de verplichte CA-disclaimer!")

                # 6. Online / Zoom gegevens
                if "zoom" in volledige_tekst.lower() or "meeting id" in volledige_tekst.lower():
                    st.success("💻 **Online meeting gegevens (Zoom) gedetecteerd**")
                else:
                    st.info("ℹ️ Geen Zoom-link of ID gevonden (waarschijnlijk een fysiek event)")

            except Exception as ocr_error:
                st.error(f"❌ Er ging iets mis tijdens de tekstherkenning (EasyOCR): {ocr_error}")

    # ---- LOGO CHECK VIA TEMPLATE MATCHING ----
    st.markdown("### 🖼️ CA-Logo Controle")
    if not logos:
        st.info("Logo-controle overgeslagen omdat de referentielogo's niet geladen zijn.")
    else:
        with st.spinner("Zoeken naar CA-logo op de flyer..."):
            logo_gevonden = False
            try:
                # Beperkt tot één schaal (0.3) om vastlopen op Streamlit Cloud te voorkomen
                for logo in logos:
                    for scale in [0.3]: 
                        w, h = logo.shape[::-1]
                        res = cv2.matchTemplate(img_gray, logo, cv2.TM_CCOEFF_NORMED)
                        threshold = 0.7  # Betrouwbaarheid van 70%
                        loc = np.where(res >= threshold)
                        
                        if len(loc[0]) > 0:
                            logo_gevonden = True
                            break
                    if logo_gevonden:
                        break
                
                if logo_gevonden:
                    st.success("✅ **CA-logo aanwezig**")
                else:
                    st.warning("⚠️ **Geen officieel CA-logo herkend** (Let op: de resolutie of hoek kan afwijken)")
            except Exception as template_error:
                st.error(f"❌ Fout tijdens het zoeken naar het logo: {template_error}")
