import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import easyocr
import requests
import re
from difflib import SequenceMatcher

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

# 2. Functie om logo's veilig te downloaden van GitHub
@st.cache_data
def download_official_logos():
    logos = []
    urls = [
        "https://raw.githubusercontent.com/picazuid-pilot/CA-Drukwerk-Checker/main/logo1.png",
        "https://raw.githubusercontent.com/picazuid-pilot/CA-Drukwerk-Checker/main/logo2.png"
    ]
    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                img_bytes = np.frombuffer(response.content, dtype=np.uint8)
                img = cv2.imdecode(img_bytes, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    logos.append(img)
        except Exception:
            pass
    return logos

logos = download_official_logos()

# 3. Verbeterde fuzzy matching met difflib
def similarity(a, b):
    """Bereken gelijkenis tussen twee strings (0-100%)"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100

def fuzzy_match(text, reference, threshold=70):
    """Check of tekst overeenkomt met referentie"""
    text = text.lower().strip()
    reference = reference.lower().strip()
    
    # Exacte match of substring
    if reference in text or text in reference:
        return 100
    
    # Woord-overlap berekenen
    words1 = set(text.split())
    words2 = set(reference.split())
    
    if not words1 or not words2:
        return 0
    
    # Bereken gemiddelde similarity voor alle woorden
    total_similarity = 0
    count = 0
    
    for w1 in words1:
        best_match = 0
        for w2 in words2:
            sim = similarity(w1, w2)
            if sim > best_match:
                best_match = sim
        if best_match > 60:  # Alleen woorden die redelijk overeenkomen
            total_similarity += best_match
            count += 1
    
    if count == 0:
        return 0
    
    return total_similarity / count

# 4. Functie voor OCR met voorbewerking
def preprocess_for_ocr(image):
    """Verbeter OCR voor lichte tekst op lichte achtergrond"""
    # Schaal de afbeelding op voor betere herkenning
    scale = 2
    if image.shape[0] < 1000 or image.shape[1] < 1000:
        scaled = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    else:
        scaled = image.copy()
    
    # Converteer naar grayscale
    gray = cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)
    
    # Pas adaptieve threshold toe voor lichte tekst
    enhanced = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2
    )
    
    return scaled, enhanced

# Bestandsuploader
uploaded_file = st.file_uploader("Upload hier de flyer (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    
    try:
        image_pil = Image.open(io.BytesIO(file_bytes))
        img_np = np.array(image_pil)
        
        # Kopie maken voor het visuele voorbeeldscherm met omlijningen
        img_canvas = img_np.copy()
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        
        # Voorbewerking voor OCR
        img_ocr_scaled, img_ocr_enhanced = preprocess_for_ocr(img_np)
        
    except Exception as e:
        st.error(f"❌ Fout bij het openen van de afbeelding: {e}")
        st.stop()

    st.success("✅ Bestand succesvol geladen. Analyse start...")

    # Twee kolommen: links de Checklist Matrix, rechts het Voorbeeldscherm
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📝 Matrix Resultaten")
        
        # --- INITIALISEER ALLE VARIABELEN ---
        volledige_tekst = ""
        txt_lower = ""
        logo_gevonden = False
        logo_score = 0
        zesde_traditie_score = 0
        traditie_fuzzy_score = 0
        tijd_regels = []
        ruwe_regels = []
        
        if reader is None:
            st.error("OCR-module is offline.")
        else:
            with st.spinner("Tekst scannen en analyseren..."):
                try:
                    # Gebruik de verbeterde afbeelding voor OCR
                    ocr_results = reader.readtext(img_ocr_enhanced, detail=1)
                    
                    alle_teksten = []
                    
                    st.markdown("#### 🔍 Live OCR Debug Output")
                    st.caption("Hieronder zie je exact wat de scanner regel-voor-regel aantreft:")
                    
                    for (bbox, text, prob) in ocr_results:
                        # Toon direct op het scherm wat er gelezen wordt om te debuggen
                        ruwe_regels.append(text)
                        st.write(f"• OCR leest: `{text}`")
                        
                        # --- STAP 1: NORMALISATIE VAN TEXT ---
                        txt_clean = text
                        
                        # Specifieke OCR-correcties
                        txt_clean = txt_clean.replace("O", "0").replace("o", "0")
                        txt_clean = txt_clean.replace("juii", "juli").replace("juIi", "juli").replace("ju1i", "juli")
                        
                        # Verbetering: "t0 t" wordt "tot"
                        txt_clean = txt_clean.lower()
                        txt_clean = txt_clean.replace("t0 t", "tot")
                        txt_clean = txt_clean.replace("t0t", "tot")
                        
                        # Verbetering: Verwijder ALLE spaties binnen tijden
                        txt_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', txt_clean)
                        txt_clean = txt_clean.replace(" : ", ":")
                        txt_clean = txt_clean.replace(": ", ":")
                        txt_clean = txt_clean.replace(" :", ":")
                        txt_clean = txt_clean.replace(" . ", ":")
                        txt_clean = txt_clean.replace(". ", ":")
                        txt_clean = txt_clean.replace(" .", ":")
                        
                        # Herstel tijdsnotaties met spaties (bijv. '12 00' naar '12:00')
                        txt_clean = re.sub(r'(\d{1,2})\s+(\d{2})', r'\1:\2', txt_clean)
                        txt_clean = txt_clean.replace(';', ':')
                        txt_clean = txt_clean.replace('.', ':')
                        
                        alle_teksten.append(txt_clean)
                        
                        # Coördinaten voor het omlijnelement aan de rechterkant
                        scale_factor = 2 if (img_np.shape[0] < 1000 or img_np.shape[1] < 1000) else 1
                        tl = tuple(map(int, [bbox[0][0]/scale_factor, bbox[0][1]/scale_factor]))
                        br = tuple(map(int, [bbox[2][0]/scale_factor, bbox[2][1]/scale_factor]))
                        
                        # Standaard groen kader om elk gedetecteerd tekstveld
                        cv2.rectangle(img_canvas, tl, br, (0, 255, 0), 2)
                        
                        # --- STAP 2: ROBUUSTE TIJD REGEX PER BLOK ---
                        tijd_matches = re.findall(r'\b\d{1,2}[:.;]?\d{2}\b', txt_clean)
                        if tijd_matches:
                            tijd_regels.append(txt_clean)
                            # Geef tijdsblokken een opvallend dikker blauw kader
                            cv2.rectangle(img_canvas, tl, br, (255, 0, 0), 3)

                    # Voeg alle regels samen voor de brede matrix-checks
                    volledige_tekst = " ".join(alle_teksten)
                    txt_lower = volledige_tekst.lower()
                    
                    st.markdown("---")
                    st.markdown("#### 📋 Matrix Checklist")
                    
                    # --- CHECK 1: 6E TRADITIE (KRITIEK) ---
                    st.markdown("##### 🔴 Kritieke Controles")
                    
                    traditie_reference = """
                    in de geest van de 6e traditie is c.a. niet verbonden aan kerken,
                    sekten, politieke of hulpverlenende instanties
                    """
                    
                    # Bereken fuzzy match score met verbeterde similarity
                    traditie_fuzzy_score = fuzzy_match(volledige_tekst, traditie_reference, 60)
                    
                    # Ook losse woorden checken
                    if "6e traditie" in txt_lower:
                        zesde_traditie_score += 2
                    if "niet verbonden" in txt_lower:
                        zesde_traditie_score += 2
                    if "kerken" in txt_lower:
                        zesde_traditie_score += 1
                    if "instantie" in txt_lower:
                        zesde_traditie_score += 1
                    if "hulpverlenende" in txt_lower:
                        zesde_traditie_score += 1
                    
                    # Combineer scores
                    if traditie_fuzzy_score >= 70:
                        st.success(f"✅ **6e traditie aanwezig** (fuzzy match: {traditie_fuzzy_score:.0f}%)")
                    elif zesde_traditie_score >= 3:
                        st.success(f"✅ **6e traditie aanwezig** (woordscore: {zesde_traditie_score}/6)")
                    elif zesde_traditie_score >= 1:
                        st.warning(f"⚠️ **6e traditie gedeeltelijk herkend** (score: {zesde_traditie_score}/6, fuzzy: {traditie_fuzzy_score:.0f}%)")
                    else:
                        st.error("❌ **6e traditie ontbreekt of is onleesbaar:** Denk aan de verplichte CA-disclaimer!")

                    # --- CHECK 2: ORGANISATOR ---
                    st.markdown("##### 🏢 Evenementgegevens")
                    
                    organisator_match = re.search(r'CA[\s\-]+[A-Za-z0-9]+', volledige_tekst, re.IGNORECASE)
                    if organisator_match:
                        st.success(f"✅ **Organisator gevonden:** {organisator_match.group(0)}")
                    else:
                        ca_pattern = re.search(r'CA\s+([A-Za-z]+)', volledige_tekst, re.IGNORECASE)
                        if ca_pattern:
                            st.success(f"✅ **Organisator gevonden (fuzzy):** {ca_pattern.group(0)}")
                        else:
                            st.warning("⚠️ **Geen specifieke CA-groep herkend** (bijv. 'CA Hoorn')")

                    # --- CHECK 3: EVENEMENTNAAM (verbeterd) ---
                    evenement_woorden = [
                        "event", "bbq", "fundraiser", "conventie", "feest", 
                        "zomer", "winter", "lente", "herfst", "workshop", 
                        "meeting", "speaker", "countdown", "bijeenkomst", 
                        "ontmoeting", "actie", "spreker"
                    ]
                    if any(woord in txt_lower for woord in evenement_woorden):
                        st.success(f"✅ **Evenementnaam gevonden**")
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
                    if len(tijd_regels) >= 2:
                        st.success(f"✅ **Tijdsbereik gevonden:** {tijd_regels[0]} tot {tijd_regels[1]}")
                    elif len(tijd_regels) == 1:
                        st.info(f"ℹ️ **Enkele tijd gevonden:** {tijd_regels[0]} (Geen eindtijd herleid)")
                    else:
                        st.warning("⚠️ **Geen tijdstip of bereik kunnen detecteren**")

                    # --- CHECK 6: LOCATIE (verbeterd) ---
                    # Eerst zoeken naar adrespatronen
                    adres_match = re.search(r'\d{1,4}\s+[A-Za-z]+\s+[A-Za-z]+', volledige_tekst)
                    postcode_match = re.search(r'\d{4}\s*[A-Z]{2}', volledige_tekst)
                    zoom_match = re.search(r'zoom|meet|teams', txt_lower)
                    
                    if adres_match or postcode_match:
                        locatie_gevonden = True
                        st.success(f"✅ **Locatie gevonden** (adres/postcode)")
                    else:
                        # Val terug op woordherkenning
                        locatie_woorden = [
                            "strand", "centrum", "kerk", "zaal", "hotel", 
                            "gebouw", "buurthuis", "community", "zaal"
                        ]
                        locatie_score = sum(1 for woord in locatie_woorden if woord in txt_lower)
                        
                        # Check op plaatsnamen (fuzzy)
                        plaatsen = ["hoorn", "amsterdam", "rotterdam", "utrecht", "den haag", "haarlem"]
                        plaats_gevonden = any(plaats in txt_lower for plaats in plaatsen)
                        
                        if locatie_score >= 2 or plaats_gevonden:
                            st.success(f"✅ **Locatie gevonden** (score: {locatie_score}/2+)")
                        else:
                            st.warning(f"⚠️ **Locatie niet duidelijk herkend** (score: {locatie_score}/2+)")

                    # --- CHECK 7: TELEFOON (aanbevolen) ---
                    st.markdown("##### 📞 Contactgegevens (aanbevolen)")
                    
                    telefoon_match = re.search(r'(06[- ]*\d{8}|\+31[- ]*6[- ]*\d{8})', volledige_tekst)
                    if telefoon_match:
                        st.success(f"✅ **Telefoonnummer gevonden:** {telefoon_match.group(0)}")
                    else:
                        st.info("ℹ️ **Geen telefoonnummer gevonden** (aanbevolen maar niet verplicht)")

                    # --- CHECK 8: E-MAIL (aanbevolen) ---
                    email_match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', volledige_tekst)
                    if email_match:
                        st.success(f"✅ **E-mailadres gevonden:** {email_match.group(0)}")
                    else:
                        st.info("ℹ️ **Geen e-mailadres gevonden** (aanbevolen maar niet verplicht)")

                    # --- CHECK 9: ONLINE ELEMENTEN ---
                    st.markdown("##### 🌐 Online Elementen")
                    
                    if "zoom" in txt_lower or "meet" in txt_lower or "teams" in txt_lower:
                        st.success("✅ **Online link gevonden**")
                        if "id" in txt_lower or "wachtwoord" in txt_lower:
                            st.success("✅ **Meeting ID/wachtwoord gevonden**")
                        else:
                            st.info("ℹ️ **Geen meeting ID of wachtwoord gevonden**")
                    else:
                        st.info("ℹ️ **Geen online link gevonden** (niet verplicht)")

                except Exception as ocr_error:
                    st.error(f"❌ Fout tijdens OCR-analyse: {ocr_error}")

        # ---- LOGO CHECK (VERBETERD) ----
        st.markdown("### 🖼️ CA-Logo Controle")
        
        # Methode 1: Template matching
        if logos:
            with st.spinner("Zoeken naar CA-logo..."):
                try:
                    for logo in logos:
                        # Probeer meerdere thresholds
                        for threshold in [0.55, 0.60, 0.65]:
                            res = cv2.matchTemplate(img_gray, logo, cv2.TM_CCOEFF_NORMED)
                            loc = np.where(res >= threshold)
                            
                            if len(loc[0]) > 0:
                                h, w = logo.shape
                                pt = (loc[1][0], loc[0][0])
                                cv2.rectangle(img_canvas, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), 4)
                                logo_score += 2
                                logo_gevonden = True
                                break
                        if logo_gevonden:
                            break
                except Exception as logo_err:
                    st.error(f"Fout bij logo-scan: {logo_err}")
        
        # Methode 2: Logo-teksten herkennen
        if volledige_tekst:
            logo_teksten = ["hoop", "vertrouwen", "moed", "cocaine anonymous"]
            logo_tekst_score = 0
            
            for woord in logo_teksten:
                if woord in txt_lower:
                    logo_tekst_score += 1
            
            if logo_tekst_score >= 2:
                logo_score += 1
                if logo_tekst_score >= 3:
                    logo_score += 1
        
        # Eindbeoordeling logo
        if logo_score >= 3:
            logo_gevonden = True
            st.success(f"✅ **CA-logo aanwezig** (score: {logo_score}/5)")
        elif logo_score >= 2:
            logo_gevonden = True
            st.warning(f"⚠️ **CA-logo waarschijnlijk aanwezig** (score: {logo_score}/5)")
        else:
            st.warning(f"⚠️ **Geen officieel CA-logo herkend** (score: {logo_score}/5)")

        # --- SAMENVATTEND RAPPORT (NU ONDERAAN) ---
        st.markdown("---")
        st.markdown("#### 📊 Samenvattend Rapport")
        
        # Bepaal of kritieke checks zijn geslaagd
        kritiek_geslaagd = logo_gevonden and (traditie_fuzzy_score >= 70 or zesde_traditie_score >= 3)
        
        if kritiek_geslaagd:
            st.success("✅ **Kritieke controles geslaagd:** Logo en 6e traditie aanwezig")
        else:
            if not logo_gevonden:
                st.error("❌ **Kritieke check mislukt:** CA-logo niet gevonden")
            if traditie_fuzzy_score < 70 and zesde_traditie_score < 3:
                st.error("❌ **Kritieke check mislukt:** 6e traditie niet gevonden")
        
        # Detailrapport
        with st.expander("📋 Bekijk gedetailleerd rapport"):
            st.markdown("**🔴 KRITIEKE CONTROLES**")
            st.write(f"{'✅' if logo_gevonden else '❌'} CA-logo (score: {logo_score}/5)")
            st.write(f"{'✅' if (traditie_fuzzy_score >= 70 or zesde_traditie_score >= 3) else '⚠️' if (traditie_fuzzy_score >= 50 or zesde_traditie_score >= 1) else '❌'} 6e traditie (fuzzy: {traditie_fuzzy_score:.0f}%, woorden: {zesde_traditie_score}/6)")
            
            st.markdown("**🏢 EVENEMENT**")
            # Hier zouden we de variabelen moeten opslaan tijdens de checks
            st.write("ℹ️ Details hierboven bekijken")
            
            st.markdown("**📞 CONTACT**")
            if telefoon_match:
                st.write(f"✅ Telefoon: {telefoon_match.group(0)}")
            else:
                st.write("ℹ️ Geen telefoonnummer")
            
            if email_match:
                st.write(f"✅ E-mail: {email_match.group(0)}")
            else:
                st.write("ℹ️ Geen e-mailadres")
            
            st.markdown("**🌐 ONLINE**")
            if "zoom" in txt_lower or "meet" in txt_lower:
                st.write("✅ Online link aanwezig")
            else:
                st.write("ℹ️ Geen online link")

    # RECHTERKOLOM: Het visuele voorbeeldscherm
    with col2:
        st.markdown("### 🖼️ Voorbeeldscherm (Visuele Matrix)")
        st.caption("🟢 Groen = Gevonden tekstvlakken | 🔵 Blauw = Gedetecteerde tijden of CA-Logo")
        
        # Toon de bewerkte afbeelding met alle getekende kaders
        st.image(img_canvas, use_column_width=True, caption="Flyer met live omlijning van de gedetecteerde matrix-elementen")
        
        if volledige_tekst:
            with st.expander("Bekijk volledige opgeschoonde tekst (ruw)"):
                st.write(volledige_tekst)
        
        # Toon ruwe OCR-output voor debugging
        if ruwe_regels:
            with st.expander("🔧 Ruwe OCR-output (debug)"):
                for i, regel in enumerate(ruwe_regels):
                    st.write(f"{i+1}. `{regel}`")

    # Toon de tijdregels die gevonden zijn voor debugging
    if tijd_regels:
        with st.sidebar:
            st.markdown("### ⏰ Gedetecteerde tijden")
            for i, tijd in enumerate(tijd_regels):
                st.write(f"{i+1}. `{tijd}`")
