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
    page_title="C.A. Drukwerk Checker v1.5",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Volledige Productie-Matrix: Multi-Reference Logo-Integriteit & Tekstvalidatie")

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

# STRIKTE CONTROLE EN INLADEN VAN DE 4 TRANSPARANTE REFERENTIELOGO'S
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
        # Laad inclusief alpha-kanaal (IMREAD_UNCHANGED) vanwege transparantie
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            missing_files.append(path)
        else:
            # Als het logo een alpha-kanaal heeft (4 kanalen), maskeer de transparantie naar wit
            if img.shape[2] == 4:
                alpha_channel = img[:, :, 3]
                rgb_channels = img[:, :, :3]
                # Maak een witte achtergrond
                white_bg = np.ones_like(rgb_channels, dtype=np.uint8) * 255
                # Mix het logo met de witte achtergrond op basis van het alpha-kanaal
                alpha_factor = alpha_channel[:, :, np.newaxis] / 255.0
                img = (rgb_channels * alpha_factor + white_bg * (1 - alpha_factor)).astype(np.uint8)
            loaded_logos[key] = img

    if missing_files:
        st.error(f"🚨 **CRITIEKE FOUT:** De volgende referentielogo's ontbreken in de `assets/` map: {', '.join(missing_files)}. De applicatie is stopgezet.")
        st.stop()
        
    return loaded_logos

ref_logos = load_strict_reference_logos()

st.info("⚙️ **Systeemstatus:** Actief. Volledige 5-staps logo-inspectie online (Hough Circles ➔ Multi-Scale ➔ Multi-Reference ➔ ORB ➔ HSV).")

uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # RGBA naar RGB Conversie voor de flyer (indien nodig)
        if len(img_np.shape) == 3 and img_np.shape[2] == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        img_canvas = img_np.copy()
    except Exception as e:
        st.error(f"❌ Fout bij het verwerken van de afbeelding: {e}")
        st.stop()

    # Initialisaties matrix variabelen
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
        # STAP 1: GEOMETRISCHE DETECTIE (Hough Circles)
        # ---------------------------------------------------------------------
        blurred = cv2.medianBlur(img_gray, 5)
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=120,
            param1=50, param2=35, minRadius=40, maxRadius=500
        )
        
        best_crop = None
        detected_x, detected_y, detected_r = 0, 0, 0
        logo_gevonden_geometrisch = False
        
        if circles is not None:
            circles = np.uint16(np.around(circles))
            # Focus op de meest prominente cirkel (meestal het hoofdlogo)
            for i in circles[0, :1]: 
                detected_x, detected_y, detected_r = i[0], i[1], i[2]
                
                # Ruime uitsnede maken met 25% marge om ook de 'TM' of '®' buiten de rand te vangen
                marge = int(detected_r * 0.25)
                h_img, w_img = img_gray.shape
                ymin = max(0, detected_y - detected_r - marge)
                ymax = min(h_img, detected_y + detected_r + marge)
                xmin = max(0, detected_x - detected_r - marge)
                xmax = min(w_img, detected_x + detected_r + marge)
                
                best_crop = img_np[ymin:ymax, xmin:xmax]
                logo_gevonden_geometrisch = True
                
                # Teken een paarse indicatorcirkel op de preview
                cv2.circle(img_canvas, (detected_x, detected_y), detected_r, (255, 0, 255), 3)

        # ---------------------------------------------------------------------
        # STAP 2 & 3: MULTI-SCALE & MULTI-REFERENCE MATCHING
        # ---------------------------------------------------------------------
        logo_status = "MISSING"
        logo_taal = "ONBEKEND"
        logo_variant_detail = ""
        best_match_score = 0.0
        
        if logo_gevonden_geometrisch and best_crop is not None:
            crop_gray = cv2.cvtColor(best_crop, cv2.COLOR_RGB2GRAY)
            
            # Valideer de uitsnede tegen alle 4 de opgeschoonde varianten
            for variant_naam, ref_img in ref_logos.items():
                ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_RGB2GRAY)
                
                # Schaalbereik van 0.4 tot 1.8 om de grootte op de flyer op te vangen
                for scale in np.arange(0.4, 1.8, 0.1):
                    width = int(ref_gray.shape[1] * scale)
                    height = int(ref_gray.shape[0] * scale)
                    
                    if width > crop_gray.shape[1] or height > crop_gray.shape[0]:
                        continue
                        
                    resized_ref = cv2.resize(ref_gray, (width, height), interpolation=cv2.INTER_AREA)
                    res = cv2.matchTemplate(crop_gray, resized_ref, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, _ = cv2.minMaxLoc(res)
                    
                    if max_val > best_match_score:
                        best_match_score = max_val
                        logo_variant_detail = variant_naam
                        logo_taal = "NL" if "NL" in variant_naam else "EN"

            if best_match_score >= 0.68:
                logo_status = "VERMOEDELIJK_OK"
            elif best_match_score >= 0.45:
                logo_status = "AANGEPAST"
            else:
                logo_status = "MISSING"

        # ---------------------------------------------------------------------
        # STAP 4: ORB STRUCTUUR VALIDATIE (INTEGRITEITSCHECK)
        # ---------------------------------------------------------------------
        orb_matches_gevonden = 0
        if logo_status != "MISSING" and best_crop is not None:
            crop_gray = cv2.cvtColor(best_crop, cv2.COLOR_RGB2GRAY)
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
                
                # Als de structurele opbouw te sterk afwijkt, markeren als handmatig bewerkt
                if orb_matches_gevonden < 14 and logo_status == "VERMOEDELIJK_OK":
                    logo_status = "AANGEPAST"

        # ---------------------------------------------------------------------
        # STAP 5: HSV KLEURVALIDATIE
        # ---------------------------------------------------------------------
        kleur_ok = True
        if logo_status == "VERMOEDELIJK_OK" and best_crop is not None:
            crop_hsv = cv2.cvtColor(best_crop, cv2.COLOR_RGB2HSV)
            avg_hue = np.mean(crop_hsv[:, :, 0])
            avg_sat = np.mean(crop_hsv[:, :, 1])
            
            # C.A. Huisstijl controle: Kleuring buiten blauw (100-140) of grijs/zwart (Sat < 35) afkeuren
            if avg_sat > 35:
                if not (100 <= avg_hue <= 140):
                    kleur_ok = False
                    logo_status = "KLEUR_GEWIJZIGD"

        # OUTPUT LOGO RAPPORTAGE
        st.markdown("#### 📊 C.A. Logo Validatie Rapport")
        if logo_status == "VERMOEDELIJK_OK":
            v_type = "met TM/® binnen de cirkel" if "BINNEN" in logo_variant_detail else "met TM/® buiten de cirkel"
            st.success(f"✅ **Officieel C.A.-Logo Gevalideerd!** Type: **{logo_taal} ({v_type})**. Vorm, structuur en merkteken-plaatsing zijn 100% legitiem.")
            logo_score_final = 25
        elif logo_status == "KLEUR_GEWIJZIGD":
            st.warning(f"⚠️ **Huisstijl-fout: Gekleurd logo!** De vorm en variant klopt, maar de kleurwijziging is in strijd met de officiële richtlijnen.")
            logo_score_final = 10
        elif logo_status == "AANGEPAST":
            st.error(f"❌ **Logo bewerkt of vervormd:** De letters of cirkelranden wijken af van de officiële varianten. (ORB-matches: {orb_matches_gevonden})")
            logo_score_final = 0
        else:
            st.error("❌ **Kritiek Matrix-element mist:** Geen officieel, herkenbaar C.A.-logo aangetroffen.")
            logo_score_final = 0

        # ---------------------------------------------------------------------
        # INHOUDELIJKE TEXT MATRIX & SABOTAGE-DETECTIE (OCR)
        # ---------------------------------------------------------------------
        st.markdown("---")
        st.markdown("### 📝 Inhoudelijke Matrix Analyse")
        
        with st.spinner("Scannen van flyertekst via Multi-Pass OCR..."):
            img_enhanced = cv2.adaptiveThreshold(img_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            img_clahe = clahe.apply(img_gray)
            
            ocr_results = reader.readtext(img_np, detail=1) + reader.readtext(img_enhanced, detail=1) + reader.readtext(img_clahe, detail=1)
            
            # Sabotage/Fellowship-conflit trefwoorden (AA / NA / Al-Anon)
            sabotage_keywords = ["unity", "service", "recovery", "just for today", "powerlessness", "serenity"]
            sabotage_gevonden = set()

            for (bbox, text, prob) in ocr_results:
                if prob < 0.30:
                    continue
                
                # Slimme OCR-correctie voor cijfer/letter-fouten
                txt_clean = text.replace("I", "1").replace("l", "1").replace("O", "0")
                key = txt_clean.lower().strip()
                
                if key in gevonden_keys:
                    continue
                gevonden_keys.add(key)
                unieke_teksten.append(txt_clean)
                
                woorden_in_regel = txt_clean.lower().split()
                alle_losse_woorden.extend(woorden_in_regel)
                
                # Directe controle op foutief fellowship-gebruik
                for skw in sabotage_keywords:
                    if skw in key or any(word_similarity(skw, w) >= 0.85 for w in woorden_in_regel):
                        sabotage_gevonden.add(skw)

                # Kaders tekenen op canvas (Groen = Tekst, Blauw = Tijdstip)
                tl = tuple(map(int, bbox[0]))
                br = tuple(map(int, bbox[2]))
                cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                if re.search(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean):
                    tijd_regels.append(txt_clean.lower())
                    cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

            volledige_tekst = " ".join(unieke_teksten)
            txt_lower = volledige_tekst.lower()

            if sabotage_gevonden:
                st.error(f"🚨 **CRITIEK INHOUDELIJK CONFLIKT:** Deze flyer gebruikt termen van andere fellowships (*{', '.join(sabotage_gevonden)}*). Dit drukwerk mag niet namens C.A. verspreid worden.")
                logo_score_final = 0

            # 6e Traditie gewogen controle
            sterke_keywords = ["6e", "traditie", "kerken", "sekten", "hulpverlenende", "instanties"]
            traditie_score = sum(1 for kw in sterke_keywords if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden))
            traditie_ok = traditie_score >= 3

            if traditie_ok:
                st.success(f"✅ **6e Traditie Disclaimer aanwezig** ({traditie_score}/5 sterke woorden)")
            else:
                st.error(f"❌ **6e Traditie Disclaimer incompleet** ({traditie_score}/5 sterke woorden)")

            # Organisator (Groepsnaam)
            organisator_match = re.search(r'ca[\s\-]+[a-z0-9]+', volledige_tekst, re.IGNORECASE)
            if organisator_match:
                organisator_gevonden = True
                organisator_naam = organisator_match.group(0).upper()
                st.success(f"✅ **Organisator:** {organisator_naam}")
            
            # Datum
            maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
            datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
            if datum_match:
                datum_gevonden = True
                datum_waarde = datum_match.group(0)
                st.success(f"✅ **Datum:** {datum_waarde}")
            
            # Tijdstip
            if len(tijd_regels) >= 1:
                tijd_gevonden = True
                st.success(f"✅ **Tijdstip:** {tijd_regels[0]}")

            # Slimme Locatie Score
            locatie_score = (2 if "stadsstrand" in txt_lower else 0) + (1 if "hoorn" in txt_lower else 0)
            if locatie_score >= 2:
                locatie_gevonden = True
                st.success("✅ **Locatie succesvol herleid**")

            # Telefoonnummer (met flexibele spaties/streepjes)
            tel_pattern = r'(\+31\s?6|06)[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}'
            telefoon_match = re.search(tel_pattern, volledige_tekst)
            if telefoon_match:
                telefoon_gevonden = True
                telefoon_waarde = telefoon_match.group(0)
                st.success(f"📞 **Telefoonnummer:** {telefoon_waarde}")

        # =====================================================================
        # 📊 MATRIX SCORE RAPPORTAGE
        # =====================================================================
        st.markdown("---")
        st.markdown("### 📊 Totale Matrix Score")
        
        score = logo_score_final
        if traditie_ok: score += 25
        if organisator_gevonden: score += 15
        if datum_gevonden: score += 15
        if tijd_gevonden: score += 10
        if locatie_gevonden: score += 5
        if telefoon_gevonden: score += 5
        
        if sabotage_gevonden:
            score = 0 

        st.metric(label="Totale Matrix Score", value=f"{score} / 100")
        st.progress(score / 100)
        
        if score == 100 and logo_status == "VERMOEDELIJK_OK":
            st.success("🎉 **UITMUNTEND EN GOEDGEKEURD:** De flyer voldoet volledig aan de visuele merkrechten én de inhoudelijke matrix.")
        elif logo_status == "KLEUR_GEWIJZIGD":
            st.warning("⚠️ **AFGEKEURD (Huisstijl-fout):** De data klopt, maar het C.A.-logo is ingekleurd. Dit moet hersteld worden naar zwart, wit of diepblauw.")
        else:
            st.error("❌ **AFGEKEURD:** Deze flyer bevat kritieke fouten, mist verplichte matrix-elementen of schendt de fellowship-rechten.")

    with col2:
        st.markdown("### 🖼️ Live Visuele Analyse")
        st.caption("Paarse cirkel = Gedetecteerd logo-kandidaat via Hough Circles.")
        st.image(img_canvas, channels="RGB", use_container_width=True)
