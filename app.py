import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import re
from difflib import SequenceMatcher
import os

# Pagina-instellingen
st.set_page_config(
    page_title="C.A. Drukwerk Checker v3.0",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Architectuur v3.0: OCR-Clustering & SIFT-Homografie Validatie")

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

# Inladen van de referentielogo's met debug
def load_reference_logos():
    paths = {
        "NL_BINNEN": "assets/logo_nl_inside.png",
        "NL_BUITEN": "assets/logo_nl_outside.png",
        "EN_BINNEN": "assets/logo_en_inside.png",
        "EN_BUITEN": "assets/logo_en_outside.png"
    }
    loaded_logos = {}
    
    st.sidebar.write("### 🔍 Logo Loading Debug")
    for key, path in paths.items():
        if os.path.exists(path):
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                loaded_logos[key] = img
                st.sidebar.write(f"✅ {key}: {path} ({img.shape})")
            else:
                st.sidebar.error(f"❌ Kon niet lezen: {path}")
        else:
            st.sidebar.error(f"❌ Bestand niet gevonden: {path}")
    
    st.sidebar.write(f"**Totaal geladen: {len(loaded_logos)}**")
    return loaded_logos

ref_logos = load_reference_logos()

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

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 🖼️ C.A. Logo Huisstijl Inspectie")
        
        # ---------------------------------------------------------------------
        # STAP 1 & 2: MULTI-PASS OCR & HOOFD-SCAN
        # ---------------------------------------------------------------------
        with st.spinner("Scannen van flyertekst en lokaliseren van logo-cluster..."):
            # Meerdere OCR-passes voor betere detectie
            img_enhanced = cv2.adaptiveThreshold(img_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            
            # Ook een contrast-verbeterde versie
            img_contrast = cv2.equalizeHist(img_gray)
            
            ocr_results = (
                reader.readtext(img_np, detail=1) + 
                reader.readtext(img_enhanced, detail=1) +
                reader.readtext(img_contrast, detail=1)
            )
            
            # Trefwoorden definities
            logo_keywords_nl = ["hoop", "vertrouwen", "moed"]
            logo_keywords_en = ["hope", "faith", "courage"]
            sabotage_keywords = ["unity", "service", "recovery", "just for today", "powerlessness", "serenity"]
            
            logo_bboxes = []
            sabotage_gevonden = set()
            gevonden_keys = set()
            unieke_teksten = []
            tijd_regels = []
            alle_losse_woorden = []
            
            nl_keyword_matches = set()
            en_keyword_matches = set()
            
            # DEBUG: toon gevonden woorden
            st.sidebar.write("### 📝 OCR Debug")
            st.sidebar.write("**Gevonden tekstfragmenten:**")

            for (bbox, text, prob) in ocr_results:
                if prob < 0.20:  # Verlaagd van 0.25
                    continue
                txt_clean = text.replace("I", "1").replace("l", "1").replace("O", "0")
                key = txt_clean.lower().strip()
                
                if key in gevonden_keys:
                    continue
                gevonden_keys.add(key)
                unieke_teksten.append(txt_clean)
                
                # Toon eerste 30 gevonden teksten in sidebar
                if len(gevonden_keys) <= 30:
                    st.sidebar.write(f"• `{txt_clean}`")
                
                woorden_in_regel = key.split()
                alle_losse_woorden.extend(woorden_in_regel)
                
                # Check voor logo-baken woorden (NL & EN) met lagere threshold
                for kw in logo_keywords_nl:
                    if kw in key or any(word_similarity(kw, w) >= 0.65 for w in woorden_in_regel):
                        logo_bboxes.append(bbox)
                        nl_keyword_matches.add(kw)
                        st.sidebar.write(f"  ✅ NL match: '{kw}'")
                for kw in logo_keywords_en:
                    if kw in key or any(word_similarity(kw, w) >= 0.65 for w in woorden_in_regel):
                        logo_bboxes.append(bbox)
                        en_keyword_matches.add(kw)
                        st.sidebar.write(f"  ✅ EN match: '{kw}'")
                        
                # Check voor cross-fellowship sabotage
                for skw in sabotage_keywords:
                    if skw in key or any(word_similarity(skw, w) >= 0.85 for w in woorden_in_regel):
                        sabotage_gevonden.add(skw)

                # Reguliere matrix-visualisatie (groen voor tekst, blauw voor tijd)
                tl = tuple(map(int, bbox[0]))
                br = tuple(map(int, bbox[2]))
                cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 1)
                if re.search(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean):
                    tijd_regels.append(txt_clean)
                    cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 2)

            volledige_tekst = " ".join(unieke_teksten)
            txt_lower = volledige_tekst.lower()
            
            st.sidebar.write(f"**Totaal woorden gevonden: {len(alle_losse_woorden)}**")
            st.sidebar.write(f"**NL logo matches: {len(nl_keyword_matches)}**")
            st.sidebar.write(f"**EN logo matches: {len(en_keyword_matches)}**")

        # ---------------------------------------------------------------------
        # STAP 3 & 4: CLUSTERING & DYNAMISCHE CROP
        # ---------------------------------------------------------------------
        best_crop = None
        logo_status = "MISSING"
        logo_taal = "ONBEKEND"
        
        if len(logo_bboxes) >= 1:
            all_pts = []
            for box in logo_bboxes:
                for pt in box:
                    all_pts.append([int(pt[0]), int(pt[1])])
            
            # Bereken de strakke bounding box
            x, y, w, h = cv2.boundingRect(np.array(all_pts))
            
            # Uitbreiden met 300% voor betere SIFT-detectie
            marge_x = int(w * 1.5) 
            marge_y = int(h * 1.5)
            
            h_img, w_img = img_gray.shape
            ymin = max(0, y - marge_y)
            ymax = min(h_img, y + h + marge_y)
            xmin = max(0, x - marge_x)
            xmax = min(w_img, x + w + marge_x)
            
            # Verbeter contrast van de crop
            best_crop = img_gray[ymin:ymax, xmin:xmax]
            best_crop = cv2.equalizeHist(best_crop)  # Contrast verbeteren
            
            # Teken de paarse cluster-box
            cv2.rectangle(img_canvas, (xmin, ymin), (xmax, ymax), (255, 0, 255), 3)
            
            st.sidebar.write(f"**Crop size:** {best_crop.shape}")
        else:
            st.sidebar.warning("⚠️ Geen logo-bakens gevonden in OCR!")

        # Toon de crop in de UI
        if best_crop is not None:
            st.image(best_crop, caption="Dynamische crop voor SIFT-analyse", use_container_width=True)
        else:
            st.warning("⚠️ Geen crop gegenereerd - geen logo-bakens gevonden")

        # ---------------------------------------------------------------------
        # STAP 5 & 6: SIFT + HOMOGRAFIE VALIDATIE
        # ---------------------------------------------------------------------
        best_inlier_ratio = 0.0
        logo_variant_detail = "ONBEKEND"
        num_keypoints_crop = 0
        
        if best_crop is not None and len(ref_logos) > 0:
            sift = cv2.SIFT_create()
            kp_crop, des_crop = sift.detectAndCompute(best_crop, None)
            
            if des_crop is not None:
                num_keypoints_crop = len(kp_crop)
                st.sidebar.write(f"**SIFT keypoints in crop:** {num_keypoints_crop}")
            else:
                st.sidebar.warning("⚠️ Geen SIFT keypoints gevonden in crop!")
            
            if des_crop is not None and len(kp_crop) > 5:  # Verlaagd van 10
                FLANN_INDEX_KDTREE = 1
                index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
                search_params = dict(checks=50)
                flann = cv2.FlannBasedMatcher(index_params, search_params)
                
                for variant_naam, ref_gray in ref_logos.items():
                    kp_ref, des_ref = sift.detectAndCompute(ref_gray, None)
                    
                    if des_ref is not None and len(kp_ref) > 5:
                        matches = flann.knnMatch(des_ref, des_crop, k=2)
                        
                        good_matches = []
                        for m, n in matches:
                            if m.distance < 0.75 * n.distance:
                                good_matches.append(m)
                        
                        st.sidebar.write(f"**{variant_naam}:** {len(good_matches)} goede matches")
                        
                        if len(good_matches) >= 10:  # Verlaagd van 15
                            src_pts = np.float32([kp_ref[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                            dst_pts = np.float32([kp_crop[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                            
                            H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
                            
                            if mask is not None:
                                inliers = np.sum(mask)
                                inlier_ratio = inliers / len(good_matches)
                                
                                if inlier_ratio > best_inlier_ratio and inliers >= 8:  # Verlaagd van 12
                                    best_inlier_ratio = inlier_ratio
                                    logo_variant_detail = variant_naam
                                    st.sidebar.write(f"  ✅ Best match: {inlier_ratio:.2f}")
                
                if best_inlier_ratio >= 0.60:  # Verlaagd van 0.70
                    logo_status = "OFFICIEEL"
                elif best_inlier_ratio >= 0.30:  # Verlaagd van 0.40
                    logo_status = "AANGEPAST"
                else:
                    if len(nl_keyword_matches) >= 2 or len(en_keyword_matches) >= 2:
                        logo_status = "VERVORMD_OF_LAAG_CONTRAST"
            else:
                st.sidebar.warning("⚠️ Onvoldoende keypoints in crop voor SIFT-analyse!")

        # Bepaal de taal op grond van de OCR-bakens
        if len(nl_keyword_matches) >= len(en_keyword_matches) and len(nl_keyword_matches) > 0:
            logo_taal = "NL"
        elif len(en_keyword_matches) > 0:
            logo_taal = "EN"

        # OUTPUT LOGO RAPPORTAGE
        st.markdown("#### 📊 C.A. Logo Validatie Rapport (SIFT)")
        
        if logo_status == "OFFICIEEL":
            st.success(f"✅ **Officieel C.A.-Logo Gevalideerd!** Taal: **{logo_taal}** ({logo_variant_detail}).")
            st.caption(f"📈 *Homografie RANSAC-inliers ratio = {best_inlier_ratio:.2f}*")
            logo_score_final = 25
        elif logo_status == "VERVORMD_OF_LAAG_CONTRAST":
            st.warning(f"⚠️ **Logo-tekst herkend, maar structuurverificatie mislukt.**")
            st.write(f"Gevonden woorden: {', '.join(nl_keyword_matches.union(en_keyword_matches))}")
            st.write(f"SIFT keypoints in crop: {num_keypoints_crop}")
            logo_score_final = 15
        elif logo_status == "AANGEPAST":
            st.error(f"❌ **Logo inhoudelijk bewerkt / Vervormd:** Homografie-matrix signaleert structuurwijzigingen.")
            logo_score_final = 0
        else:
            st.error("❌ **Kritiek Matrix-element mist:** Geen C.A. baken-woorden of logo-structuren aangetroffen.")
            st.write(f"Gevonden NL woorden: {nl_keyword_matches}")
            st.write(f"Gevonden EN woorden: {en_keyword_matches}")
            logo_score_final = 0

        # ---------------------------------------------------------------------
        # RESTERENDE INHOUDELIJKE TEXT MATRIX
        # ---------------------------------------------------------------------
        st.markdown("---")
        st.markdown("### 📝 Inhoudelijke Matrix Analyse")

        if sabotage_gevonden:
            st.error(f"🚨 **CRITIEK INHOUDELIJK CONFLIKT:** {', '.join(sabotage_gevonden)}")
            logo_score_final = 0

        # 6e Traditie gewogen controle
        sterke_keywords = ["6e", "traditie", "kerken", "sekten", "hulpverlenende", "instanties"]
        traditie_score = sum(1 for kw in sterke_keywords if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden))
        traditie_ok = traditie_score >= 3

        if traditie_ok:
            st.success(f"✅ **6e Traditie Disclaimer aanwezig** ({traditie_score}/6)")
        else:
            st.error(f"❌ **6e Traditie Disclaimer incompleet** ({traditie_score}/6)")

        # Groepsnaam / Organisator
        organisator_match = re.search(r'ca[\s\-]+[a-z0-9]+', volledige_tekst, re.IGNORECASE)
        organisator_gevonden = True if organisator_match else False

        # Datum & Tijdstip & Telefoon
        maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
        datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
        datum_gevonden = True if datum_match else False
        tijd_gevonden = len(tijd_regels) >= 1
        locatie_gevonden = ("stadsstrand" in txt_lower) or ("hoorn" in txt_lower)
        
        tel_pattern = r'(\+31\s?6|06)[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}'
        telefoon_gevonden = True if re.search(tel_pattern, volledige_tekst) else False

        # Scores toekennen
        if organisator_gevonden: st.success(f"✅ **Organisator herleid uit tekst**")
        if datum_gevonden: st.success(f"✅ **Datum herleid uit tekst**")
        if tijd_gevonden: st.success(f"✅ **Tijdstip herleid uit tekst**")
        if locatie_gevonden: st.success("✅ **Locatie succesvol herleid**")
        if telefoon_gevonden: st.success(f"📞 **Telefoonnummer aanwezig**")

        # TOTAL SCORE CALCULATOR
        st.markdown("---")
        st.markdown("### 📊 Totale Matrix Score")
        
        score = logo_score_final
        if traditie_ok: score += 25
        if organisator_gevonden: score += 15
        if datum_gevonden: score += 15
        if tijd_gevonden: score += 10
        if locatie_gevonden: score += 5
        if telefoon_gevonden: score += 5
        if sabotage_gevonden: score = 0 

        st.metric(label="Totale Matrix Score", value=f"{score} / 100")
        st.progress(score / 100)
        
        if score >= 90:
            st.success("🎉 **GOEDGEKEURD VOOR VERSPREIDING:** Deze flyer is stabiel en wiskundig goedgekeurd volgens de matrix-richtlijnen.")
        else:
            st.error("❌ **AFGEKEURD:** Dit document voldoet niet aan de gestelde criteria.")

    with col2:
        st.markdown("### 🖼️ Live Visuele Analyse")
        st.caption("Paarse box = Dynamisch berekend OCR-baken-cluster voor SIFT-analyse")
        st.image(img_canvas, channels="RGB", use_container_width=True)
