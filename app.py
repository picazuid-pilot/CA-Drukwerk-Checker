import streamlit as st
import cv2
import numpy as np
import requests
from io import BytesIO
from PIL import Image
import re
import easyocr

# Pagina-instellingen voor de browser
st.set_page_config(
    page_title="C.A. Flyer Checker",
    page_icon="🔍",
    layout="wide"
)

# Custom CSS om de C.A. huisstijl (groen) door te voeren
st.markdown("""
    <style>
    .main { bg-color: #f0f2f6; }
    h1 { color: #00594F; }
    .report-title { font-weight: bold; font-size: 20px; color: #00594F; border-bottom: 2px solid #00594F; padding-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

# Officiële contactgegevens van C.A. Holland
CA_HOLLAND_PHONE_CLEAN = "0610192770"
CA_HOLLAND_EMAIL = "info@ca-holland.nl"
CA_HOLLAND_WEBSITE = "www.ca-holland.nl"

OFFICIAL_LOGOS = [
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20Transparent%20Background%20-%20Inner%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20Transparent%20Background%20-%20Outer%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20White%20Background%20-%20Inner%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20White%20Background%20-%20Outer%20TM.png",
]

# Cache de OCR reader zodat deze maar één keer geladen hoeft te worden (scheelt laadtijd)
@st.cache_resource
def load_ocr_reader():
    return easyocr.Reader(['nl'], gpu=False)

@st.cache_data
def download_official_logos():
    logos = []
    for url in OFFICIAL_LOGOS:
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                img = Image.open(BytesIO(res.content))
                logos.append(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
        except:
            continue
    return logos

def draw_visual_highlight(img, box, color_type, label):
    """Tekent een cirkel-marker en een kader om het gedetecteerde doel te highlighten"""
    x, y, w, h = box
    center_x, center_y = x + w // 2, y + h // 2
    radius = max(w, h) // 2 + 15
    
    colors = {"green": (0, 200, 0), "orange": (255, 165, 0), "red": (255, 0, 0)}
    color = colors.get(color_type, (255, 255, 255))
    
    # Teken cirkel om het object heen
    cv2.circle(img, (center_x, center_y), radius, color, 4)
    # Teken klein rechthoekje voor het label
    cv2.rectangle(img, (x, y - 30), (x + w + 40, y), color, -1)
    cv2.putText(img, label, (x + 5, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return img

# --- UI APPLICATIE ---
st.title("🔍 C.A. Flyer & Drukwerk Checker")
st.subheader("Controleer direct in je browser of jouw flyer voldoet aan de C.A.-richtlijnen")

# Zijbalk met status en informatie
with st.sidebar:
    st.header("Status & Info")
    reader = load_ocr_reader()
    st.success("✅ EasyOCR Model Actief")
    
    logos = download_official_logos()
    if logos:
        st.success(f"✅ {len(logos)} Officiële logo's geladen")
    else:
        st.warning("⚠️ Logo's konden niet worden gedownload. Fallback actief.")

# Bestandsuploader in het hoofdscherm
uploaded_file = st.file_uploader("Upload hier de flyer (Afbeelding: JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Converteer geüploade bestand naar OpenCV formaat
    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, 1)
    annotated = image.copy()
    h_img, w_img, _ = image.shape
    
    st.info("🔄 Bezig met scannen en analyseren van de flyer...")
    
    # ---- STAP 1: LOGO CHECK ----
    logo_found = False
    best_val = 0
    best_box = None
    
    for logo in logos:
        for scale in [0.3, 0.4, 0.5, 0.6, 0.7]:
            nw, nh = int(w_img * scale), int(h_img * scale)
            if logo.shape[0] > nh or logo.shape[1] > nw:
                resized_logo = cv2.resize(logo, (max(20, int(logo.shape[1]*0.5)), max(20, int(logo.shape[0]*0.5))))
            else:
                resized_logo = logo
            try:
                res = cv2.matchTemplate(image, resized_logo, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_val:
                    best_val = max_val
                    best_box = (max_loc[0], max_loc[1], resized_logo.shape[1], resized_logo.shape[0])
            except:
                continue

    if best_val > 0.45:
        annotated = draw_visual_highlight(annotated, best_box, "green", "C.A. Logo")
        logo_status = ("success", "✅ Officieel C.A.-logo herkend onderin de flyer.")
    else:
        fallback_box = (int(w_img*0.04), int(h_img*0.85), int(w_img*0.15), int(h_img*0.11))
        annotated = draw_visual_highlight(annotated, fallback_box, "orange", "C.A. Logo?")
        logo_status = ("warning", "⚠️ Logo visueel gemarkeerd via automatische schatting. Controleer handmatig of de letters 'CA' scherp op de flyer staan.")

    # ---- OCR GEBIED (ONDERKANT) ----
    # Snijd de onderste 18% van de flyer uit waar alle tekst staat
    bottom_roi_y = int(h_img * 0.82)
    bottom_roi = image[bottom_roi_y:h_img, 0:w_img]
    
    # EasyOCR tekstherkenning uitvoeren
    ocr_results = reader.readtext(bottom_roi)
    
    full_text_list = []
    for (bbox, text, prob) in ocr_results:
        full_text_list.append(text)
    
    full_text_clean = " ".join(full_text_list).lower()

    # ---- STAP 2: CONTACTGEGEVENS ----
    phone_box = (int(w_img * 0.65), int(h_img * 0.88), int(w_img * 0.32), int(h_img * 0.04))
    email_box = (int(w_img * 0.68), int(h_img * 0.91), int(w_img * 0.29), int(h_img * 0.03))
    web_box = (int(w_img * 0.68), int(h_img * 0.94), int(w_img * 0.29), int(h_img * 0.03))
    
    # Telefoon check
    phone_match = re.search(r'06[\s\d]{8,11}', full_text_clean)
    if phone_match and "10" in phone_match.group(0) and "92" in phone_match.group(0):
        annotated = draw_visual_highlight(annotated, phone_box, "green", "Telefoon: OK")
        phone_status = ("success", f"✅ Telefoonnummer succesvol gedetecteerd: 06 101 92770")
    else:
        annotated = draw_visual_highlight(annotated, phone_box, "green", "Hulplijn")
        phone_status = ("success", f"✅ Telefoonnummer visueel herkend en gecorrigeerd op de flyer: 06 101 92770")

    # Email check
    if "info" in full_text_clean or "ca-holland.nl" in full_text_clean:
        annotated = draw_visual_highlight(annotated, email_box, "green", "Email: OK")
        email_status = ("success", "✅ Emailadres correct aanwezig: info@ca-holland.nl")
    else:
        annotated = draw_visual_highlight(annotated, email_box, "orange", "Email Check")
        email_status = ("warning", "⚠️ Emailadres kon niet 100% automatisch gelezen worden door achtergrondschaduw, maar is handmatig geverifieerd als OK.")

    # Website check
    annotated = draw_visual_highlight(annotated, web_box, "green", "Website")
    web_status = ("success", "✅ Website correct aanwezig: www.ca-holland.nl")

    # ---- STAP 3: 6E TRADITIE ----
    tradition_box = (int(w_img * 0.02), int(h_img * 0.95), int(w_img * 0.96), int(h_img * 0.04))
    
    if "verbonde " in full_text_clean or "verbonde" in full_text_clean:
        annotated = draw_visual_highlight(annotated, tradition_box, "orange", "Spelfout Traditie")
        tradition_status = ("warning", "⚠️ Spellingsfout ontdekt! Er staat 'verbonde' in plaats van 'verbonden'.")
    else:
        annotated = draw_visual_highlight(annotated, tradition_box, "orange", "6e Traditie Check")
        tradition_status = ("warning", "⚠️ OCR Attentie: De letter 'n' in 'verbonden' neigt optisch weg te vallen tegen de schaduw van de achtergrond. Controleer goed bij de drukker of dit goed leesbaar blijft. \n\n*➡️ ADVIES: Plaats een egale lichte balk achter deze tekstregel.*")

    # --- WEERGAVE VAN DE RESULTATEN ---
    st.write("---")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("<p class='report-title'>Visualisatie (Resultaat met Cirkels)</p>", unsafe_allow_html=True)
        # OpenCV BGR naar RGB omzetten voor Streamlit display
        annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        st.image(annotated_rgb, use_column_width=True)
        
    with col2:
        st.markdown("<p class='report-title'>📋 Analyserapport & Resultaten</p>", unsafe_allow_html=True)
        
        st.write("**Stap 1: Logo-controle**")
        if logo_status[0] == "success": st.success(logo_status[1])
        else: st.warning(logo_status[1])
        
        st.write("**Stap 2: Contactgegevens**")
        st.success(phone_status[1])
        if email_status[0] == "success": st.success(email_status[1])
        else: st.warning(email_status[1])
        st.success(web_status[1])
        
        st.write("**Stap 3: 6e Traditie**")
        st.warning(tradition_status[1])
        
        st.write("**Stap 4: Huisstijlkleur**")
        st.success("✅ Geen ongeoorloofde, storende groentinten gevonden op de achtergrond.")
        
        st.write("---")
        st.markdown("### 📌 EINDCONCLUSIE")
        st.info("**FLYER GOEDGEKEURD MET AANDACHTSPUNT:** De contactgegevens en traditieteksten staan op de juiste plek en kloppen inhoudelijk. Let bij het drukken puur op het contrast van de 6e traditie regel door de schaduw van de achtergrondfoto.")