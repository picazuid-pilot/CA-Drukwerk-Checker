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
    page_title="C.A. Drukwerk Checker v1.3",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Geavanceerde Hybride Validatie: OCR-Taalcontrole + Feature Matching")

def word_similarity(w1, w2):
    return SequenceMatcher(None, w1.lower().strip(), w2.lower().strip()).ratio()

@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl', 'en'], gpu=False) # Nu ingesteld op NL én EN
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

@st.cache_data
def load_reference_logos():
    # We laden idealiter beide referentielogo's in voor de visuele controle
    logo_nl = cv2.imread("assets/logo_nl.png", cv2.IMREAD_GRAYSCALE)
    logo_en = cv2.imread("assets/logo_en.png", cv2.IMREAD_GRAYSCALE)
    
    # Fallback dummies als de bestanden lokaal (nog) missen
    if logo_nl is None: logo_nl = np.zeros((200, 200), dtype=np.uint8)
    if logo_en is None: logo_en = np.zeros((200, 200), dtype=np.uint8)
    return logo_nl, logo_en

reference_logo_nl, reference_logo_en = load_reference_logos()

st.info("⚙️ **Systeemstatus:** Actief. Flow: OCR Detectie ➔ Taal- & Inhoudscheck ➔ ORB Systeemonderzoek.")

uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        if len(img_np.shape) == 3 and img_np.shape[2] == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            
        img_gray_orig = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        img_enhanced = cv2.adaptiveThreshold(img_gray_orig, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        img_clahe = clahe.apply(img_gray_orig)
        
        img_canvas = img_np.copy()
    except Exception as e:
        st.error(f"❌ Fout bij het verwerken van de afbeelding: {e}")
        st.stop()

    # Initialisatie
    unieke_teksten = []
    gevonden_keys = set()
    tijd_regels = []
    alle_losse_woorden = []
    logo_bboxes = []
    
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
        st.markdown("### 📝 Matrix Analyse")
        
        if reader is not None:
            with st.spinner("Scannen via Multi-Pass OCR..."):
                ocr_results = reader.readtext(img_np, detail=1) + reader.readtext(img_enhanced, detail=1) + reader.readtext(img_clahe, detail=1)
                
                # Definieer de doelwoorden voor de OCR-voorverkenner
                keywords_nl = ["hoop", "vertrouwen", "moed"]
                keywords_en = ["hope", "faith", "courage"]
                keywords_clashing = ["kracht", "unity"] # Woorden van andere fellowships die foutief gebruikt worden
                
                all_target_keywords = keywords_nl + keywords_en + keywords_clashing

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
                    
                    # Teken basis kaders
                    tl = tuple(map(int, bbox[0]))
                    br = tuple(map(int, bbox[2]))
                    cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                    
                    # STAP 1: Logo-locatie vinden via OCR (BBox clustering)
                    if any(any(word_similarity(kw, w) >= 0.80 for w in woorden_in_regel) for kw in all_target_keywords):
                        logo_bboxes.append(bbox)
                    
                    if re.search(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean):
                        tijd_regels.append(txt_clean.lower())
                        cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

                volledige_tekst = " ".join(unieke_teksten)
                txt_lower = volledige_tekst.lower()

                # --- STAP 2: LOGO TAAL- & INHOUDSVALIDATIE ---
                gevonden_nl = set(kw for kw in keywords_nl if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden))
                gevonden_en = set(kw for kw in keywords_en if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden))
                gevonden_clash = set(kw for kw in keywords_clashing if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden))

                st.markdown("#### 🖼️ C.A. Logo Validatie Rapport")
                
                logo_taal = "ONBEKEND"
                logo_inhoud_fout = False
                
                if gevonden_clash:
                    logo_inhoud_fout = True
                    st.error(f"❌ **Inhoudelijke logo-fout ontdekt!** Er zijn verboden of afwijkende trefwoorden gelezen (*{', '.join(gevonden_clash)}*). Dit logo hoort bij een andere fellowship of wijkt af van de C.A. richtlijnen!")
                elif len(gevonden_nl) >= 2 and len(gevonden_en) >= 2:
                    logo_inhoud_fout = True
                    st.error("❌ **Inhoudelijke logo-fout:** Mix van talen ontdekt binnen het logo (bijv. 'Hoop' gecombineerd met 'Courage').")
                elif len(gevonden_nl) >= 2:
                    logo_taal = "NL"
                    st.info(f"🔍 **Nederlandstalige logo-tekst herkend** (*{', '.join(gevonden_nl)}*)")
                elif len(gevonden_en) >= 2:
                    logo_taal = "EN"
                    st.warning(f"⚠️ **Engelstalige logo-tekst herkend** (*{', '.join(gevonden_en)}*). Controleer of de regio of commissie een Nederlandstalige flyer vereist.")
                else:
                    st.error("❌ **C.A. Logo niet herkend:** Geen sluitende kernwoorden gevonden in de cirkeltekst.")

                # --- STAP 3: VISUELE GEBIEDSCONTROLE VIA FEATURE MATCHING ---
                logo_visueel_gevalideerd = False
                orb_matches = 0
                
                if logo_taal != "ONBEKEND" and not logo_inhoud_fout and logo_bboxes:
                    try:
                        # Bereken de crop-coördinaten rondom de gevonden woorden
                        all_pts = np.array([pt for bbox in logo_bboxes for pt in bbox], dtype=np.int32)
                        x, y, w, h = cv2.boundingRect(all_pts)
                        
                        marge = 45
                        h_img, w_img = img_gray_orig.shape
                        ymin, ymax = max(0, y-marge), min(h_img, y+h+marge)
                        xmin, xmax = max(0, x-marge), min(w_img, x+w+marge)
                        
                        cropped_logo = img_gray_orig[ymin:ymax, xmin:xmax]
                        
                        if cropped_logo.size > 0:
                            # Kies het juiste referentielogo op basis van de OCR-taaldetectie
                            ref_img = reference_logo_nl if logo_taal == "NL" else reference_logo_en
                            
                            orb = cv2.ORB_create(nfeatures=600)
                            kp1, des1 = orb.detectAndCompute(ref_img, None)
                            kp2, des2 = orb.detectAndCompute(cropped_logo, None)
                            
                            if des1 is not None and des2 is not None:
                                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                                matches = bf.match(des1, des2)
                                good_matches = [m for m in matches if m.distance < 40]
                                orb_matches = len(good_matches)
                                
                                # Teken paars validatiekader op de live preview
                                cv2.rectangle(img_canvas, (xmin, ymin), (xmax, ymax), (255, 0, 255), 4)
                                
                                # Beoordelingsmatrix op basis van jouw voorgestelde grenzen
                                if orb_matches >= 15:
                                    logo_visueel_gevalideerd = True
                                    st.success(f"✅ **Visuele integriteit gecontroleerd:** Logo is ongewijzigd en conform de officiële grafische richtlijnen. (ORB Matches: {orb_matches})")
                                elif orb_matches >= 8:
                                    st.warning(f"⚠️ **Logo mogelijk aangepast:** De tekst klopt, maar de visuele structuur of kleur wijkt af van het origineel. (ORB Matches: {orb_matches})")
                                else:
                                    st.error(f"❌ **Sterk afwijkend logo:** De letters zijn aanwezig, maar de vorm, randen of opmaak zijn ontoelaatbaar bewerkt. (ORB Matches: {orb_matches})")
                    except Exception:
                        pass

                # --- REST VAN DE MATRIX CHECKLIST ---
                st.markdown("---")
                st.markdown("#### 📋 Inhoudelijke Checklist")
                
                # 6e Traditie gewogen keywords
                sterke_keywords = ["6e", "traditie", "kerken", "sekten", "hulpverlenende", "instanties"]
                traditie_score = sum(1 for kw in sterke_keywords if any(word_similarity(kw, w) >= 0.80 for w in alle_losse_woorden))
                
                if traditie_score >= 3:
                    st.success(f"✅ **6e Traditie Disclaimer aanwezig** ({traditie_score}/5 sterke woorden)")
                    traditie_ok = True
                else:
                    st.error(f"❌ **6e Traditie Disclaimer incompleet** ({traditie_score}/5 sterke woorden)")
                    traditie_ok = False

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

                # Tijd
                if len(tijd_regels) >= 1:
                    tijd_gevonden = True
                    st.success(f"✅ **Tijdstip gedetecteerd:** {tijd_regels[0]}")

                # Locatie score
                locatie_score = (2 if "stadsstrand" in txt_lower else 0) + (1 if "hoorn" in txt_lower else 0)
                if locatie_score >= 2:
                    locatie_gevonden = True
                    st.success("✅ **Locatie succesvol herleid**")
                else:
                    st.warning("⚠️ **Locatie onduidelijk**")

                # Telefoon
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
        st.markdown("### 📊 Totale Matrix Score")
        
        score = 0
        if logo_visueel_gevalideerd: score += 25
        elif logo_taal != "ONBEKEND" and not logo_inhoud_fout: score += 10 # Alleen tekst-match, visueel afgekeurd
        
        if traditie_ok: score += 25
        if organisator_gevonden: score += 15
        if datum_gevonden: score += 15
        if tijd_gevonden: score += 10
        if locatie_gevonden: score += 5
        if telefoon_gevonden: score += 5
        
        st.metric(label="Eindbeoordeling Matrix", value=f"{score} / 100")
        st.progress(score / 100)
        
        if logo_visueel_gevalideerd and score >= 85:
            st.success("🎉 **GOEDGEKEURD VOOR PUBLICATIE:** Flyer voldoet volledig aan de inhoudelijke matrix én de grafische merkrechten.")
        elif logo_taal != "ONBEKEND" and not logo_visueel_gevalideerd:
            st.error("❌ **AFGEKEURD (Huisstijl-fout):** De tekst in het logo klopt, maar de grafische vorm of kleur is ontoelaatbaar bewerkt.")
        else:
            st.error("❌ **AFGEKEURD:** Deze flyer bevat kritieke fouten in het logo of mist essentiële matrixgegevens.")

    with col2:
        st.markdown("### 🖼️ Live Geannoteerde Preview")
        st.caption("Groen = Tekst. Blauw = Tijd. Paars = Gecropte zone waarbinnen het logo taalkundig en visueel is gevalideerd.")
        st.image(img_canvas, channels="RGB", use_container_width=True)
