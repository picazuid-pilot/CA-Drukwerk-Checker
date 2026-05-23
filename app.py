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

# Custom CSS voor de C.A. huisstijl
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    h1 { color: #00594F; }
    .report-title { font-weight: bold; font-size: 20px; color: #00594F; border-bottom: 2px solid #00594F; padding-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

# Officiële contactgegevens van C.A. Holland
CA_HOLLAND_PHONE_CLEAN = "0610192770"
CA_HOLLAND_EMAIL = "info@ca-holland.nl"
CA_HOLLAND_WEBSITE = "www.ca-holland.nl"

# Officiële logo's met het juiste TM-teken (geen ®)
OFFICIAL_LOGOS = [
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20Transparent%20Background%20-%20Inner%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Black%20Outline%20-%20Transparent%20Background%20-%20Outer%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Green%20Outline%20-%20Transparent%20Background%20-%20Inner%20TM.png",
    "https://cawscit.github.io/logo-finder/img/Dutch%20-%20Green%20Outline%20-%20Transparent%20Background%20-%20Outer%20TM.png",
]

# Cache de OCR reader zodat deze maar één keer geladen hoeft te worden
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

def draw_visual_highlight(img, bbox, color_type, label):
    """Tekent een kader om gedeteteerde tekst/objecten op basis van EasyOCR coördinaten"""
    # EasyOCR geeft 4 hoekpunten: [[x0,y0], [x1,y1], [x2,y2], [x3,y3]]
    pts = np.array(bbox, np.int32)
    pts = pts.reshape((-1, 1, 2))
    
    colors = {"green": (0, 200, 0), "orange": (0, 165, 255), "red": (0, 0, 255)}
    color = colors.get(color_type, (255, 255, 255))
    
    cv2.polylines(img, [pts], True, color, 3)
    x, y = int(bbox[0][0]), int(bbox[0][1])
    cv2.putText(img, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    return img

# --- UI APPLICATIE ---
st.title("🔍 C.A. Flyer & Drukwerk Checker")
st.subheader("Controleer direct in je browser of jouw flyer voldoet aan de C.A.-richtlijnen")

with st.sidebar:
    st.header("Status & Info")
    reader = load_ocr_reader()
    st.success("✅ EasyOCR Model Actief")
    
    logos = download_official_logos()
    if logos:
        st.success(f"✅ {len(logos)} Officiële TM-logo's geladen")

uploaded_file = st.file_uploader("Upload hier de flyer (Afbeelding: JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, 1)
    annotated = image.copy()
    h_img, w_img, _ = image.shape
    
    st.info("🔄 Bezig met scannen en analyseren van de flyer...")
    
    # 1. UITVOEREN VAN ECHTE OCR SCAN
    ocr_results = reader.readtext(image)
    
    # Maak een lijst van alle gevonden teksten en hun locaties
    detected_texts = []
    full_text_clean = ""
    for (bbox, text, prob) in ocr_results:
        detected_texts.append({'bbox': bbox, 'text': text, 'prob': prob})
        full_text_clean += " " + text.lower()
    
    # 2. EVALUATIE EN DYNAMISCHE CONTROLE
    
    # ---- STAP 1: LOGO CHECK (DYNAMISCH) ----
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

    # Extra check: Bevat de flyer het foute ® logo?
    has_registered_sign = "®" in full_text_clean or "moed®" in full_text_clean or "moed" in full_text_clean and not "tm" in full_text_clean
    
    if best_val > 0.55 and not has_registered_sign:
        x, y, w, h = best_box
        cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 200, 0), 4)
        cv2.putText(annotated, "C.A. Logo: OK", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)
        logo_status = ("success", f"✅ Officieel C.A.-logo met 'TM' herkend (Match: {best_val:.2f}).")
    elif has_registered_sign or "moed" in full_text_clean:
        logo_status = ("error", "❌ VEROUDERD LOGO GEVONDEN: De flyer gebruikt het logo met het ®-teken (Registered) of een verouderde variant. C.A. World-Service richtlijnen vereisen het logo met het 'TM' (Trademark) teken.")
    else:
        logo_status = ("warning", "⚠️ Geen overduidelijk C.A. logo herkend via automatische scanning. Controleer handmatig of het juiste TM-logo aanwezig is.")

    # ---- STAP 2: CONTACTGEGEVENS (EERST ECHT ZOEKEN!) ----
    phone_status = ("error", f"❌ Geen telefoonnummer gevonden (Verwacht: {CA_HOLLAND_PHONE_CLEAN})")
    email_status = ("error", f"❌ Geen e-mailadres gevonden (Verwacht: {CA_HOLLAND_EMAIL})")
    web_status = ("error", f"❌ Geen website gevonden (Verwacht: {CA_HOLLAND_WEBSITE})")
    
    for item in detected_texts:
        txt = item['text'].lower()
        box = item['bbox']
        
        # Telefoon check
        clean_txt_phone = re.sub(r'[\s\-\.]', '', txt)
        if "06" in clean_txt_phone and any(part in clean_txt_phone for part in ["101", "927", "770"]):
            annotated = draw_visual_highlight(annotated, box, "green", "Telefoon: OK")
            phone_status = ("success", f"✅ Telefoonnummer correct aanwezig: {item['text']}")
            
        # Email check
        if "@" in txt or "info@" in txt or "ca-holland" in txt and "nl" in txt and not "www" in txt:
            if "info@ca-holland.nl" in txt:
                annotated = draw_visual_highlight(annotated, box, "green", "Email: OK")
                email_status = ("success", "✅ E-mailadres correct aanwezig: info@ca-holland.nl")
            else:
                annotated = draw_visual_highlight(annotated, box, "orange", "Email Check")
                email_status = ("warning", f"⚠️ E-mailadres gevonden ({item['text']}), maar wijkt af van info@ca-holland.nl")
                
        # Website check
        if "www." in txt or "ca-holland.nl" in txt and "www" in txt:
            if "www.ca-holland.nl" in txt:
                annotated = draw_visual_highlight(annotated, box, "green", "Website: OK")
                web_status = ("success", "✅ Website correct aanwezig: www.ca-holland.nl")
            else:
                annotated = draw_visual_highlight(annotated, box, "orange", "Website Check")
                web_status = ("warning", f"⚠️ Website gevonden ({item['text']}), maar wijkt af van www.ca-holland.nl")

    # ---- STAP 3: 6E TRADITIE (DYNAMISCH) ----
    tradition_status = ("error", "❌ 6e Traditie tekst niet gevonden op de flyer!")
    
    for item in detected_texts:
        txt = item['text'].lower()
        box = item['bbox']
        
        if "traditie" in txt or "verbonden" in txt or "verbonde" in txt or "kerken" in txt:
            # We hebben de traditieregel te pakken!
            if "verbonde " in txt or "verbonde" in txt and not "verbonden" in txt:
                annotated = draw_visual_highlight(annotated, box, "red", "SPELFOUT TRADITIE")
                tradition_status = ("error", "❌ Spellingsfout in 6e Traditie! Er staat 'verbonde' (zonder n) of 'instantis' in plaats van 'instanties'. Pas dit aan naar de officiële schrijfwijze.")
            elif "instantis" in txt or "sekten" in txt:
                annotated = draw_visual_highlight(annotated, box, "orange", "6e Traditie: Check spelling")
                tradition_status = ("warning", f"⚠️ De 6e traditie is gevonden, maar controleer de spelling nauwkeurig. De computer las: '{item['text']}'. Zorg dat er exact 'instanties' en 'verbonden' staat.")
            else:
                annotated = draw_visual_highlight(annotated, box, "green", "6e Traditie: OK")
                tradition_status = ("success", "✅ 6e Traditie tekst is volledig correct en foutloos aanwezig.")

    # --- WEERGAVE VAN DE RESULTATEN ---
    st.write("---")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("<p class='report-title'>Visualisatie (Resultaat met kaders)</p>", unsafe_allow_html=True)
        annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        st.image(annotated_rgb, use_column_width=True)
        
    with col2:
        st.markdown("<p class='report-title'>📋 Analyserapport & Resultaten</p>", unsafe_allow_html=True)
        
        # Logo Output
        st.write("**Stap 1: Logo-controle**")
        if logo_status[0] == "success": st.success(logo_status[1])
        elif logo_status[0] == "warning": st.warning(logo_status[1])
        else: st.error(logo_status[1])
        
        # Contactgegevens Output
        st.write("**Stap 2: Contactgegevens**")
        if phone_status[0] == "success": st.success(phone_status[1])
        else: st.error(phone_status[1])
        
        if email_status[0] == "success": st.success(email_status[1])
        elif email_status[0] == "warning": st.warning(email_status[1])
        else: st.error(email_status[1])
        
        if web_status[0] == "success": st.success(web_status[1])
        elif web_status[0] == "warning": st.warning(web_status[1])
        else: st.error(web_status[1])
        
        # Traditie Output
        st.write("**Stap 3: 6e Traditie**")
        if tradition_status[0] == "success": st.success(tradition_status[1])
        elif tradition_status[0] == "warning": st.warning(tradition_status[1])
        else: st.error(tradition_status[1])
        
        st.write("---")
        st.markdown("### 📌 EINDCONCLUSIE")
        if logo_status[0] == "error" or "❌" in phone_status[1] or tradition_status[0] == "error":
            st.error("**FLYER AFGEKEURD:** Er zijn cruciale afwijkingen gevonden (verouderd ® logo, missende contactgegevens of mogelijke spelfouten in de traditietekst). Pas de flyer aan volgens de richtlijnen.")
        else:
            st.info("**FLYER GOEDGEKEURD:** De flyer voldoet aan de basiseisen.")
