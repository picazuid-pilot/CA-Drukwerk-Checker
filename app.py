import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import traceback

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker - Debug",
    page_icon="🔧",
    layout="wide"
)

st.title("🔧 C.A. Drukwerk Checker - Debug Modus")
st.subheader("Stap-voor-stap debuggen van de afbeelding")

# 1. EERST: Check of OpenCV werkt
try:
    st.write("✅ OpenCV geladen")
except Exception as e:
    st.error(f"❌ OpenCV fout: {e}")

# 2. Check PIL
try:
    from PIL import Image
    st.write("✅ PIL geladen")
except Exception as e:
    st.error(f"❌ PIL fout: {e}")

# 3. Probeer EasyOCR (met fallback)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
    st.write("✅ EasyOCR geïnstalleerd")
except ImportError:
    EASYOCR_AVAILABLE = False
    st.warning("⚠️ EasyOCR niet geïnstalleerd (werkt zonder OCR)")

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.write("---")
    st.write("### 📁 Bestand verwerken...")
    
    try:
        # STAP 1: Lees bytes
        file_bytes = uploaded_file.read()
        st.write(f"✅ Bestand gelezen: {len(file_bytes)} bytes")
        
        # STAP 2: Open met PIL
        try:
            image_pil = Image.open(io.BytesIO(file_bytes))
            st.write(f"✅ PIL afbeelding geopend: {image_pil.size}, mode: {image_pil.mode}")
            
            # Converteer naar RGB als nodig
            if image_pil.mode != "RGB":
                image_pil = image_pil.convert("RGB")
                st.write(f"   → Geconverteerd naar RGB")
            
        except Exception as e:
            st.error(f"❌ PIL fout: {e}")
            st.code(traceback.format_exc())
            st.stop()
        
        # STAP 3: Converteer naar numpy array
        try:
            img_np = np.array(image_pil)
            st.write(f"✅ Numpy array: {img_np.shape}, dtype: {img_np.dtype}")
        except Exception as e:
            st.error(f"❌ Numpy conversie fout: {e}")
            st.code(traceback.format_exc())
            st.stop()
        
        # STAP 4: Toon afbeelding
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.image(img_np, caption="Afbeelding geladen", use_container_width=True)
        
        with col2:
            st.write("### 📊 Afbeeldingsinfo")
            st.write(f"- Formaat: {img_np.shape[1]}x{img_np.shape[0]}")
            st.write(f"- Kanale: {img_np.shape[2] if len(img_np.shape) > 2 else 1}")
            st.write(f"- Min waarde: {img_np.min()}")
            st.write(f"- Max waarde: {img_np.max()}")
            
        # STAP 5: Probeer OpenCV conversie
        try:
            if len(img_np.shape) == 3 and img_np.shape[2] == 3:
                img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                st.write(f"✅ Grayscale conversie: {img_gray.shape}")
            else:
                st.warning(f"⚠️ Onverwacht kleurenformaat: {img_np.shape}")
        except Exception as e:
            st.error(f"❌ OpenCV conversie fout: {e}")
            st.code(traceback.format_exc())
        
        # STAP 6: Probeer OCR (alleen als beschikbaar)
        st.write("---")
        st.write("### 🔍 OCR Test")
        
        if EASYOCR_AVAILABLE:
            try:
                # Vertraagde import om memory te besparen
                import easyocr
                
                st.write("EasyOCR initialiseren...")
                reader = easyocr.Reader(['en'], gpu=False)
                st.write("✅ EasyOCR reader aangemaakt")
                
                with st.spinner("OCR scan bezig..."):
                    results = reader.readtext(img_np, detail=0)
                    st.write(f"✅ OCR scan voltooid: {len(results)} regels gevonden")
                    
                    if results:
                        st.write("### 📝 Gevonden tekst:")
                        for i, text in enumerate(results[:20]):
                            st.write(f"{i+1}. `{text}`")
                        if len(results) > 20:
                            st.write(f"... en nog {len(results)-20} regels")
                    else:
                        st.warning("⚠️ Geen tekst gevonden in afbeelding")
                        
            except Exception as e:
                st.error(f"❌ OCR fout: {e}")
                st.code(traceback.format_exc())
        else:
            st.info("ℹ️ EasyOCR niet beschikbaar, sla OCR over")
            
    except Exception as e:
        st.error(f"❌ Algemene fout: {e}")
        st.code(traceback.format_exc())

else:
    st.info("👆 Upload een flyer om te beginnen met debuggen")
    
    st.write("### 📋 Wat er getest wordt:")
    st.write("1. ✅ Bestand lezen")
    st.write("2. ✅ PIL afbeelding openen")
    st.write("3. ✅ Numpy conversie")
    st.write("4. ✅ Afbeelding weergeven")
    st.write("5. ✅ OpenCV conversie")
    st.write("6. ✅ EasyOCR (indien beschikbaar)")
