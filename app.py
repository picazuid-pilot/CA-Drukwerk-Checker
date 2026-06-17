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
    page_title="C.A. Drukwerk Checker v1.4",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Productie-Ready Hybride Controle: Geometrie + Multi-Scale + Kleurvalidatie")

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

# CRUCIAAL (Punt 4): Harde stop als referentielogo's ontbreken
def load_strict_reference_logos():
    logo_nl = cv2.imread("assets/logo_nl.png") # In kleur laden voor kleurvalidatie!
    logo_en = cv2.imread("assets/logo_en.png")
    
    if logo_nl is None or logo_en is None:
        st.error("🚨 **CRITIEKE FOUT:** De officiële referentielogo's (`logo_nl.png` en `logo_en.png`) ontbreken in de `assets/` map. De applicatie is stopgezet.")
        st.stop()
    return logo_nl, logo_en

ref_logo_nl, ref_logo_en = load_strict_reference_logos()

st.info("⚙️ **Systeemstatus:** Actief. Validatieflow: Hough Circles ➔ Multi-Scale Match ➔ ORB Structuur ➔ HSV Kleuranalyse.")

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

    # Initialisaties voor algemene matrix
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
        st.markdown("### 🖼️ Geavanceerde C.A. Logo Inspectie")
        
        # ---------------------------------------------------------------------
        # STAP 1 & 2: GEOMETRISCHE DETECTIE (Hough Circles)
        # ---------------------------------------------------------------------
        # We blurren de afbeelding om ruis te verminderen voor betere cirkeldetectie
        blurred = cv2.medianBlur(img_gray, 5)
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=100,
            param1=50, param2=30, minRadius=40, maxRadius=400
        )
        
        best_crop = None
        detected_x, detected_y, detected_r = 0, 0, 0
        logo_gevonden_geometrisch = False
        
        if circles is not None:
            circles = np.uint16(np.around(circles))
            # Pak de grootste/meest centrale cirkel als kandidaat
            for i in circles[0, :1]: 
                detected_x, detected_y, detected_r = i[0], i[1], i[2]
                
                # Snijd het logogebied ruim uit met een marge van 25%
                marge = int(detected_r * 0.25)
                h_img, w_img = img_gray.shape
                ymin = max(0, detected_y - detected_r - marge)
                ymax = min(h_img, detected_y + detected_r + marge)
                xmin = max(0, detected_x - detected_r - marge)
                xmax = min(w_img, detected_x + detected_r + marge)
                
                best_crop = img_np[ymin:ymax, xmin:xmax]
                logo_gevonden_geometrisch = True
                
                # Teken een paarse cirkel op het canvas ter indicatie
                cv2.circle(img_canvas, (detected_x, detected_y), detected_r, (255, 0, 255), 3)

        # ---------------------------------------------------------------------
        # STAP 3: MULTI-SCALE TEMPLATE MATCHING & TAALBEPALING
        # ---------------------------------------------------------------------
        logo_status = "MISSING"
        logo_taal = "NL"
        best_match_score = 0.0
        
        if logo_gevonden_geometrisch and best_crop is not None:
            crop_gray = cv2.cvtColor(best_crop, cv2.COLOR_RGB2GRAY)
            
            for taal, ref_img in [("NL", ref_logo_nl), ("EN", ref_logo_en)]:
                ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
                
                # Test verschillende schalen van het referentielogo (Punt 3 van je voorstel)
                for scale in np.arange(0.4, 1.8, 0.1):
                    width = int(ref_gray.shape[1] * scale)
                    height = int(ref_gray.shape[0] * scale)
                    
                    # Voorkom dat het template groter is dan de crop zelf
                    if width > crop_gray.shape[1] or height > crop_gray.shape[0]:
                        continue
                        
                    resized_ref = cv2.resize(ref_gray, (width, height), interpolation=cv2.INTER_AREA)
                    res = cv2.matchTemplate(crop_gray, resized_ref, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, _ = cv2.minMaxLoc(res)
                    
                    if max_val > best_match_score:
                        best_match_score = max_val
                        logo_taal = taal

            # Grenzen bepalen op basis van Multi-Scale match score
            if best_match_score >= 0.70:
                logo_status = "VERMOEDELIJK_OK"
            elif best_match_score >= 0.45:
                logo_status = "AANGEPAST"
            else:
                logo_status = "MISSING"

        # ---------------------------------------------------------------------
        # STAP 4: ORB STRUCTUUR VALIDATIE
        # ---------------------------------------------------------------------
        orb_matches_gevonden = 0
        if logo_status != "MISSING" and best_crop is not None:
            crop_gray = cv2.cvtColor(best_crop, cv2.COLOR_RGB2GRAY)
            target_ref = ref_logo_nl if logo_taal == "NL" else ref_logo_en
            target_ref_gray = cv2.cvtColor(target_ref, cv2.COLOR_BGR2GRAY)
            
            orb = cv2.ORB_create(nfeatures=700)
            kp1, des1 = orb.detectAndCompute(target_ref_gray, None)
            kp2, des2 = orb.detectAndCompute(crop_gray, None)
            
            if des1 is not None and des2 is not None:
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                matches = bf.match(des1, des2)
                good_matches = [m for m in matches if m.distance < 40]
                orb_matches_gevonden = len(good_matches)
                
                # Strenge ORB-grenscontrole (Punt 4 van je voorstel)
                if orb_matches_gevonden < 15 and logo_status == "VERMOEDELIJK_OK":
                    logo_status = "AANGEPAST" # Structuur/tekst klopt niet

        # ---------------------------------------------------------------------
        # STAP 5: HSV KLEURVALIDATIE (Punt 5 van je voorstel - Essentieel!)
        # ---------------------------------------------------------------------
        kleur_ok = True
        if logo_status == "VERMOEDELIJK_OK" and best_crop is not None:
            # Converteer de crop naar HSV (kleurruimte)
            crop_hsv = cv2.cvtColor(best_crop, cv2.COLOR_RGB2HSV)
            
            # Bereken de gemiddelde saturatie (kleurintensiteit) en hue (kleurtoon)
            avg_hue = np.mean(crop_hsv[:, :, 0])
            avg_sat = np.mean(crop_hsv[:, :, 1])
            
            # Als de saturatie heel hoog is buiten het normale zwart/blauw bereik,
            # of als er een duidelijke afwijking is naar groen/rood tinten:
            # C.A. logo's zijn primair diepblauw (H: 100-130) of neutraal zwart/grijs (Sat < 30)
            if avg_sat > 40: # Er is sprake van actieve kleuring
                if not (100 <= avg_hue <= 140): # Valt buiten het officiële C.A. blauw-bereik
                    kleur_ok = False
                    logo_status = "KLEUR_GEWIJZIGD"

        # ---------------------------------------------------------------------
        # PRINT LOGO RAPPORTAGE
        # ---------------------------------------------------------------------
        if logo_status == "VERMOEDELIJK_OK":
            st.success(f"✅ **Officieel C.A.-Logo Gevalideerd!** ({logo_taal}-talig). Vorm, structuur en kleurkleuring zijn conform de richtlijnen.")
            logo_score_final = 25
        elif logo_status == "KLEUR_GEWIJZIGD":
            st.warning(f"⚠️ **Huisstijl-fout: Logo ingekleurd!** De vorm en tekst zijn correct, maar de kleurwijziging (HSV-detectie) is in strijd met de richtlijnen.")
            logo_score_final = 10
        elif logo_status == "AANGEPAST":
            st.error(f"❌ **Logo ontoelaatbaar bewerkt:** De cirkeltekst of vorm is vervormd, uitgerekt of aangepast. (ORB-matches: {orb_matches_gevonden})")
            logo_score_final = 0
        else:
            st.error("❌ **Kritiek Matrix-element mist:** Geen officieel C.A.-logo aangetroffen op de flyer.")
            logo_score_final = 0

        # ---------------------------------------------------------------------
        # ALGEMENE OCR MATRIX EN SABOTAGE CONTROLE (Punt 6 van je voorstel)
        # ---------------------------------------------------------------------
        st.markdown("---")
        st.markdown("### 📝 Inhoudelijke Matrix Analyse")
        
        with st.spinner("Scannen van flyertekst en sabotage-check..."):
            # Multi-Pass OCR
            img_enhanced = cv2.adaptiveThreshold(img_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            img_clahe = clahe.apply(img_gray)
            
            ocr_results = reader.readtext(img_np, detail=1) + reader.readtext(img_enhanced, detail=1) + reader.readtext(img_clahe, detail=1)
            
            # Andere fellowship indicatoren (Sabotage preventie)
            sabotage_keywords = ["unity", "service", "recovery", "just for today", "powerlessness", "serenity"]
            sabotage_gevonden = set()

            for (bbox, text, prob) in ocr_results:
                if prob < 0.30:
                    continue
                
                txt_clean = text.replace("I", "1").replace("l", "1").replace("O", "0")
                key = txt_clean.lower().strip()
                
                if key in gevonden_keys:
                    continue
                gevonden_keys.add(key)
                unieke_teksten.append(txt_clean)
                
                woorden_in_regel = txt_clean.lower().split()
                alle_losse_woorden.extend(woorden_in_regel)
                
                # Controleer direct op misplaatst fellowship gebruik
                for skw in sabotage_keywords:
                    if skw in key or any(word_similarity(skw, w) >= 0.85 for w in woorden_in_regel):
                        sabotage_gevonden.add(skw)

                # Kaders tekenen voor tekst en tijd
                tl = tuple(map(int, bbox[0]))
                br = tuple(map(int, bbox[2]))
                cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                if re.search(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean):
                    tijd_regels.append(txt_clean.lower())
                    cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

            volledige_tekst = " ".join(unieke_teksten)
            txt_lower = volledige_tekst.lower()

            # Sabotage-blokkade activeren
            if sabotage_gevonden:
                st.error(f"🚨 **CRITIEK INHOUDELIJK CONFLIKT:** Deze flyer bevat herstel-termen die exclusief toebehoren aan andere fellowships (gedetecteerd: *{', '.join(sabotage_gevonden)}*). Dit drukwerk wordt direct afgekeurd.")
                logo_score_final = 0

            # 6e Traditie gewogen keywords
            sterke_keywords = ["6e", "traditie", "kerken", "sekten", "hulpverlenende", "instanties"]
            traditie_score = sum(1 for kw in sterke_keywords if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden))
            traditie_ok = traditie_score >= 3

            if traditie_ok:
                st.success(f"✅ **6e Traditie Disclaimer aanwezig** ({traditie_score}/5 sterke woorden)")
            else:
                st.error(f"❌ **6e Traditie Disclaimer incompleet** ({traditie_score}/5 sterke woorden)")

            # Organisator, Datum, Tijd, Locatie, Telefoon
            organisator_match = re.search(r'ca[\s\-]+[a-z0-9]+', volledige_tekst, re.IGNORECASE)
            if organisator_match:
                organisator_gevonden = True
                organisator_naam = organisator_match.group(0).upper()
                st.success(f"✅ **Organisator:** {organisator_naam}")
            
            maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
            datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
            if datum_match:
                datum_gevonden = True
                datum_waarde = datum_match.group(0)
                st.success(f"✅ **Datum:** {datum_waarde}")
            
            if len(tijd_regels) >= 1:
                tijd_gevonden = True
                st.success(f"✅ **Tijdstip:** {tijd_regels[0]}")

            locatie_score = (2 if "stadsstrand" in txt_lower else 0) + (1 if "hoorn" in txt_lower else 0)
            if locatie_score >= 2:
                locatie_gevonden = True
                st.success("✅ **Locatie succesvol herleid**")

            tel_pattern = r'(\+31\s?6|06)[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}'
            telefoon_match = re.search(tel_pattern, volledige_tekst)
            if telefoon_match:
                telefoon_gevonden = True
                telefoon_waarde = telefoon_match.group(0)
                st.success(f"📞 **Telefoonnummer:** {telefoon_waarde}")

        # =====================================================================
        # 📊 WEGING & EINDBEOORDELING
        # =====================================================================
        st.markdown("---")
        st.markdown("### 📊 Matrix Score Rapport")
        
        score = logo_score_final
        if traditie_ok: score += 25
        if organisator_gevonden: score += 15
        if datum_gevonden: score += 15
        if tijd_gevonden: score += 10
        if locatie_gevonden: score += 5
        if telefoon_gevonden: score += 5
        
        if sabotage_gevonden:
            score = 0 # Harde override bij misbruik merkrechten

        st.metric(label="Totale Matrix Score", value=f"{score} / 100")
        st.progress(score / 100)
        
        if score == 100 and logo_status == "VERMOEDELIJK_OK":
            st.success("🎉 **GOEDGEKEURD:** De flyer voldoet aan alle strenge visuele en inhoudelijke regelgeving.")
        elif logo_status == "KLEUR_GEWIJZIGD":
            st.warning("⚠️ **AFGEKEURD (Huisstijl-fout):** De flyer bevat alle data, maar het C.A.-logo is ingekleurd. Herstel dit naar de officiële kleur.")
        else:
            st.error("❌ **AFGEKEURD:** Deze flyer voldoet niet aan de matrix-eisen of bevat herstel-termen van derden.")

    with col2:
        st.markdown("### 🖼️ Live Visuele Analyse")
        st.caption("Paarse cirkel = Geometrisch gedetecteerd logo-kandidaat via Hough Circles.")
        st.image(img_canvas, channels="RGB", use_container_width=True)
