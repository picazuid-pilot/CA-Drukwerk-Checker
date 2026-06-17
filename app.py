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
    page_title="C.A. Drukwerk Checker",
    page_icon="📋",
    layout="wide"
)

st.title("📋 C.A. Drukwerk Checker")
st.subheader("Controleer de verplichte elementen en inhoud van de flyer matrix")

# 1. Cache de EasyOCR Reader
@st.cache_resource
def load_ocr_reader():
    try:
        return easyocr.Reader(['nl'], gpu=False)
    except Exception as e:
        st.error(f"❌ Fout bij het laden van EasyOCR: {e}")
        return None

reader = load_ocr_reader()

# 2. Lokale logo's laden (stabieler dan GitHub)
@st.cache_data
def load_local_logos():
    """Laad logo's lokaal in plaats van van GitHub"""
    logos = []
    
    # Probeer lokale bestanden te laden
    logo_paths = ["logo1.png", "logo2.png"]
    
    for path in logo_paths:
        try:
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    logos.append(img)
                    st.sidebar.write(f"✅ Logo geladen: {path} ({img.shape})")
                else:
                    st.sidebar.warning(f"⚠️ Kon logo niet laden: {path}")
            else:
                st.sidebar.warning(f"⚠️ Bestand niet gevonden: {path}")
        except Exception as e:
            st.sidebar.error(f"❌ Fout bij laden {path}: {e}")
    
    return logos

# Laad logo's
logos = load_local_logos()
st.sidebar.write(f"📦 Totaal logo's geladen: {len(logos)}")

