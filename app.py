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
    page_title="C.A. Holland - Flyer Checker",
    page_icon="🔍",
    layout="wide"
)

# Custom CSS voor de C.A. huisstijl
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    h1, h2, h3 { color: #00594F; }
    .report-title { font-weight: bold; font-size: 20px; color: #00594F; border-bottom: 2px solid #00594F; padding-bottom: 5px; margin-bottom: 15px; }
    </style>
    """, unsafe_allow_html=True)

# Constanten
CA_HOLLAND_PHONE_CLEAN = "0610192770"
CA_HOLLAND_EMAIL_REGEX = r'[A-Za-z0-9._%+-]+@ca-holland\.nl'
ANY_EMAIL_REGEX = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

OFFICIAL_LOGOS = [
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20Transparent%20Background%20-%20Inner%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20Transparent%20Background%20-%20Outer%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Green%20Outline%20-%20Transparent%20Background%20-%20Inner%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Green%20Outline%20-%20Transparent%20Background%20-%20Outer%20TM.png",
]

@st.cache_resource
def load_ocr_reader():
    return easyocr.Reader(['nl', 'en'], gpu=False)

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

def draw_visual_highlight(img, bbox, color_type, label):
    pts = np.array(bbox, np.int32).reshape((-1, 1, 2))
    colors = {"green": (0, 200, 0), "orange": (0, 165, 255), "red": (0, 0, 255)}
    color = colors.get(color_type, (255, 255, 255))
    cv2.polylines(img, [pts], True, color, 3)
    x, y = int(bbox[0][0]), int(bbox[0][1])
    cv2.putText(img, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    return img

def check_tradition_6(full_text):
    text_lower = full_text.lower()
    indicators = ["traditie", "geest", "verbonden", "kerken", "sekten", "politieke", "hulpverlenende", "instanties", "ca is niet", "c.a."]
    matches = sum(1 for word in indicators if word in text_lower)
    return matches >= 3

# --- UI APPLICATIE ---
st.title("🔍 C.A. Flyer & Matrix Checker")
st.subheader("Controleer of jouw flyer voldoet aan de officiële richtlijnen van C.A. Holland")

with st.sidebar:
    st.header("Status")
    reader = load_ocr_reader()
    st.success("✅ OCR Model Actief")
    logos = download_official_logos()
    if logos:
        st.success(f"✅ {len(logos)} TM-logo's ingeladen")

uploaded_file = st.file_uploader("Upload de flyer afbeelding (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, 1)
    annotated = image.copy()
    h_img, w_img, _ = image.shape
    
    with st.spinner("Bezig met scannen en matrixanalyse..."):
        ocr_results = reader.readtext(image)
        
        detected_texts = []
        full_text_clean = ""
        for (bbox, text, prob) in ocr_results:
            detected_texts.append({'bbox': bbox, 'text': text, 'prob': prob})
            full_text_clean += " " + text
            
        clean_text_no_spaces = full_text_clean.replace(" ", "").lower()

        # ---- 1. LOGO CHECK ----
        logo_found = False
        best_val = 0
        best_box = None

        for logo in logos:
            for scale in [0.2, 0.3, 0.4, 0.5]:
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

        has_registered_sign = "®" in full_text_clean.lower() or "moed®" in full_text_clean.lower()
        if best_val > 0.55 and not has_registered_sign:
            logo_found = True
            x, y, w, h = best_box
            cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 200, 0), 4)
            logo_status = ("success", f"✅ Officieel C.A.-logo met 'TM' herkend (Match: {best_val:.2f}).")
        elif has_registered_sign:
            logo_status = ("error", "❌ VEROUDERD LOGO: De flyer gebruikt het logo met het ®-teken. Dit moet verplicht het 'TM' logo zijn.")
        else:
            # Fallback op tekstbasis mocht de beeldherkenning falen
            if any(x in full_text_clean.lower() for x in ["cocaine anonymous", "c.a. holland"]):
                logo_found = True
                logo_status = ("success", "✅ C.A. Naam/Logo via tekstherkenning vastgesteld.")
            else:
                logo_status = ("error", "❌ Geen officieel C.A. logo of duidelijke naamvermelding gedetecteerd.")
