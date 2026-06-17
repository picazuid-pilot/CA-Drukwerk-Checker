import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import re
import traceback

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("OCR-analyse met Tesseract")

# Probeer Tesseract te laden
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
    st.sidebar.success("✅ Tesseract geladen")
except ImportError:
    TESSERACT_AVAILABLE = False
    st.sidebar.error("❌ Tesseract niet beschikbaar")

# Helper functie
def word_similarity(w1, w2):
    try:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, str(w1).lower().strip(), str(w2).lower().strip()).ratio()
    except:
        return 0.0

uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    try:
        file_bytes = uploaded_file.read()
        image_pil = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        img_np = np.array(image_pil)
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.image(img_np, caption="Geüploade flyer", use_container_width=True)
        
        with col2:
            st.markdown("### 📝 Analyse Resultaten")
            
            if TESSERACT_AVAILABLE:
                try:
                    with st.spinner("OCR scan bezig..."):
                        # Converteer naar grayscale voor Tesseract
                        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                        
                        # Verbeter contrast
                        img_gray = cv2.equalizeHist(img_gray)
                        
                        # OCR met Tesseract
                        config = '--oem 3 --psm 6 -l nld'
                        text = pytesseract.image_to_string(img_gray, config=config)
                        
                        st.write("**Gevonden tekst:**")
                        st.text(text[:500] + ("..." if len(text) > 500 else ""))
                        
                        # Analyse
                        text_lower = text.lower()
                        
                        # Logo check
                        logo_woorden = ["hoop", "vertrouwen", "moed"]
                        gevonden_logo = []
                        
                        for woord in logo_woorden:
                            if woord in text_lower:
                                gevonden_logo.append(woord)
                        
                        st.markdown("---")
                        st.markdown("### 🖼️ Logo Check")
                        
                        if len(gevonden_logo) >= 2:
                            st.success(f"✅ Logo herkend! Woorden: {', '.join(gevonden_logo)}")
                        elif len(gevonden_logo) >= 1:
                            st.warning(f"⚠️ Logo gedeeltelijk herkend: {', '.join(gevonden_logo)}")
                        else:
                            st.warning("⚠️ Geen logo-teksten gevonden")
                            st.caption("Zoek naar: 'hoop', 'vertrouwen', 'moed'")
                        
                        # 6e Traditie check
                        st.markdown("---")
                        st.markdown("### 📝 6e Traditie Check")
                        
                        traditie_woorden = ["6e", "traditie", "kerken", "sekten"]
                        gevonden_traditie = []
                        
                        for woord in traditie_woorden:
                            if woord in text_lower:
                                gevonden_traditie.append(woord)
                        
                        if len(gevonden_traditie) >= 3:
                            st.success(f"✅ 6e traditie gevonden! ({len(gevonden_traditie)}/4)")
                        elif len(gevonden_traditie) >= 2:
                            st.warning(f"⚠️ 6e traditie gedeeltelijk ({len(gevonden_traditie)}/4)")
                        else:
                            st.error("❌ 6e traditie niet gevonden")
                        
                        # Extra info
                        with st.expander("📝 Volledige OCR tekst"):
                            st.text(text)
                            
                except Exception as e:
                    st.error(f"❌ OCR fout: {e}")
                    st.code(traceback.format_exc())
            else:
                st.error("❌ Tesseract is niet beschikbaar.")
                st.info("📌 Installatie instructies:")
                st.code("pip install pytesseract")
                st.info("📌 Voor Streamlit Cloud, voeg toe aan requirements.txt:")
                st.code("pytesseract")
                st.info("📌 Let op: Tesseract heeft ook systeemafhankelijkheden!")
                
    except Exception as e:
        st.error(f"❌ Algemene fout: {e}")
        st.code(traceback.format_exc())
else:
    st.info("👆 Upload een flyer om te beginnen")