# 3. Helperfunctie voor tekstgelijkenis (Fuzzy Match)
def similarity(a, b):
    """Bereken hoe sterk twee woorden op elkaar lijken (0.0 - 1.0)"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

def word_similarity_score(word, text_list, threshold=0.70):
    """Check of een woord voorkomt in een lijst met fuzzy matching"""
    if not word or not text_list:
        return False
    word = word.lower().strip()
    for text in text_list:
        if similarity(word, text) >= threshold:
            return True
    return False

# 4. Multi-Pass OCR voorbereiding
def prepare_ocr_passes(image):
    """Genereert meerdere varianten voor Multi-Pass OCR"""
    passes = []
    
    # Pass 1: Origineel
    passes.append(("origineel", image.copy()))
    
    # Pass 2: Opgeschaald (2x) voor kleine tekst
    h, w = image.shape[:2]
    if h < 1500 or w < 1500:
        scaled = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    else:
        scaled = image.copy()
    passes.append(("opgeschaald", scaled))
    
    # Pass 3: Contrastverbetering (CLAHE)
    lab = cv2.cvtColor(scaled, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    l_enhanced = clahe.apply(l)
    lab_enhanced = cv2.merge((l_enhanced, a, b))
    enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2RGB)
    passes.append(("contrast", enhanced))
    
    return passes

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

# --- INITIALISEER ALLE VARIABELEN (voorkomt NameError) ---
volledige_tekst = ""
woorden_set = set()
tijd_regels = []
ruwe_regels_debug = []
logo_gevonden = False
logo_score = 0.0
logo_methode = []
traditie_score = 0
totaal_keywords = 0
organisator_gevonden = False
gevonden_event = []
datum_match = None
locatie_gevonden = False
telefoon_match = None
email_match = None
gevonden_online = []

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # Voorbereiden voor Multi-Pass OCR
        ocr_passes = prepare_ocr_passes(img_np)
        
        # Canvas voor visualisatie (gebruik de opgeschaalde versie)
        img_canvas = ocr_passes[1][1].copy()  # De opgeschaalde versie
        img_gray_canvas = cv2.cvtColor(img_canvas, cv2.COLOR_RGB2GRAY)
        
    except Exception as e:
        st.error(f"❌ Fout bij het openen van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geladen. Multi-Pass Analyse start...")

    # Twee kolommen: links de Checklist Matrix, rechts het Voorbeeldscherm
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Matrix Resultaten")
        
        if reader is None:
            st.error("OCR-module is offline.")
        else:
            with st.spinner("Uitvoeren van Multi-Pass OCR (3 passes)..."):
                try:
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    st.caption("Gedetecteerde tekst uit alle 3 de OCR-passes:")
                    
                    # --- MULTI-PASS OCR STRATEGIE ---
                    alle_woorden = []
                    alle_teksten_raw = []
                    
                    for pass_name, img_pass in ocr_passes:
                        st.write(f"**Pass {pass_name}:**")
                        results = reader.readtext(img_pass, detail=1)
                        
                        # Bepaal schaalfactor voor kaders
                        if pass_name == "origineel":
                            scale_factor = 2.0  # Origineel is kleiner, opschalen naar canvas
                        else:
                            scale_factor = 1.0  # Al op schaal
                        
                        for (bbox, text, prob) in results:
                            ruwe_regels_debug.append(f"[{pass_name}] {text}")
                            st.write(f"• `{text}`")
                            
                            # --- TEXT CLEANING ---
                            txt_clean = text.upper()
                            txt_clean = txt_clean.replace("O", "0").replace("o", "0")
                            txt_clean = txt_clean.replace("JUII", "JULI").replace("JU1I", "JULI")
                            txt_clean = txt_clean.replace("T0 T", "TOT").replace("T0T", "TOT")
                            
                            # Tijdsnotaties opschonen
                            txt_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', txt_clean)
                            txt_clean = txt_clean.replace(" : ", ":").replace(": ", ":").replace(" :", ":")
                            txt_clean = txt_clean.replace(" . ", ":").replace(". ", ":").replace(" .", ":")
                            txt_clean = re.sub(r'(\d{1,2})\s+(\d{2})', r'\1:\2', txt_clean)
                            txt_clean = txt_clean.replace(';', ':').replace('.', ':')
                            
                            # Opslaan voor analyse
                            alle_woorden.extend(txt_clean.lower().split())
                            alle_teksten_raw.append(txt_clean.lower())
                            
                            # --- KADERS TEKENEN ---
                            tl = (int(bbox[0][0] * scale_factor), int(bbox[0][1] * scale_factor))
                            br = (int(bbox[2][0] * scale_factor), int(bbox[2][1] * scale_factor))
                            cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 1)
                            
                            # --- TIJD DETECTIE ---
                            tijd_matches = re.findall(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean)
                            if tijd_matches:
                                tijd_regels.append(txt_clean.lower())
                                cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)
                    
                    # Maak één string van alle gevonden woorden
                    volledige_tekst = " ".join(alle_teksten_raw)
                    woorden_set = set(alle_woorden)
                    
                    st.markdown("---")
                    st.markdown("#### 📋 Matrix Checklist")
                    
                    # --- CHECK 1: 6E TRADITIE (KRITIEK) ---
                    st.markdown("##### 🔴 Kritieke Controles")
                    
                    traditie_keywords = [
                        "6e", "traditie", "verbonden", "kerken", 
                        "sekten", "politieke", "hulpverlenende", "instanties"
                    ]
                    
                    gevonden_traditie = []
                    for kw in traditie_keywords:
                        if word_similarity_score(kw, woorden_set, 0.70):
                            gevonden_traditie.append(kw)
                    
                    traditie_score = len(gevonden_traditie)
                    totaal_keywords = len(traditie_keywords)
                    
                    if traditie_score >= 6:
                        st.success(f"✅ **6e traditie aanwezig** ({traditie_score}/{totaal_keywords} kernwoorden gevonden)")
                    elif traditie_score >= 4:
                        st.warning(f"⚠️ **6e traditie gedeeltelijk herkend** ({traditie_score}/{totaal_keywords} - gevonden: {', '.join(gevonden_traditie)})")
                    else:
                        st.error(f"❌ **6e traditie ontbreekt** (slechts {traditie_score}/{totaal_keywords} kernwoorden gevonden)")

                    # --- CHECK 2: ORGANISATOR ---
                    st.markdown("##### 🏢 Evenementgegevens")
                    
                    organisator_gevonden = False
                    for woord in woorden_set:
                        if re.search(r'ca[\s\-]+[a-z0-9]+', woord, re.IGNORECASE):
                            organisator_gevonden = True
                            st.success(f"✅ **Organisator gevonden:** {woord.upper()}")
                            break
                    
                    if not organisator_gevonden:
                        # Fallback: zoek naar "CA" + plaatsnaam
                        ca_plaats = False
                        plaatsen = ["hoorn", "amsterdam", "rotterdam", "utrecht", "haarlem", "den haag"]
                        for plaats in plaatsen:
                            if plaats in woorden_set or word_similarity_score(plaats, woorden_set, 0.75):
                                if "ca" in woorden_set or any("ca" in w for w in woorden_set):
                                    ca_plaats = True
                                    st.success(f"✅ **Organisator gevonden (fuzzy):** CA {plaats.title()}")
                                    break
                        
                        if not ca_plaats:
                            st.warning("⚠️ **Geen specifieke CA-groep herkend**")

                    # --- CHECK 3: EVENEMENTNAAM ---
                    evenement_woorden = [
                        "event", "bbq", "fundraiser", "conventie", "feest", 
                        "zomer", "winter", "lente", "herfst", "workshop", 
                        "meeting", "speaker", "countdown", "bijeenkomst",
                        "actie", "dag", "avond", "middag", "bijeen"
                    ]
                    
                    gevonden_event = [w for w in evenement_woorden if w in woorden_set]
                    if gevonden_event:
                        st.success(f"✅ **Evenement gevonden:** {', '.join(gevonden_event[:3])}")
                    else:
                        st.info("ℹ️ **Geen duidelijke evenementnaam herkend**")

                    # --- CHECK 4: DATUM ---
                    maanden = "januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec"
                    datum_match = re.search(rf'(\d+[-/]\d+[-/]\d+|\d+\s+({maanden}))', volledige_tekst, re.IGNORECASE)
                    if datum_match:
                        st.success(f"✅ **Datum gevonden:** {datum_match.group(0)}")
                    else:
                        st.warning("⚠️ **Geen datum gevonden**")

                    # --- CHECK 5: TIJD ---
                    tijd_regels = list(set(tijd_regels))
                    if len(tijd_regels) >= 2:
                        st.success(f"✅ **Tijdsbereik gevonden:** {tijd_regels[0]} tot {tijd_regels[1]}")
                    elif len(tijd_regels) == 1:
                        st.info(f"ℹ️ **Enkele tijd gevonden:** {tijd_regels[0]}")
                    else:
                        st.warning("⚠️ **Geen tijd gevonden**")

                    # --- CHECK 6: LOCATIE ---
                    postcode_match = re.search(r'\d{4}\s*[a-z]{2}', volledige_tekst, re.IGNORECASE)
                    locatie_woorden = [
                        "strand", "centrum", "kerk", "zaal", "hotel", 
                        "gebouw", "buurthuis", "community", "hoorn", 
                        "amsterdam", "rotterdam", "utrecht", "haarlem"
                    ]
                    
                    locatie_gevonden = False
                    if postcode_match:
                        locatie_gevonden = True
                        st.success(f"✅ **Locatie gevonden (postcode):** {postcode_match.group(0)}")
                    else:
                        gevonden_loc = [w for w in locatie_woorden if w in woorden_set]
                        if gevonden_loc:
                            locatie_gevonden = True
                            st.success(f"✅ **Locatie gevonden:** {', '.join(gevonden_loc[:2])}")
                        else:
                            st.warning("⚠️ **Locatie niet duidelijk herkend**")

                    # --- CHECK 7: CONTACTGEGEVENS ---
                    st.markdown("##### 📞 Contactgegevens")
                    
                    telefoon_match = re.search(r'(06[- ]*\d{8}|\+31[- ]*6[- ]*\d{8})', volledige_tekst)
                    if telefoon_match:
                        st.success(f"✅ **Telefoon:** {telefoon_match.group(0)}")
                    else:
                        st.info("ℹ️ **Geen telefoonnummer gevonden**")
                    
                    email_match = re.search(r'[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}', volledige_tekst, re.IGNORECASE)
                    if email_match:
                        st.success(f"✅ **E-mail:** {email_match.group(0)}")
                    else:
                        st.info("ℹ️ **Geen e-mailadres gevonden**")

                    # --- CHECK 8: ONLINE ---
                    st.markdown("##### 🌐 Online")
                    online_woorden = ["zoom", "meet", "teams", "skype", "google"]
                    gevonden_online = [w for w in online_woorden if w in woorden_set]
                    if gevonden_online:
                        st.success(f"✅ **Online link gevonden:** {', '.join(gevonden_online)}")
                    else:
                        st.info("ℹ️ **Geen online link gevonden**")

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")
                    import traceback
                    st.code(traceback.format_exc())

        # ---- LOGO CHECK ----
        st.markdown("### 🖼️ CA-Logo Controle")
        
        logo_gevonden = False
        logo_score = 0.0
        logo_methode = []
        
        # Methode 1: Cirkeltekst herkenning (fuzzy)
        logo_keywords = ["hoop", "vertrouwen", "moed", "cocaine", "anonymous"]
        gevonden_logo = []
        
        for kw in logo_keywords:
            if word_similarity_score(kw, woorden_set, 0.70):
                gevonden_logo.append(kw)
        
        logo_tekst_score = len(gevonden_logo)
        if logo_tekst_score >= 2:
            logo_score += 2.0
            logo_methode.append("tekst")
        if logo_tekst_score >= 3:
            logo_score += 1.0
        
        # Methode 2: Zoek naar "CA" als zelfstandig woord
        if "ca" in woorden_set:
            logo_score += 0.5
            logo_methode.append("ca_tekst")
        
        # Methode 3: Zoek naar "Cocaine Anonymous" in tekst
        if "cocaine" in woorden_set and "anonymous" in woorden_set:
            logo_score += 1.0
            logo_methode.append("coca_anoniem")
        
        # Methode 4: Template matching (alleen als fallback)
        if logos and logo_score < 2.0:
            with st.spinner("Zoeken naar CA-logo via template matching..."):
                try:
                    for logo in logos:
                        # Probeer verschillende thresholds
                        for threshold in [0.40, 0.45, 0.50]:
                            for scale in [1.0, 0.75, 0.5]:
                                if scale != 1.0:
                                    h, w = logo.shape
                                    logo_scaled = cv2.resize(logo, (int(w*scale), int(h*scale)))
                                else:
                                    logo_scaled = logo
                                
                                res = cv2.matchTemplate(img_gray_canvas, logo_scaled, cv2.TM_CCOEFF_NORMED)
                                loc = np.where(res >= threshold)
                                
                                if len(loc[0]) > 0:
                                    h_s, w_s = logo_scaled.shape
                                    pt = (loc[1][0], loc[0][0])
                                    cv2.rectangle(img_canvas, pt, (pt[0] + w_s, pt[1] + h_s), (255, 0, 0), 5)
                                    logo_score += 1.5
                                    logo_methode.append("template")
                                    break
                            if logo_score >= 1.5:
                                break
                        if logo_score >= 1.5:
                            break
                except Exception as e:
                    st.warning(f"Template matching fallback error: {e}")
        
        # Eindbeoordeling
        if logo_score >= 3.0:
            logo_gevonden = True
            st.success(f"✅ **CA-logo aanwezig** (score: {logo_score:.1f}/5.0 - methodes: {', '.join(set(logo_methode))})")
            if gevonden_logo:
                st.caption(f"Herkenbare logo-tekst: {', '.join(gevonden_logo)}")
        elif logo_score >= 1.5:
            logo_gevonden = True
            st.warning(f"⚠️ **CA-logo waarschijnlijk aanwezig** (score: {logo_score:.1f}/5.0 - methodes: {', '.join(set(logo_methode))})")
            if gevonden_logo:
                st.caption(f"Herkenbare logo-tekst: {', '.join(gevonden_logo)}")
        else:
            st.warning(f"⚠️ **Geen officieel CA-logo herkend** (score: {logo_score:.1f}/5.0)")

        # --- SAMENVATTEND RAPPORT ---
        st.markdown("---")
        st.markdown("#### 📊 Samenvattend Rapport")
        
        # Bepaal kritieke status
        kritiek_geslaagd = logo_gevonden and traditie_score >= 6
        
        if kritiek_geslaagd:
            st.success("✅ **Alle kritieke controles geslaagd!**")
            st.success("Het CA-logo is aanwezig en de 6e traditie is correct opgenomen.")
        else:
            if not logo_gevonden:
                st.error("❌ **Kritieke check mislukt:** CA-logo niet gevonden")
            if traditie_score < 6:
                st.error(f"❌ **Kritieke check mislukt:** 6e traditie incompleet ({traditie_score}/{totaal_keywords} kernwoorden)")
        
        # Detailrapport
        with st.expander("📋 Bekijk gedetailleerd analyse-rapport"):
            st.markdown("**🔴 Kritieke controles**")
            st.write(f"{'✅' if logo_gevonden else '❌'} CA-logo (score: {logo_score:.1f}/5.0)")
            st.write(f"{'✅' if traditie_score >= 6 else '⚠️' if traditie_score >= 4 else '❌'} 6e traditie ({traditie_score}/{totaal_keywords} woorden)")
            
            st.markdown("**🏢 Evenement**")
            st.write(f"{'✅' if organisator_gevonden else '❌'} Organisator")
            st.write(f"{'✅' if gevonden_event else 'ℹ️'} Evenementnaam")
            st.write(f"{'✅' if datum_match else '❌'} Datum")
            st.write(f"{'✅' if tijd_regels else '❌'} Tijd")
            st.write(f"{'✅' if locatie_gevonden else '⚠️'} Locatie")
            
            st.markdown("**📞 Contact**")
            st.write(f"{'✅' if telefoon_match else 'ℹ️'} Telefoonnummer")
            st.write(f"{'✅' if email_match else 'ℹ️'} E-mailadres")
            
            st.markdown("**🌐 Online**")
            st.write(f"{'✅' if gevonden_online else 'ℹ️'} Online link")

    # RECHTERKOLOM: Visueel voorbeeldscherm
    with col2:
        st.markdown("### 🖼️ Voorbeeldscherm (Visuele Matrix)")
        st.caption("🟢 Groen = Tekst | 🔵 Blauw = Tijd of Logo")
        
        st.image(img_canvas, use_column_width=True, caption="Opgeschaalde flyer met matrix-omlijningen")
        
        if volledige_tekst:
            with st.expander("Bekijk alle gecombineerde OCR-tekst"):
                st.write(volledige_tekst)
        
        if ruwe_regels_debug:
            with st.expander("🔧 Multi-Pass OCR Debug Log"):
                for regel in ruwe_regels_debug[:50]:
                    st.write(f"• {regel}")
                if len(ruwe_regels_debug) > 50:
                    st.write(f"... en nog {len(ruwe_regels_debug)-50} regels")

    # Sidebar met debug info
    with st.sidebar:
        st.markdown("### 📊 Debug Info")
        st.write(f"Logo templates: {len(logos)}")
        st.write(f"Woorden gevonden: {len(woorden_set)}")
        st.write(f"OCR passes: 3")
        
        if tijd_regels:
            st.markdown("### ⏰ Gedetecteerde tijden")
            for t in set(tijd_regels):
                st.write(f"• `{t}`")
else:
    # Instructies als er geen bestand is geüpload
    st.info("👆 Upload een flyer (JPG, JPEG, PNG) om te beginnen met de analyse.")
    st.markdown("""
    ### Wat wordt gecontroleerd?
    
    **🔴 Kritieke elementen:**
    - CA-logo (herkenning via tekst + template matching)
    - 6e traditie disclaimer
    
    **🏢 Evenementgegevens:**
    - Organisator (CA + plaatsnaam)
    - Evenementnaam/type
    - Datum
    - Tijd
    - Locatie
    
    **📞 Contactgegevens:**
    - Telefoonnummer
    - E-mailadres
    
    **🌐 Online elementen:**
    - Zoom/Meet/Teams link
    """)
