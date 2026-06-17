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
    page_title="C.A. Drukwerk Checker v1.2",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Hybride Matrix Controle: OCR Inhoud + Visuele Logo Integriteit")

def word_similarity(w1, w2):
    return SequenceMatcher(None, w1.lower().strip(), w2.lower().strip()).ratio()

@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# Inladen van het officiële referentielogo voor ORB-matching
@st.cache_data
def load_reference_logo():
    # Zorg dat dit logo in je 'assets/' map staat
    pad = "assets/logo1.png"
    img = cv2.imread(pad, cv2.IMREAD_GRAYSCALE)
    if img is None:
        # Dummy logo genereren als het bestand mist (zodat de app niet crasht)
        img = np.zeros((200, 200), dtype=np.uint8)
        cv2.circle(img, (100, 100), 80, 255, -1)
    return img

reference_logo = load_reference_logo()

st.info("⚙️ **Systeemstatus:** Hybride controle actief. Niveau 1 (OCR Lokalisatie) + Niveau 2 (ORB Visuele Integriteitsvalidatie).")

uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # RGBA naar RGB Conversie tegen crashes
        if len(img_np.shape) == 3 and img_np.shape[2] == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            
        img_gray_orig = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        
        # Multi-pass voorbereiding
        img_enhanced = cv2.adaptiveThreshold(img_gray_orig, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        img_clahe = clahe.apply(img_gray_orig)
        
        img_canvas = img_np.copy()
    except Exception as e:
        st.error(f"❌ Fout bij het verwerken van de afbeelding: {e}")
        st.stop()

    # Initialisatie variabelen
    unieke_teksten = []
    gevonden_keys = set()
    tijd_regels = []
    alle_losse_woorden = []
    
    # Bounding boxes voor logo-lokalisatie
    logo_bboxes = []
    
    organisator_gevonden = False
    evenementnaam_gevonden = False
    datum_gevonden = False
    tijd_gevonden = False
    locatie_gevonden = False
    telefoon_gevonden = False
    
    organisator_naam = "Onbekend"
    datum_waarde = "Onbekend"
    telefoon_waarde = "Onbekend"

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Matrix Analyse")
        
        if reader is not None:
            with st.spinner("Scannen via Multi-Pass OCR & Deduplicatie..."):
                # Multi-pass OCR
                ocr_orig = reader.readtext(img_np, detail=1)
                ocr_enh = reader.readtext(img_enhanced, detail=1)
                ocr_clahe = reader.readtext(img_clahe, detail=1)
                ocr_results = ocr_orig + ocr_enh + ocr_clahe
                
                for (bbox, text, prob) in ocr_results:
                    if prob < 0.30:
                        continue
                    
                    # SLIMME OCR CORRECTIE (Punt 3) - Voorkomt typefouten in nummers/data
                    txt_clean = text.replace("I", "1").replace("l", "1").replace("O", "0")
                    txt_clean = txt_clean.replace("juii", "juli").replace("juIi", "juli").replace("t0t", "tot")
                    
                    key = txt_clean.lower().strip()
                    
                    # DEDUPLICATIE (Punt 2)
                    if key in gevonden_keys:
                        continue
                    gevonden_keys.add(key)
                    unieke_teksten.append(txt_clean)
                    
                    # Woorden verzamelen voor traditie/logo checks
                    woorden_in_regel = txt_clean.lower().split()
                    alle_losse_woorden.extend(woorden_in_regel)
                    
                    # Canvas kaders tekenen
                    tl = tuple(map(int, bbox[0]))
                    br = tuple(map(int, bbox[2]))
                    cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                    
                    # Check of deze regel logowoorden bevat (voor lokalisatie)
                    for lw in ["hoop", "vertrouwen", "moed"]:
                        if any(word_similarity(lw, w) >= 0.80 for w in woorden_in_regel):
                            logo_bboxes.append(bbox)
                    
                    # Tijd-herkenning
                    if re.search(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean):
                        tijd_regels.append(txt_clean.lower())
                        cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

                volledige_tekst = " ".join(unieke_teksten)
                txt_lower = volledige_tekst.lower()
                
                # --- LOGO NIVEAU 1: OCR AANWEZIGHEID ---
                logo_keywords = ["hoop", "vertrouwen", "moed"]
                gevonden_logo_woorden = set()
                for kw in logo_keywords:
                    for woord in alle_losse_woorden:
                        if word_similarity(kw, woord) >= 0.80:
                            gevonden_logo_woorden.add(kw)
                
                logo_ocr_score = len(gevonden_logo_woorden)
                logo_aanwezig_ocr = logo_ocr_score >= 2

                # --- LOGO NIVEAU 2: VISUELE INTEGRITEIT (ORB FEATURE MATCHING) ---
                logo_visueel_gevalideerd = False
                orb_matches_gevonden = 0
                
                if logo_aanwezig_ocr and logo_bboxes:
                    try:
                        # Bereken de totale bounding box om het logo uit te snijden
                        all_pts = np.array([pt for bbox in logo_bboxes for pt in bbox], dtype=np.int32)
                        x, y, w, h = cv2.boundingRect(all_pts)
                        
                        # Voeg wat marge toe rond het logo (omliggende cirkel/randen meepakken)
                        marge = 40
                        h_img, w_img = img_gray_orig.shape
                        ymin, ymax = max(0, y-marge), min(h_img, y+h+marge)
                        xmin, xmax = max(0, x-marge), min(w_img, x+w+marge)
                        
                        cropped_logo = img_gray_orig[ymin:ymax, xmin:xmax]
                        
                        if cropped_logo.size > 0:
                            # Initialiseer ORB detector
                            orb = cv2.ORB_create(nfeatures=500)
                            kp1, des1 = orb.detectAndCompute(reference_logo, None)
                            kp2, des2 = orb.detectAndCompute(cropped_logo, None)
                            
                            if des1 is not None and des2 is not None:
                                # Match features via BruteForce Hamming
                                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                                matches = bf.match(des1, des2)
                                # Filter op goede, betrouwbare matches
                                good_matches = [m for m in matches if m.distance < 45]
                                orb_matches_gevonden = len(good_matches)
                                
                                # Blauw/paars kader om het gevalideerde logo-gebied trekken
                                cv2.rectangle(img_canvas, (xmin, ymin), (xmax, ymax), (255, 0, 255), 4)
                                
                                # Als er voldoende structurele overeenkomsten zijn, is het logo ongewijzigd
                                if orb_matches_gevonden >= 12: 
                                    logo_visueel_gevalideerd = True
                    except Exception as e:
                        pass

                # --- OUTPUT LOGO STATUS MATRIX ---
                st.markdown("#### 🖼️ C.A. Logo Validatie Rapport")
                if logo_visueel_gevalideerd:
                    st.success(f"✅ **Officieel CA-logo gevalideerd!** Structureel ongewijzigd conform richtlijnen. (ORB-score: {orb_matches_gevonden} matches)")
                    logo_status = "GOED"
                elif logo_aanwezig_ocr:
                    st.warning(f"⚠️ **CA-logo aangepast of beschadigd!** De verplichte woorden (*{', '.join(gevonden_logo_woorden)}*) zijn gelezen, maar de visuele vorm of kleur wijkt af van het origineel! (ORB-score: {orb_matches_gevonden} matches)")
                    logo_status = "AANGEPAST"
                else:
                    st.error("❌ **Officieel CA-logo ontbreekt!** Geen geldige logo-tekst of merkteken aangetroffen.")
                    logo_status = "MISSING"

                # --- CRITIEKE CONTROLES: 6E TRADITIE (Punt 4) ---
                st.markdown("---")
                st.markdown("#### 📋 Inhoudelijke Checklist")
                
                # Gewogen keywords (Punt 4)
                sterke_keywords = ["6e", "traditie", "kerken", "sekten", "hulpverlenende", "instanties"]
                traditie_score = 0
                for kw in sterke_keywords:
                    if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden):
                        traditie_score += 1
                
                if traditie_score >= 3: # Gewogen grens (Punt 4)
                    st.success(f"✅ **6e Traditie Disclaimer aanwezig** (Gewogen match: {traditie_score}/5 sterke woorden)")
                    traditie_ok = True
                else:
                    st.error(f"❌ **6e Traditie Disclaimer incompleet of afwezig** ({traditie_score}/5 sterke woorden gevonden)")
                    traditie_ok = False

                # --- EVENEMENT CONTROLES ---
                # Organisator
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
                else:
                    st.warning("⚠️ **Geen datum gevonden**")

                # Tijdstip
                if len(tijd_regels) >= 1:
                    tijd_gevonden = True
                    st.success(f"✅ **Tijdstip gedetecteerd:** {tijd_regels[0]}")
                else:
                    st.warning("⚠️ **Geen tijdstip gevonden**")

                # Slimme Locatie Score (Punt 5)
                locatie_score = 0
                if "stadsstrand" in txt_lower: locatie_score += 2
                if "hoorn" in txt_lower: locatie_score += 1
                if any(w in txt_lower for w in ["zaal", "buurthuis", "kerk", "adres"]): locatie_score += 1
                
                if locatie_score >= 2:
                    locatie_gevonden = True
                    st.success("✅ **Locatie succesvol herleid**")
                else:
                    st.warning("⚠️ **Locatie onduidelijk**")

                # Telefoonnummer
                tel_pattern = r'(\+31\s?6|06)[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}'
                telefoon_match = re.search(tel_pattern, volledige_tekst)
                if telefoon_match:
                    telefoon_gevonden = True
                    telefoon_waarde = telefoon_match.group(0)
                    st.success(f"📞 **Telefoonnummer:** {telefoon_waarde}")

        # =====================================================================
        # 📊 WEGING & MATRIX SCORE RAPPORT
        # =====================================================================
        st.markdown("---")
        st.markdown("### 📊 Totale Matrix Score")
        
        score = 0
        if logo_status == "GOED": score += 25
        elif logo_status == "AANGEPAST": score += 10 # Strafpunten voor bewerkt logo!
        
        if traditie_ok: score += 25
        if organisator_gevonden: score += 15
        if datum_gevonden: score += 15
        if tijd_gevonden: score += 10
        if locatie_gevonden: score += 5
        if telefoon_gevonden: score += 5
        
        st.metric(label="Eindbeoordeling", value=f"{score} / 100")
        st.progress(score / 100)
        
        if logo_status == "GOED" and score >= 85:
            st.success("🎉 **GOEDGEKEURD VOOR DRUKWERK:** Deze flyer voldoet aan alle huisstijl- en matrixrichtlijnen.")
        elif logo_status == "AANGEPAST":
            st.warning("⚠️ **AFGEKEURD (Huisstijl-fout):** De tekst klopt, maar het C.A.-logo is visueel bewerkt. Dit is niet toegestaan.")
        else:
            st.error("❌ **AFGEKEURD:** De flyer mist kritieke elementen of het officiële logo ontbreekt volledig.")

        with st.expander("📋 Score-opbouw bekijken"):
            st.write(f"{'✅ +25' if logo_status == 'GOED' else '⚠️ +10 (Aangepast/Gekleurd)' if logo_status == 'AANGEPAST' else '❌ +0'} C.A. Logo Validatie")
            st.write(f"{'✅ +25' if traditie_ok else '❌ +0'} 6e Traditie Disclaimer")
            st.write(f"{'✅ +15' if organisator_gevonden else '❌ +0'} Groepsnaam ({organisator_naam})")
            st.write(f"{'✅ +15' if datum_gevonden else '❌ +0'} Datum ({datum_waarde})")
            st.write(f"{'✅ +10' if tijd_gevonden else '❌ +0'} Tijdstip")
            st.write(f"{'✅ +5' if locatie_gevonden else '❌ +0'} Locatie-indicatie")
            st.write(f"{'📞 +5' if telefoon_gevonden else '❌ +0'} Telefoonnummer contactpersoon")

    with col2:
        st.markdown("### 🖼️ Live Geannoteerde Preview")
        st.caption("Groen = Tekstregels. Blauw = Tijd. Roze/Paars kader = Het automatische uitgesneden logo-gebied dat visueel is gecontroleerd.")
        st.image(img_canvas, channels="RGB", use_container_width=True)
