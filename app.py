import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import re
from difflib import SequenceMatcher

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker v2.0",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Definitieve Productie-Matrix: Genuanceerde Huisstijl-Inspectie")

def word_similarity(w1, w2):
    return SequenceMatcher(None, w1.lower().strip(), w2.lower().strip()).ratio()

@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl', 'en'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# INLADEN VAN DE 4 TRANSPARANTE REFERENTIELOGO'S (MET ALPHACHANNEL FIX)
def load_strict_reference_logos():
    paths = {
        "NL_BINNEN": "assets/logo_nl_inside.png",
        "NL_BUITEN": "assets/logo_nl_outside.png",
        "EN_BINNEN": "assets/logo_en_inside.png",
        "EN_BUITEN": "assets/logo_en_outside.png"
    }
    
    loaded_logos = {}
    missing_files = []
    
    for key, path in paths.items():
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            missing_files.append(path)
        else:
            if img.shape[2] == 4:
                alpha_channel = img[:, :, 3]
                rgb_channels = img[:, :, :3]
                white_bg = np.ones_like(rgb_channels, dtype=np.uint8) * 255
                alpha_factor = alpha_channel[:, :, np.newaxis] / 255.0
                img = (rgb_channels * alpha_factor + white_bg * (1 - alpha_factor)).astype(np.uint8)
            loaded_logos[key] = img

    if missing_files:
        st.error(f"🚨 **CRITIEKE FOUT:** De volgende referentielogo's ontbreken in de `assets/` map: {', '.join(missing_files)}. De applicatie is stopgezet.")
        st.stop()
        
    return loaded_logos

ref_logos = load_strict_reference_logos()

st.info("⚙️ **Systeemstatus:** Actief. Genuanceerde contrast-matrix geladen (v2.0).")

uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        if len(img_np.shape) == 3 and img_np.shape[2] == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        img_canvas = img_np.copy()
    except Exception as e:
        st.error(f"❌ Fout bij het verwerken van de afbeelding: {e}")
        st.stop()

    unieke_teksten = []
    gevonden_keys = set()
    tijd_regels = []
    alle_losse_woorden = []
    
    organisator_gevonden = False
    datum_gevonden = False
    tijd_gevonden = False
    locatie_gevonden = False
    telefoon_gevonden = False
    
    organisator_naam = "Onbekend"
    datum_waarde = "Onbekend"
    telefoon_waarde = "Onbekend"

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 🖼️ C.A. Logo Huisstijl Inspectie")
        
        # ---------------------------------------------------------------------
        # STAP 1: GEOMETRISCHE DETECTIE (Tolerante Hough Circles)
        # ---------------------------------------------------------------------
        blurred = cv2.medianBlur(img_gray, 5)
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=100,
            param1=50, param2=25, minRadius=20, maxRadius=600
        )
        
        best_crop = None
        detected_x, detected_y, detected_r = 0, 0, 0
        logo_gevonden_geometrisch = False
        ymin, ymax, xmin, xmax = 0, 0, 0, 0
        
        if circles is not None:
            circles = np.uint16(np.around(circles))
            for i in circles[0, :1]: 
                detected_x, detected_y, detected_r = i[0], i[1], i[2]
                
                marge = int(detected_r * 0.30)
                h_img, w_img = img_gray.shape
                ymin = max(0, detected_y - detected_r - marge)
                ymax = min(h_img, detected_y + detected_r + marge)
                xmin = max(0, detected_x - detected_r - marge)
                xmax = min(w_img, detected_x + detected_r + marge)
                
                best_crop = img_np[ymin:ymax, xmin:xmax]
                logo_gevonden_geometrisch = True
                cv2.circle(img_canvas, (detected_x, detected_y), detected_r, (255, 0, 255), 3)

        # ---------------------------------------------------------------------
        # STAP 2 & 3: MULTI-SCALE MATCHING (CRACH-FREE LOGICA via img_gray)
        # ---------------------------------------------------------------------
        logo_status = "MISSING"
        logo_taal = "ONBEKEND"
        logo_variant_detail = ""
        best_match_score = 0.0
        
        if logo_gevonden_geometrisch:
            search_area_gray = img_gray[ymin:ymax, xmin:xmax]
        else:
            search_area_gray = img_gray.copy()
        
        for variant_naam, ref_img in ref_logos.items():
            ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_RGB2GRAY)
            
            for scale in np.arange(0.2, 2.0, 0.05):
                width = int(ref_gray.shape[1] * scale)
                height = int(ref_gray.shape[0] * scale)
                
                if width > search_area_gray.shape[1] or height > search_area_gray.shape[0]:
                    continue
                    
                resized_ref = cv2.resize(ref_gray, (width, height), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(search_area_gray, resized_ref, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                
                if max_val > best_match_score:
                    best_match_score = max_val
                    logo_variant_detail = variant_naam
                    logo_taal = "NL" if "NL" in variant_naam else "EN"
                    
                    if not logo_gevonden_geometrisch:
                        detected_x, detected_y = max_loc[0] + width//2, max_loc[1] + height//2
                        detected_r = width//2
                        best_crop = img_np[max_loc[1]:max_loc[1]+height, max_loc[0]:max_loc[0]+width]

        if best_match_score >= 0.55:
            logo_status = "VERMOEDELIJK_OK"
        elif best_match_score >= 0.40:
            logo_status = "AANGEPAST"
        else:
            logo_status = "MISSING"
            
        if logo_status == "VERMOEDELIJK_OK" and not logo_gevonden_geometrisch:
            cv2.circle(img_canvas, (detected_x, detected_y), detected_r, (255, 0, 255), 3)

        # ---------------------------------------------------------------------
        # STAP 4: ORB STRUCTUUR VALIDATIE (INTEGRITEITSCHECK)
        # ---------------------------------------------------------------------
        orb_matches_gevonden = 0
        if logo_status != "MISSING" and best_crop is not None:
            if len(best_crop.shape) == 3:
                crop_gray = cv2.cvtColor(best_crop, cv2.COLOR_RGB2GRAY)
            else:
                crop_gray = best_crop.copy()
                
            target_ref = ref_logos[logo_variant_detail]
            target_ref_gray = cv2.cvtColor(target_ref, cv2.COLOR_RGB2GRAY)
            
            orb = cv2.ORB_create(nfeatures=700)
            kp1, des1 = orb.detectAndCompute(target_ref_gray, None)
            kp2, des2 = orb.detectAndCompute(crop_gray, None)
            
            if des1 is not None and des2 is not None:
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                matches = bf.match(des1, des2)
                good_matches = [m for m in matches if m.distance < 40]
                orb_matches_gevonden = len(good_matches)
                
                if orb_matches_gevonden < 12 and logo_status == "VERMOEDELIJK_OK":
                    logo_status = "AANGEPAST"

        # ---------------------------------------------------------------------
        # STAP 5: GEOPTIMALISEERDE LEESBAARHEID- EN CONTRASTCHECK (v2.0 Fix)
        # ---------------------------------------------------------------------
        logo_kleur_opmerking = "Standaard opmaak"
        if logo_status == "VERMOEDELIJK_OK" and best_crop is not None:
            if len(best_crop.shape) == 3:
                crop_hsv = cv2.cvtColor(best_crop, cv2.COLOR_RGB2HSV)
                avg_sat = np.mean(crop_hsv[:, :, 1])
                if avg_sat > 35:
                    logo_kleur_opmerking = "Aangepast aan flyer-stijl (Gekleurd)"
            
            if len(best_crop.shape) == 3:
                contrast_score = np.std(cv2.cvtColor(best_crop, cv2.COLOR_RGB2GRAY))
            else:
                contrast_score = np.std(best_crop)
                
            if contrast_score < 13:
                logo_status = "SLECHT_CONTRAST"

        # OUTPUT LOGO RAPPORTAGE (AANGEPAST VOOR DE BBQ-FLYER SITUATIE)
        st.markdown("#### 📊 C.A. Logo Validatie Rapport")
        if logo_status == "VERMOEDELIJK_OK":
            v_type = "met TM/® binnen de cirkel" if "BINNEN" in logo_variant_detail else "met TM/® buiten de cirkel"
            st.success(f"✅ **Officieel C.A.-Logo Gevalideerd!** Type: **{logo_taal} ({v_type})**.")
            st.caption(f"🎨 *Stijl-notitie: {logo_kleur_opmerking} (Vorm en structuur zijn correct).*")
            logo_score_final = 25
        elif logo_status == "SLECHT_CONTRAST":
            # --- v2.0 FIX: HARD AFKEUR OMGEBOUWD NAAR CONSTRUCTIEVE WAARSCHUWING + PARTIËLE SCORE ---
            v_type = "met TM/® binnen de cirkel" if "BINNEN" in logo_variant_detail else "met TM/® buiten de cirkel"
            st.warning(f"⚠️ **Logo gedetecteerd, maar onleesbaar (Te laag contrast).**")
            st.write(f"Vorm en variant ({logo_taal} {v_type}) zijn correct, maar het logo valt weg tegen de donkere achtergrond. Dit drukwerk is kwalitatief onvoldoende.")
            st.caption("💡 *Constructief advies: Maak het logo wit (of diepblauw) zodat het goed afsteekt.*")
            logo_score_final = 10 # Genuanceerde score in plaats van 0
        elif logo_status == "AANGEPAST":
            st.error(f"❌ **Logo inhoudelijk bewerkt:** De verhoudingen, letters of cirkelstructuur wijken af van de officiële richtlijnen. (ORB-matches: {orb_matches_gevonden})")
            logo_score_final = 0
        else:
            st.error("❌ **Kritiek Matrix-element mist:** Geen officieel C.A.-logo aangetroffen.")
            logo_score_final = 0

        # ... [OCR SABOTAGE CONTROLE & REST VAN DE MATRIX BLIJFT GELIJK] ...
