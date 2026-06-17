import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Beeldanalyse zonder OCR (stabiel op Streamlit Cloud)")

def detect_ca_logo(image_gray, logo_template_path=None):
    """
    Detecteert een CA-logo aan de hand van kleur en vorm.
    Werkt zonder OCR!
    """
    # Methode 1: Groene vlekken detecteren (CA-logo is vaak groen)
    # Converteer naar HSV voor kleurdetectie
    if len(image_gray.shape) == 2:
        # Als we alleen grayscale hebben, gebruik dan edge detection
        edges = cv2.Canny(image_gray, 50, 150)
        circles = cv2.HoughCircles(edges, cv2.HOUGH_GRADIENT, 1, 20, 
                                   param1=50, param2=30, minRadius=20, maxRadius=200)
        
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            return {
                'gevonden': len(circles) > 0,
                'aantal_cirkels': len(circles),
                'methode': 'cirkel_detectie'
            }
    
    # Methode 2: Template matching (als we een template hebben)
    # (slaan we over voor nu)
    
    # Methode 3: Check op typische CA-logo kenmerken
    # - Rond/ovaal
    # - Groen/wit
    # - Centraal geplaatst
    
    return {
        'gevonden': False,
        'aantal_cirkels': 0,
        'methode': 'geen_detectie'
    }

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    try:
        # Lees bestand
        file_bytes = uploaded_file.read()
        image_pil = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        img_np = np.array(image_pil)
        
        # Twee kolommen
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.image(img_np, caption="Geüploade flyer", use_container_width=True)
            
            # Toon afbeeldingsinformatie
            with st.expander("📊 Afbeeldingsinfo"):
                st.write(f"- Formaat: {img_np.shape[1]}x{img_np.shape[0]}")
                st.write(f"- Kleurkanalen: {img_np.shape[2] if len(img_np.shape) > 2 else 1}")
                st.write(f"- Bestandsgrootte: {len(file_bytes) / 1024:.1f} KB")
        
        with col2:
            st.markdown("### 📝 Analyse Resultaten")
            
            # ---- BEELDANALYSE ZONDER OCR ----
            
            # 1. Detecteer ronde vormen (mogelijk logo)
            img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            
            # Cirkel detectie
            circles = None
            try:
                edges = cv2.Canny(img_gray, 50, 150)
                circles = cv2.HoughCircles(edges, cv2.HOUGH_GRADIENT, 1, 20,
                                         param1=50, param2=30, minRadius=20, maxRadius=200)
            except:
                pass
            
            st.markdown("### 🖼️ Logo Detectie")
            
            logo_gevonden = False
            if circles is not None:
                circles = np.round(circles[0, :]).astype("int")
                st.success(f"✅ Ronde vorm gevonden! ({len(circles)} cirkels gedetecteerd)")
                logo_gevonden = True
                
                # Teken cirkels op afbeelding
                img_with_circles = img_np.copy()
                for (x, y, r) in circles:
                    cv2.circle(img_with_circles, (x, y), r, (0, 255, 0), 2)
                
                # Toon afbeelding met cirkels
                st.image(img_with_circles, caption="Cirkel detectie", use_container_width=True)
            else:
                st.warning("⚠️ Geen ronde vormen gedetecteerd")
            
            # 2. Kleuranalyse (groene componenten)
            # Converteer naar HSV
            hsv = cv2.cvtColor(img_np, cv2.COLOR_RGB2HSV)
            
            # Groene kleur detectie (CA-logo is vaak groen)
            lower_green = np.array([35, 40, 40])
            upper_green = np.array([85, 255, 255])
            
            green_mask = cv2.inRange(hsv, lower_green, upper_green)
            green_percentage = (np.sum(green_mask > 0) / green_mask.size) * 100
            
            st.markdown("### 🎨 Kleuranalyse")
            st.write(f"Groene pixels: {green_percentage:.2f}% van de afbeelding")
            
            if green_percentage > 1:
                st.success("✅ Aanzienlijke groene component gevonden (CA-logo kenmerk)")
                logo_gevonden = True
            else:
                st.info("ℹ️ Weinig groene pixels gedetecteerd")
            
            # 3. Totaal oordeel
            st.markdown("---")
            st.markdown("### 📊 Samenvattend Oordeel")
            
            if logo_gevonden:
                st.success("✅ **Logo waarschijnlijk aanwezig** (ronde vorm + groene kleur)")
            else:
                st.warning("⚠️ **Logo niet gedetecteerd**")
                st.caption("Tip: Zorg voor voldoende contrast en duidelijke ronde vormen")
            
            # 4. Handmatige invoer (als fallback)
            st.markdown("---")
            st.markdown("### ✍️ Handmatige Controle")
            
            logo_handmatig = st.radio(
                "Is er een CA-logo zichtbaar op deze flyer?",
                ["Weet ik niet", "Ja, logo is zichtbaar", "Nee, geen logo"]
            )
            
            if logo_handmatig == "Ja, logo is zichtbaar":
                st.success("✅ Logobeschikbaarheid bevestigd")
            elif logo_handmatig == "Nee, geen logo":
                st.error("❌ Geen logo aanwezig")
            
            # 5. Opmerkingen over andere elementen
            st.markdown("---")
            st.markdown("### 📋 Andere Elementen")
            
            # Check op tekstindicatoren (zonder OCR)
            # We kunnen niet lezen, maar we kunnen wel checken of er veel tekst is
            # door het contrast en edge density te meten
            
            edges = cv2.Canny(img_gray, 100, 200)
            edge_density = np.sum(edges > 0) / edges.size
            
            st.write(f"Tekstdichtheid indicator: {edge_density*100:.2f}%")
            
            if edge_density > 0.05:
                st.info("ℹ️ Veel tekst gedetecteerd (waarschijnlijk flyer met inhoud)")
            else:
                st.info("ℹ️ Weinig tekst gedetecteerd")
                
    except Exception as e:
        st.error(f"❌ Fout bij verwerken afbeelding: {e}")
        import traceback
        st.code(traceback.format_exc())

else:
    st.info("👆 Upload een flyer om te beginnen met de analyse")
    
    st.markdown("""
    ### 📋 Wat deze checker doet (zonder OCR):
    
    1. **Logo detectie** - Zoekt naar ronde vormen en groene kleuren (kenmerkend voor CA-logo)
    2. **Kleuranalyse** - Meet hoeveel groen er in de afbeelding zit
    3. **Edge detectie** - Meet hoeveel tekst er ongeveer aanwezig is
    4. **Handmatige controle** - Laat de gebruiker bevestigen of logo zichtbaar is
    
    ### Voordelen van deze aanpak:
    - ✅ **Werkt altijd** op Streamlit Cloud (geen externe dependencies)
    - ✅ **Snel** - geen OCR nodig
    - ✅ **Geen geheugenproblemen** - lichtgewicht
    - ✅ **Geen taalmodel nodig** - werkt voor alle talen
    
    ### Beperkingen:
    - ⚠️ Kan geen tekst lezen
    - ⚠️ Alleen visuele patronen herkennen
    - ⚠️ Minder nauwkeurig dan OCR
    """)
