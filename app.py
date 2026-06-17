import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import re
from difflib import SequenceMatcher

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Simpele OCR-analyse")

# 1. Probeer EasyOCR te laden met try-except
try:
    import easyocr
    reader = easyocr.Reader(['nl'], gpu=False)
    OCR_BESCHIKBAAR = True
    st.sidebar.success("✅ OCR geladen")
except Exception as e:
    OCR_BESCHIKBAAR = False
    st.sidebar.error(f"❌ OCR fout: {e}")

# 2. Helper functies
def word_similarity(w1, w2):
    try:
        return SequenceMatcher(None, str(w1).lower().strip(), str(w2).lower().strip()).ratio()
    except:
        return 0.0

# 3. Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    try:
        # 4. Lees bestand
        file_bytes = uploaded_file.read()
        
        # 5. Open met PIL
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # 6. Converteer naar RGB indien nodig
        if len(img_np.shape) == 3 and img_np.shape[2] == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
        elif len(img_np.shape) == 2:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
        
        st.success(f"✅ Afbeelding geladen: {img_np.shape}")
        
        # 7. Toon afbeelding
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.image(img_np, caption="Geüploade flyer", use_container_width=True)
        
        with col2:
            st.markdown("### 📝 Analyse Resultaten")
            
            # 8. OCR uitvoeren (alleen als beschikbaar)
            if OCR_BESCHIKBAAR:
                try:
                    with st.spinner("OCR scan bezig..."):
                        # Een simpele OCR pass
                        results = reader.readtext(img_np, detail=1)
                        
                        # Verzamel alle tekst
                        alle_tekst = []
                        gevonden_woorden = []
                        logo_woorden_gevonden = []
                        
                        st.markdown("**Gevonden tekst:**")
                        
                        for (bbox, text, prob) in results:
                            if prob > 0.2:
                                alle_tekst.append(text)
                                st.write(f"• `{text}` (confidence: {prob:.2f})")
                                
                                # Zoek naar logo-woorden
                                text_lower = text.lower()
                                for woord in ["hoop", "vertrouwen", "moed"]:
                                    if woord in text_lower or word_similarity(woord, text_lower) > 0.7:
                                        gevonden_woorden.append(woord)
                                        logo_woorden_gevonden.append(text)
                        
                        # Check logo
                        st.markdown("---")
                        st.markdown("### 🖼️ Logo Check")
                        
                        if len(set(gevonden_woorden)) >= 2:
                            st.success(f"✅ Logo herkend! Woorden: {', '.join(set(gevonden_woorden))}")
                            st.info(f"Gevonden in: {', '.join(logo_woorden_gevonden[:3])}")
                        elif len(set(gevonden_woorden)) >= 1:
                            st.warning(f"⚠️ Logo gedeeltelijk herkend: {', '.join(set(gevonden_woorden))}")
                        else:
                            st.warning("⚠️ Geen logo-teksten gevonden")
                            st.caption("Zoek naar: 'hoop', 'vertrouwen', 'moed'")
                        
                        # Check 6e traditie
                        st.markdown("---")
                        st.markdown("### 📝 6e Traditie Check")
                        
                        alle_tekst_lower = " ".join(alle_tekst).lower()
                        traditie_woorden = ["6e", "traditie", "kerken", "sekten"]
                        gevonden_traditie = []
                        
                        for woord in traditie_woorden:
                            if woord in alle_tekst_lower:
                                gevonden_traditie.append(woord)
                        
                        if len(gevonden_traditie) >= 3:
                            st.success(f"✅ 6e traditie gevonden! ({len(gevonden_traditie)}/4)")
                        elif len(gevonden_traditie) >= 2:
                            st.warning(f"⚠️ 6e traditie gedeeltelijk ({len(gevonden_traditie)}/4)")
                        else:
                            st.error("❌ 6e traditie niet gevonden")
                        
                        # Toon alle tekst
                        with st.expander("📝 Volledige OCR tekst"):
                            st.write(" ".join(alle_tekst))
                            
                except Exception as e:
                    st.error(f"❌ OCR fout: {e}")
                    st.code(str(e))
            else:
                st.error("❌ OCR is niet beschikbaar. EasyOCR kon niet laden.")
                
    except Exception as e:
        st.error(f"❌ Fout bij verwerken afbeelding: {e}")
        st.code(str(e))

else:
    st.info("👆 Upload een flyer om te beginnen")
