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
st.subheader("Architectuur v3.0: OCR-Clustering & Logo-Validatie")

def word_similarity(w1, w2):
    """Bereken gelijkenis tussen twee woorden"""
    return SequenceMatcher(None, w1.lower().strip(), w2.lower().strip()).ratio()

@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl', 'en'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# ---- GEEN SIFT MEER ----
# We gebruiken alleen OCR voor logo-detectie

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
        # MULTI-PASS OCR
        # ---------------------------------------------------------------------
        with st.spinner("Scannen van flyertekst en lokaliseren van logo-cluster..."):
            # Meerdere OCR-passes voor betere detectie
            img_enhanced = cv2.adaptiveThreshold(img_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            img_contrast = cv2.equalizeHist(img_gray)
            
            try:
                ocr_results = (
                    reader.readtext(img_np, detail=1) + 
                    reader.readtext(img_enhanced, detail=1) +
                    reader.readtext(img_contrast, detail=1)
                )
            except Exception as e:
                st.error(f"❌ OCR-fout: {e}")
                ocr_results = []
            
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
            
            # DEBUG: toon gevonden woorden in sidebar
            st.sidebar.write("### 📝 OCR Debug")
            st.sidebar.write("**Gevonden tekstfragmenten:**")
            ocr_count = 0

            for (bbox, text, prob) in ocr_results:
                if prob < 0.20:
                    continue
                
                txt_clean = text.replace("I", "1").replace("l", "1").replace("O", "0")
                key = txt_clean.lower().strip()
                
                if key in gevonden_keys:
                    continue
                gevonden_keys.add(key)
                unieke_teksten.append(txt_clean)
                
                # Toon eerste 30 gevonden teksten in sidebar
                if ocr_count < 30:
                    st.sidebar.write(f"• `{txt_clean}`")
                    ocr_count += 1
                
                woorden_in_regel = key.split()
                alle_losse_woorden.extend(woorden_in_regel)
                
                # Check voor logo-baken woorden (NL & EN)
                for kw in logo_keywords_nl:
                    if kw in key or any(word_similarity(kw, w) >= 0.65 for w in woorden_in_regel):
                        logo_bboxes.append(bbox)
                        nl_keyword_matches.add(kw)
                        st.sidebar.write(f"  ✅ NL match: '{kw}' in '{txt_clean}'")
                for kw in logo_keywords_en:
                    if kw in key or any(word_similarity(kw, w) >= 0.65 for w in woorden_in_regel):
                        logo_bboxes.append(bbox)
                        en_keyword_matches.add(kw)
                        st.sidebar.write(f"  ✅ EN match: '{kw}' in '{txt_clean}'")
                        
                # Check voor cross-fellowship sabotage
                for skw in sabotage_keywords:
                    if skw in key or any(word_similarity(skw, w) >= 0.85 for w in woorden_in_regel):
                        sabotage_gevonden.add(skw)
                        st.sidebar.write(f"  ⚠️ Sabotage: '{skw}' in '{txt_clean}'")

                # Reguliere matrix-visualisatie
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
        # LOGO CLUSTERING & VALIDATIE ZONDER SIFT
        # ---------------------------------------------------------------------
        best_crop = None
        logo_status = "MISSING"
        logo_taal = "ONBEKEND"
        
        # Bepaal taal op basis van matches
        if len(nl_keyword_matches) >= len(en_keyword_matches) and len(nl_keyword_matches) > 0:
            logo_taal = "NL"
        elif len(en_keyword_matches) > 0:
            logo_taal = "EN"
        
        # Logo status op basis van tekstherkenning
        if len(nl_keyword_matches) >= 2:
            logo_status = "TEKST_HERKEND"
            logo_score_final = 20
        elif len(nl_keyword_matches) >= 1:
            logo_status = "TEKST_GEDEELTELIJK"
            logo_score_final = 10
        elif len(en_keyword_matches) >= 2:
            logo_status = "TEKST_HERKEND_EN"
            logo_score_final = 20
        elif len(en_keyword_matches) >= 1:
            logo_status = "TEKST_GEDEELTELIJK_EN"
            logo_score_final = 10
        else:
            logo_status = "MISSING"
            logo_score_final = 0
        
        # Als er logo_bboxes zijn, teken de cluster
        if len(logo_bboxes) >= 1:
            all_pts = []
            for box in logo_bboxes:
                for pt in box:
                    all_pts.append([int(pt[0]), int(pt[1])])
            
            # Bereken de strakke bounding box
            x, y, w, h = cv2.boundingRect(np.array(all_pts))
            
            # Uitbreiden met 200%
            marge_x = int(w * 1.0) 
            marge_y = int(h * 1.0)
            
            h_img, w_img = img_gray.shape
            ymin = max(0, y - marge_y)
            ymax = min(h_img, y + h + marge_y)
            xmin = max(0, x - marge_x)
            xmax = min(w_img, x + w + marge_x)
            
            best_crop = img_gray[ymin:ymax, xmin:xmax]
            
            # Teken de paarse cluster-box
            cv2.rectangle(img_canvas, (xmin, ymin), (xmax, ymax), (255, 0, 255), 3)

        # Toon de crop in de UI
        if best_crop is not None:
            st.image(best_crop, caption="Dynamische crop van logo-cluster", use_container_width=True)

        # OUTPUT LOGO RAPPORTAGE
        st.markdown("#### 📊 C.A. Logo Validatie Rapport (OCR)")
        
        if logo_status == "TEKST_HERKEND" or logo_status == "TEKST_HERKEND_EN":
            st.success(f"✅ **C.A.-Logo herkend!** Taal: **{logo_taal}**")
            st.caption(f"Gevonden woorden: {', '.join(nl_keyword_matches.union(en_keyword_matches))}")
        elif logo_status == "TEKST_GEDEELTELIJK" or logo_status == "TEKST_GEDEELTELIJK_EN":
            st.warning(f"⚠️ **Logo gedeeltelijk herkend** - Taal: **{logo_taal}**")
            st.write(f"Gevonden: {', '.join(nl_keyword_matches.union(en_keyword_matches))}")
            st.write("Er zijn niet alle logo-teksten ('hoop', 'vertrouwen', 'moed') gevonden. Dit kan komen door:")
            st.write("- Laag contrast van de tekst")
            st.write("- OCR die cirkeltekst niet goed leest")
            st.write("- Kleine lettergrootte")
        else:
            st.error("❌ **Kritiek Matrix-element mist:** Geen C.A. baken-woorden aangetroffen.")
            st.write("De logo-teksten 'hoop', 'vertrouwen', 'moed' zijn niet herkend in de OCR.")
            st.write("Tips voor een betere scan:")
            st.write("- Gebruik een hogere resolutie afbeelding")
            st.write("- Zorg voor voldoende contrast")
            st.write("- Vermijd tekst over afbeeldingen")

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
            st.success(f"✅ **6e Traditie Disclaimer aanwezig** ({traditie_score}/6 sterke woorden)")
        else:
            st.error(f"❌ **6e Traditie Disclaimer incompleet** ({traditie_score}/6 sterke woorden)")
            st.write(f"Gevonden woorden uit de disclaimer: {', '.join([kw for kw in sterke_keywords if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden)])}")

        # Groepsnaam / Organisator
        organisator_match = re.search(r'ca[\s\-]+[a-z0-9]+', volledige_tekst, re.IGNORECASE)
        organisator_gevonden = True if organisator_match else False

        # Datum & Tijdstip & Telefoon
        maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
        datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
        datum_gevonden = True if datum_match else False
        tijd_gevonden = len(tijd_regels) >= 1
        locatie_gevonden = ("stadsstrand" in txt_lower) or ("hoorn" in txt_lower) or ("strand" in txt_lower)
        
        tel_pattern = r'(\+31\s?6|06)[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}'
        telefoon_gevonden = True if re.search(tel_pattern, volledige_tekst) else False

        # Scores toekennen
        if organisator_gevonden: st.success(f"✅ **Organisator herleid uit tekst**")
        else: st.warning("⚠️ **Geen organisator gevonden** (bijv. 'CA Hoorn')")
        
        if datum_gevonden: st.success(f"✅ **Datum herleid uit tekst**")
        else: st.warning("⚠️ **Geen datum gevonden**")
        
        if tijd_gevonden: st.success(f"✅ **Tijdstip herleid uit tekst**")
        else: st.warning("⚠️ **Geen tijd gevonden**")
        
        if locatie_gevonden: st.success("✅ **Locatie succesvol herleid**")
        else: st.warning("⚠️ **Geen locatie gevonden**")
        
        if telefoon_gevonden: st.success(f"📞 **Telefoonnummer aanwezig**")
        else: st.info("ℹ️ **Geen telefoonnummer gevonden**")

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
        st.caption("🟢 Groen = Tekstvlakken | 🔵 Blauw = Tijd | 🟣 Paars = Logo-cluster")
        st.image(img_canvas, channels="RGB", use_container_width=True)
        
        # Toon gevonden tekst in expander
        if volledige_tekst:
            with st.expander("📝 Volledige OCR-tekst"):
                st.write(volledige_tekst)
        
        # Toon alle gevonden woorden
        if alle_losse_woorden:
            with st.expander("🔍 Alle gevonden woorden"):
                st.write(", ".join(set(alle_losse_woorden[:100])))
else:
    # Instructies
    st.info("👆 Upload een flyer om te beginnen met de analyse.")
