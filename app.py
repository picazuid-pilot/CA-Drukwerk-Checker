"""
CA Drukwerk Checker v2
=======================
Controleert Nederlandstalig CA PI-drukwerk (flyers/posters) op:
  - Verplicht: gebruik van een officieel Nederlands CA-logo
  - Verplicht: de letterlijke 6de-Traditie-zin (met spelfouttolerantie)
  - Aanbevolen: "Georganiseerd door", adres/locatie/Zoomlink, datum & tijd
  - Waarschuwing: volledige namen (Traditie 12 - anonimiteit)
  - Print-gereedheid: CMYK + snijranden (alleen betrouwbaar te checken bij PDF)

Werkt volledig zonder externe API's (OCR + regex + fuzzy matching).
Optioneel kan een gratis/eigen OpenAI-compatibele API-sleutel worden
toegevoegd om de tekstcontrole te verfijnen (niet verplicht).
"""

import io
import os
import re
import json
import tempfile
from pathlib import Path
from difflib import SequenceMatcher

import numpy as np
import streamlit as st
from PIL import Image
import cv2

# ---- Optionele afhankelijkheden -------------------------------------------------
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


# =============================================================================
# Configuratie / constanten
# =============================================================================

st.set_page_config(page_title="CA Drukwerk Checker", page_icon="✅", layout="wide")

ASSETS_FOLDER = Path(__file__).parent / "assets"

REQUIRED_SENTENCE = (
    "In de geest van de 6de Traditie is C.A. niet verbonden aan kerken, "
    "sekten, politieke of hulpverlenende instanties."
)

BLEED_TOOL_URL = "https://bleed-cmyk-builderpy-ecaauj8zkjwrhhivxmilqq.streamlit.app/"

# Officiële contactgegevens van CA Holland. Pas dit aan als deze ooit wijzigen —
# de rest van de controle-logica hoeft dan niet aangepast te worden.
CORRECT_PHONE_DIGITS = "0610192770"          # 06 101 92770, alleen cijfers
CORRECT_PHONE_DISPLAY = "06 101 92770"
CORRECT_EMAIL = "info@ca-holland.nl"
CORRECT_WEBSITE_DOMAIN = "ca-holland.nl"

# OCR/typfout-gevoelige tekens die vaak verward worden met cijfers
_DIGIT_LOOKALIKES = {
    "o": "0", "O": "0",
    "i": "1", "I": "1", "l": "1", "L": "1",
    "s": "5", "S": "5",
    "b": "8", "B": "8",
}

# Formaten die we herkennen als "standaard papierformaat zonder bleed" (mm, staand+liggend)
STANDARD_SIZES_MM = [
    (105, 148), (148, 105),  # A6
    (148, 210), (210, 148),  # A5
    (210, 297), (297, 210),  # A4
    (297, 420), (420, 297),  # A3
]

# Woorden die nooit als (deel van) een persoonsnaam geteld mogen worden
NAME_STOPWORDS = {
    "januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
    "september", "oktober", "november", "december",
    "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag",
    "nederland", "belgie", "belgië", "cocaine", "anonymous", "anoniem", "traditie",
    "georganiseerd", "door", "adres", "locatie", "zoom", "meeting", "datum", "tijd",
    "regio", "zuid", "noord", "oost", "west", "flyer", "poster", "welkom", "iedereen",
    "open", "gesloten", "meeting", "bijeenkomst", "commissie", "comite", "comité",
    "public", "information", "hoop", "vertrouwen", "moed",
}


# =============================================================================
# Hulpfuncties: bestand inladen (afbeelding of PDF)
# =============================================================================

def load_uploaded_file(uploaded_file):
    """
    Laadt het geüploade bestand.
    Retourneert (pil_image_voor_analyse, is_pdf, pdf_bytes_of_None)
    """
    suffix = Path(uploaded_file.name).suffix.lower()
    raw_bytes = uploaded_file.getvalue()

    if suffix == ".pdf":
        if not PYMUPDF_AVAILABLE:
            return None, True, raw_bytes
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        page = doc[0]
        # Render op 300 DPI voor scherpe OCR/logo-detectie
        zoom = 300 / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return img, True, raw_bytes
    else:
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        return img, False, None


# =============================================================================
# Logo-detectie (shape-based, kleur- en achtergrond-onafhankelijk)
# =============================================================================

def _prep_edges(gray_array, blur_ksize=3):
    """Canny edge-map, licht geblurd zodat kleine drukwerkartefacten geen ruis geven."""
    blurred = cv2.GaussianBlur(gray_array, (blur_ksize, blur_ksize), 0)
    edges = cv2.Canny(blurred, 50, 150)
    return edges


def _soft_edges(edges, k=13):
    """
    Vervaagt een binaire randenkaart tot een vloeiende 'randkans'-kaart.
    Cruciaal voor betrouwbare matching: pixel-exacte randcorrelatie faalt
    al bij een verschuiving van een paar pixels (JPEG-compressie, lichte
    schaalafwijking), wat bij fijne details zoals ringtekst al snel
    voorkomt. Door te vervagen wordt matching tolerant voor zulke kleine
    afwijkingen zonder de algehele vorm te verliezen.
    """
    return cv2.GaussianBlur(edges.astype(np.float32), (k, k), 0)


def load_logo_templates(assets_folder: Path):
    """
    Laadt alle referentielogo's uit de assets-map en zet ze om naar een
    edge-template (vierkant uitgesneden rond de alpha- of contour-inhoud),
    zodat kleur en achtergrond niet uitmaken voor de vergelijking.
    """
    templates = []
    if not assets_folder.exists():
        return templates

    for file in sorted(assets_folder.glob("*.png")):
        try:
            pil_img = Image.open(file)
            has_alpha = pil_img.mode == "RGBA"
            if has_alpha:
                arr = np.array(pil_img.convert("RGBA"))
                alpha = arr[:, :, 3]
                # Gebruik alpha-masker om het logo strak uit te snijden
                ys, xs = np.where(alpha > 10)
                if len(xs) == 0:
                    continue
                x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
                gray = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2GRAY)
                gray_crop = gray[y0:y1, x0:x1]
                alpha_crop = alpha[y0:y1, x0:x1]
                # Waar geen alpha is: neutraliseren met een MIDDENGRIJS (niet wit!).
                # Bij een witte outline op transparante achtergrond zou een witte
                # opvulkleur de outline volledig laten verdwijnen (geen contrast =
                # geen randen te detecteren). Middengrijs geeft altijd contrast,
                # ongeacht of de outline wit of zwart is.
                gray_crop = np.where(alpha_crop > 10, gray_crop, 128).astype(np.uint8)
            else:
                arr = np.array(pil_img.convert("RGB"))
                gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                gray_crop = gray

            edges = _prep_edges(gray_crop)
            soft = _soft_edges(edges)
            templates.append({
                "name": file.stem, "edges": edges, "soft": soft, "shape": edges.shape,
            })
        except Exception:
            continue

    return templates


def _score_candidate_region(work_gray, cx, cy, r, resized_templates, pad=1.08, fixed_size=220):
    """
    Snijdt een vierkante regio rond een kandidaat-cirkel (met kleine marge),
    schaalt die naar een vaste werkgrootte (voor consistente en snelle
    matching, ongeacht hoe groot de gedetecteerde cirkel op de pagina is),
    en vergelijkt de vervaagde randenkaart tegen alle referentietemplates
    (al vooraf op dezelfde vaste grootte geschaald, zie find_logo_in_page).
    Retourneert (beste_score, beste_naam) voor deze ene kandidaat-locatie.
    """
    h, w = work_gray.shape
    half = int(r * pad)
    x0, x1 = max(0, int(cx - half)), min(w, int(cx + half))
    y0, y1 = max(0, int(cy - half)), min(h, int(cy + half))
    if x1 - x0 < 20 or y1 - y0 < 20:
        return -1.0, None

    region_gray = work_gray[y0:y1, x0:x1]
    if region_gray.shape[0] != fixed_size or region_gray.shape[1] != fixed_size:
        region_gray = cv2.resize(region_gray, (fixed_size, fixed_size), interpolation=cv2.INTER_AREA)

    region_edges = _prep_edges(region_gray)
    if np.count_nonzero(region_edges) < 30:
        return -1.0, None  # nagenoeg lege regio, niet de moeite van het scoren waard
    region_soft = _soft_edges(region_edges)

    best_score = -1.0
    best_name = None
    for name, resized_soft in resized_templates.items():
        try:
            result = cv2.matchTemplate(region_soft, resized_soft, cv2.TM_CCOEFF_NORMED)
        except cv2.error:
            continue
        score = float(result[0, 0]) if result.size == 1 else float(result.max())
        if score > best_score:
            best_score = score
            best_name = name

    return best_score, best_name


def find_logo_in_page(page_rgb_array, templates, match_threshold=0.20):
    """
    Detecteert een officieel CA-logo op de pagina.

    Strategie: alle 12 varianten zijn een cirkelvormig zegel, dus we
    gebruiken eerst een Hough-cirkeldetectie om kandidaat-locaties (positie
    én schaal) te vinden — veel preciezer dan een blinde multi-schaal-scan,
    en dat blijkt in de praktijk nodig: pixel-exacte randcorrelatie is
    gevoelig voor de kleinste afwijking, dus een goed gelokaliseerde
    kandidaat scoort aanzienlijk beter dan een net-niet-uitgelijnde.
    Als er geen cirkels gevonden worden (bv. bij een sterk vervormd of
    geroteerd logo), valt de functie terug op een blinde multi-schaal-scan.

    Retourneert (gevonden: bool, beste_naam, beste_score, bbox)
    """
    if not templates:
        return False, None, 0.0, None

    page_gray = cv2.cvtColor(page_rgb_array, cv2.COLOR_RGB2GRAY)
    page_h, page_w = page_gray.shape

    # Downscale voor snelheid; alle latere coördinaten rekenen we terug
    max_dim = 1200
    scale_factor = min(1.0, max_dim / max(page_h, page_w))
    work_gray = (
        cv2.resize(page_gray, (int(page_w * scale_factor), int(page_h * scale_factor)),
                   interpolation=cv2.INTER_AREA)
        if scale_factor < 1.0 else page_gray
    )
    work_h, work_w = work_gray.shape

    best_score = -1.0
    best_name = None
    best_bbox = None

    # --- Strategie 1: Hough-cirkeldetectie als precieze kandidaat-locator ---
    circle_input = cv2.medianBlur(work_gray, 5)
    circles = cv2.HoughCircles(
        circle_input, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=int(work_w * 0.06),
        param1=80, param2=35,
        minRadius=int(work_w * 0.015), maxRadius=int(work_w * 0.45),
    )

    if circles is not None:
        # Hough retourneert kandidaten al gesorteerd op accumulator-sterkte
        # (sterkste/meest cirkelvormige eerst). Op een drukke foto-achtergrond
        # kunnen er honderden kandidaten ontstaan (haar, plooien, etc.); de
        # echte logo-cirkel staat vrijwel altijd al binnen de eerste tientallen,
        # dus we beperken ons tot de sterkste kandidaten voor de snelheid.
        MAX_CANDIDATES = 50
        candidates = circles[0][:MAX_CANDIDATES]

        # Templates één keer vooraf schalen naar de vaste werkgrootte
        # i.p.v. dit per kandidaat-cirkel te herhalen.
        FIXED_SIZE = 220
        resized_templates = {
            tpl["name"]: cv2.resize(tpl["soft"], (FIXED_SIZE, FIXED_SIZE)) for tpl in templates
        }
        for cx, cy, r in candidates:
            score, name = _score_candidate_region(work_gray, cx, cy, r, resized_templates, fixed_size=FIXED_SIZE)
            if score > best_score:
                best_score = score
                best_name = name
                best_bbox = (
                    int((cx - r) / scale_factor), int((cy - r) / scale_factor),
                    int(2 * r / scale_factor), int(2 * r / scale_factor),
                )

    # --- Strategie 2 (terugval): blinde multi-schaal-scan ---
    # Alleen nodig als Hough niets bruikbaars vond, of als extra dekking voor
    # logo's die (door vervorming/rotatie) niet als nette cirkel herkend worden.
    if best_score < match_threshold:
        work_edges = _prep_edges(work_gray)
        work_soft = _soft_edges(work_edges)
        scales = np.linspace(0.04, 0.6, 18)

        for tpl in templates:
            t_h, t_w = tpl["shape"]
            aspect = t_h / t_w
            for rel_w in scales:
                target_w = max(20, int(work_w * rel_w))
                target_h = max(20, int(target_w * aspect))
                if target_h >= work_h or target_w >= work_w:
                    continue
                resized_tpl = cv2.resize(tpl["soft"], (target_w, target_h))
                try:
                    result = cv2.matchTemplate(work_soft, resized_tpl, cv2.TM_CCOEFF_NORMED)
                except cv2.error:
                    continue
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                ox, oy = max_loc
                patch_edges = _prep_edges(work_gray[oy:oy + target_h, ox:ox + target_w])
                if np.count_nonzero(patch_edges) < 30:
                    continue  # (bijna) lege regio: geen betrouwbare match

                if max_val > best_score:
                    best_score = max_val
                    best_name = tpl["name"]
                    best_bbox = (
                        int(ox / scale_factor), int(oy / scale_factor),
                        int(target_w / scale_factor), int(target_h / scale_factor),
                    )

    found = best_score >= match_threshold
    return found, best_name, float(best_score), best_bbox


# =============================================================================
# OCR
# =============================================================================

def extract_text(pil_image: Image.Image) -> str:
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        return pytesseract.image_to_string(pil_image, lang="nld+eng")
    except pytesseract.TesseractError:
        try:
            return pytesseract.image_to_string(pil_image, lang="eng")
        except Exception:
            return ""
    except Exception:
        return ""


def normalize_text(text: str) -> str:
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# =============================================================================
# Tekstcontroles
# =============================================================================

def _tokenize(text: str):
    return re.findall(r"\S+", text)


# Bekende, geaccepteerde schrijfvarianten die NIET als afwijking gemeld mogen
# worden (uitbreidbaar). Sleutel = variant (na het strippen van 1 trailing
# leesteken en lowercasen), waarde = canonieke vorm waarnaar genormaliseerd
# wordt. Echte spelfouten die hier niet in staan blijven gewoon gevlagd.
WORD_VARIANT_MAP = {
    "6e": "6de",       # "6de Traditie" mag ook als "6e traditie" geschreven worden
    "ca": "c.a",       # "C.A." mag ook zonder punten als "CA" geschreven worden
}


def _norm_word(w: str) -> str:
    """
    Normaliseert een woord voor vergelijking: lowercase, één trailing
    leesteken (punt/komma/puntkomma/dubbele punt) genegeerd — verschillen
    in eindpunctuatie zijn geen taalfout — en bekende schrijfvarianten
    (zie WORD_VARIANT_MAP) omgezet naar hun canonieke vorm.
    """
    core = w.lower()
    if core and core[-1] in ".,;:":
        core = core[:-1]
    return WORD_VARIANT_MAP.get(core, core)


def check_required_sentence(full_text: str, required=REQUIRED_SENTENCE):
    """
    Zoekt de verplichte zin woord-voor-woord in de OCR-tekst en rapporteert
    per verschillend woord wat er gevonden werd t.o.v. wat er had moeten staan.
    Dit voorkomt dat losse spelfouten wegvallen in een score over de hele
    string (bij lange zinnen drukt correcte tekst rondom een fout de score
    anders kunstmatig omhoog).
    """
    text_words = _tokenize(normalize_text(full_text))
    req_words = _tokenize(required)
    req_len = len(req_words)

    if not text_words:
        return {"status": "not_found", "score": 0.0, "snippet": None, "differences": []}

    best_match_count = -1
    best_window = None

    for size in [req_len - 2, req_len - 1, req_len, req_len + 1, req_len + 2, req_len + 3]:
        if size <= 0:
            continue
        for i in range(0, max(1, len(text_words) - size + 1)):
            window = text_words[i:i + size]
            sm = SequenceMatcher(
                None,
                [_norm_word(w) for w in window],
                [_norm_word(w) for w in req_words],
            )
            match_count = sum(block.size for block in sm.get_matching_blocks())
            if match_count > best_match_count:
                best_match_count = match_count
                best_window = window

    if best_window is None or best_match_count < req_len * 0.4:
        return {"status": "not_found", "score": 0.0, "snippet": None, "differences": []}

    sm = SequenceMatcher(
        None,
        [_norm_word(w) for w in best_window],
        [_norm_word(w) for w in req_words],
    )
    differences = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        differences.append({
            "type": tag,
            "gevonden": " ".join(best_window[i1:i2]) if i2 > i1 else "(ontbreekt)",
            "verwacht": " ".join(req_words[j1:j2]) if j2 > j1 else "(overbodig)",
        })

    score = round(best_match_count / req_len, 3)

    if not differences:
        status = "ok"
    elif score >= 0.5:
        status = "likely_typo"
    else:
        status = "not_found"

    return {
        "status": status,
        "score": score,
        "snippet": " ".join(best_window),
        "differences": differences,
    }


def check_organized_by(full_text: str) -> bool:
    return bool(re.search(r"georganiseerd\s+door|organisati[e]?\s*:", full_text, re.IGNORECASE))


def check_location(full_text: str) -> dict:
    has_postcode = bool(re.search(r"\b\d{4}\s?[A-Za-z]{2}\b", full_text))
    has_zoom = bool(re.search(r"zoom\.us|meet\.google|teams\.microsoft|jitsi", full_text, re.IGNORECASE))
    has_keyword = bool(re.search(r"\b(adres|locatie|zaal|straat|plein|laan)\b", full_text, re.IGNORECASE))
    found = has_postcode or has_zoom or has_keyword
    return {"found": found, "postcode": has_postcode, "zoomlink": has_zoom, "keyword": has_keyword}


def check_date_time(full_text: str) -> dict:
    weekdays = r"maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag"
    months = (r"januari|februari|maart|april|mei|juni|juli|augustus|"
              r"september|oktober|november|december")
    has_weekday = bool(re.search(weekdays, full_text, re.IGNORECASE))
    has_month = bool(re.search(months, full_text, re.IGNORECASE))
    has_numeric_date = bool(re.search(r"\b\d{1,2}[\/\-.]\d{1,2}([\/\-.]\d{2,4})?\b", full_text))
    has_time = bool(re.search(r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s*uur\b", full_text, re.IGNORECASE))
    found_date = has_weekday or has_month or has_numeric_date
    return {
        "found_date": found_date, "found_time": has_time,
        "weekday": has_weekday, "month": has_month, "numeric": has_numeric_date,
    }


def check_full_names(full_text: str):
    """
    Heuristische detectie van volledige namen (Voornaam Achternaam).
    'Voornaam A.' (initiaal) wordt NIET gevlagd, conform de gangbare
    beknopte, anonimiteit-respecterende schrijfwijze.
    Retourneert lijst met gevonden kandidaten (kan false positives bevatten).
    """
    # Patroon: Hoofdletterwoord + spatie + Hoofdletterwoord (geen enkele letter+punt)
    pattern = r"\b([A-Z][a-zà-ÿ]{2,})\s+([A-Z][a-zà-ÿ]{2,})\b"
    candidates = []
    for match in re.finditer(pattern, full_text):
        first, last = match.group(1), match.group(2)
        if first.lower() in NAME_STOPWORDS or last.lower() in NAME_STOPWORDS:
            continue
        # Uitsluiten: begin van een zin waar het tweede woord ook een gewoon zelfstandig
        # naamwoord kan zijn is niet volledig te filteren met regex alleen -> als kandidaat tonen,
        # gebruiker beoordeelt zelf mee.
        candidates.append(f"{first} {last}")
    # Dedupliceren met behoud van volgorde
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


# =============================================================================
# Contactgegevens: hulplijn, e-mail, website
# =============================================================================
# Filosofie: deze gegevens zijn niet verplicht aanwezig, maar ALS ze aanwezig
# zijn moeten ze correct zijn. Opmaakvarianten (spaties/streepjes/hoofdletters/
# met of zonder www./https://) zijn toegestaan; een verkeerd cijfer, een typfout
# in het domein, of een andere aanbieder is dat niet.

def _normalize_phone_candidate(raw: str) -> str:
    """Vervangt cijfer-lookalike letters (O/o, l/I, S, B) door hun cijfer en
    strip alle overige tekens (spaties, streepjes, punten) tot een pure
    cijferreeks."""
    mapped = "".join(_DIGIT_LOOKALIKES.get(ch, ch) for ch in raw)
    return re.sub(r"[^\d]", "", mapped)


def check_helpline(full_text: str) -> dict:
    # De check is gekoppeld aan het label 'hulplijn' zelf (tolerant voor kleine
    # schrijffouten zoals 'hulp lijn'); zonder dat label wordt dit veld als
    # niet-aanwezig beschouwd (conform "wanneer de hulplijn erop staat").
    label_match = re.search(r"hulp\s*lijn\s*[:\-]?\s*", full_text, re.IGNORECASE)
    if label_match is None:
        return {"present": False, "correct": None, "found": None}

    # Beperk het zoekgebied tot de rest van DEZELFDE regel als het label, zodat
    # een regeleinde + het begin van het volgende veld (bv. 'info@...') niet
    # per ongeluk wordt meegelezen als onderdeel van het nummer.
    rest_of_line = full_text[label_match.end():].split("\n", 1)[0]

    candidate_match = re.search(
        r"[0-9OoIlLiSsBb][0-9OoIlLiSsBb \-.]{7,16}[0-9OoIlLiSsBb]", rest_of_line
    )

    if candidate_match is None:
        # Label 'hulplijn' staat er wel, maar er volgt geen herkenbaar nummer
        return {"present": True, "correct": False, "found": None}

    raw_found = candidate_match.group(0).strip()
    normalized = _normalize_phone_candidate(raw_found)
    correct = normalized == CORRECT_PHONE_DIGITS

    return {"present": True, "correct": correct, "found": raw_found}


def check_email(full_text: str) -> dict:
    match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", full_text)
    if not match:
        return {"present": False, "correct": None, "found": None}

    raw_found = match.group(0)
    normalized = raw_found.strip().lower().rstrip(".,;:")
    correct = normalized == CORRECT_EMAIL

    return {"present": True, "correct": correct, "found": raw_found}


def check_website(full_text: str) -> dict:
    # Alleen tellen als het duidelijk een URL/website-vermelding is (begint met
    # www. of http(s)://), om te voorkomen dat het domein van het e-mailadres
    # dubbel als 'website' wordt geteld. Sluithaakjes/aanhalingstekens (bv. uit
    # een markdown-link) worden expliciet uitgesloten van de match, anders
    # wordt de hele link inclusief opmaak als 1 token ingeslikt.
    match = re.search(r"(https?://[^\s\)\]\}\"'<>]+|www\.[^\s\)\]\}\"'<>]+)", full_text, re.IGNORECASE)
    if not match:
        return {"present": False, "correct": None, "found": None}

    raw_found = match.group(0)
    domain = raw_found.lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.split("/")[0]
    domain = domain.rstrip(".,;:")
    correct = domain == CORRECT_WEBSITE_DOMAIN

    return {"present": True, "correct": correct, "found": raw_found}


# =============================================================================
# Print-gereedheid (CMYK + bleed) — alleen betrouwbaar voor PDF
# =============================================================================

def check_print_ready_pdf(pdf_bytes: bytes) -> dict:
    if not PYMUPDF_AVAILABLE:
        return {
            "checked": False,
            "message": "PyMuPDF is niet geïnstalleerd; print-gereedheid kan niet worden gecontroleerd.",
        }

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]

        # --- CMYK check: kijk naar kleurruimte van ingebedde afbeeldingen ---
        cmyk_found = False
        rgb_found = False
        images = page.get_images(full=True)
        for img_info in images:
            xref = img_info[0]
            base = doc.extract_image(xref)
            colorspace = base.get("colorspace", None)
            cs_name = ""
            try:
                cs_name = str(fitz.Colorspace(colorspace).name) if colorspace else ""
            except Exception:
                cs_name = base.get("cs-name", "") or ""
            if "CMYK" in cs_name.upper():
                cmyk_found = True
            elif "RGB" in cs_name.upper() or "GRAY" in cs_name.upper():
                rgb_found = True

        # --- Bleed check: vergelijk mediabox met bekende standaardformaten ---
        rect = page.rect  # in punten (1pt = 1/72 inch)
        width_mm = rect.width / 72 * 25.4
        height_mm = rect.height / 72 * 25.4

        is_standard_size = any(
            abs(width_mm - w) < 2 and abs(height_mm - h) < 2
            for w, h in STANDARD_SIZES_MM
        )
        has_bleed = not is_standard_size  # groter dan standaardformaat => waarschijnlijk bleed toegevoegd

        doc.close()

        return {
            "checked": True,
            "cmyk_found": cmyk_found,
            "rgb_found": rgb_found,
            "has_bleed": has_bleed,
            "width_mm": round(width_mm, 1),
            "height_mm": round(height_mm, 1),
            "no_embedded_images": len(images) == 0,
        }
    except Exception as e:
        return {"checked": False, "message": f"Kon PDF niet analyseren: {e}"}


# =============================================================================
# Optionele AI-verfijning (OpenAI-compatibel; werkt o.a. met gratis Groq-sleutels)
# =============================================================================

def call_ai_verification(api_key, base_url, model, ocr_text):
    if not REQUESTS_AVAILABLE or not api_key:
        return None

    system_prompt = (
        "Je bent een strikte Nederlandse taalcontroleur voor CA (Cocaine Anonymous) "
        "drukwerk. Je krijgt ruwe OCR-tekst van een flyer. Beoordeel: "
        "1) staat de volgende zin er correct op (kleine OCR-fouten negeren, "
        "echte spelfouten wel melden): \"" + REQUIRED_SENTENCE + "\" "
        "2) staat er een organisator vermeld? 3) staat er een adres/locatie/Zoomlink? "
        "4) staat er een datum en tijd? 5) staan er volledige persoonsnamen "
        "(voornaam+achternaam voluit, GEEN 'Voornaam A.'-vorm) die de anonimiteit "
        "kunnen schenden? Antwoord ALLEEN als JSON met keys: "
        "sentence_ok (bool), sentence_note (str), organized_by (bool), "
        "location (bool), date_time (bool), full_names (lijst van strings)."
    )

    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": ocr_text[:6000]},
                ],
                "temperature": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```json|```$", "", content.strip(), flags=re.MULTILINE).strip()
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Logo-templates: GEEN Streamlit-cache meer.
# =============================================================================
# Eerdere versies gebruikten @st.cache_resource, maar dat veroorzaakte een# hardnekkige KeyError: cache_resource bust alleen op wijzigingen in de
# broncode van de gedecoreerde functie zelf — niet op wijzigingen in de
# hulpfunctie load_logo_templates die eronder ligt. Na een deploy waarbij
# load_logo_templates nieuwe keys kreeg (bv. "soft"), bleef de oude gecachte
# lijst met dicts in het geheugen van de container hangen, waardoor de nieuwe
# code op een ontbrekende key crashte.
#
# Het laden van 12 kleine PNG's + Canny kost ~50 ms — verwaarloosbaar naast de
# OCR die er daarna toch over de pagina heen gaat. Betrouwbaarheid > micro-
# optimalisatie, dus we laden de templates elke run opnieuw in.
_logo_templates_cache = None


def get_logo_templates(force_reload: bool = False):
    global _logo_templates_cache
    if force_reload or _logo_templates_cache is None:
        _logo_templates_cache = load_logo_templates(ASSETS_FOLDER)
    return _logo_templates_cache


# =============================================================================
# Volledige analyse
# =============================================================================

def analyze_file(uploaded_file, ai_config=None):
    results = {"errors": []}

    page_img, is_pdf, pdf_bytes = load_uploaded_file(uploaded_file)

    if page_img is None:
        results["errors"].append(
            "Kon PDF niet inlezen: PyMuPDF ontbreekt op de server. Voeg 'pymupdf' toe aan requirements.txt."
        )
        return results

    page_array = np.array(page_img)

    # --- 1. Logo-detectie ---
    templates = get_logo_templates()
    if not templates:
        results["logo"] = {"found": False, "score": 0.0, "name": None,
                            "note": "Geen referentielogo's gevonden in de 'assets' map."}
    else:
        found, name, score, bbox = find_logo_in_page(page_array, templates)
        results["logo"] = {"found": found, "score": round(score, 3), "name": name, "bbox": bbox}

    # --- 2. OCR ---
    ocr_text = extract_text(page_img)
    results["ocr_text"] = ocr_text
    results["ocr_available"] = TESSERACT_AVAILABLE

    # --- 3. Tekstcontroles ---
    results["sentence"] = check_required_sentence(ocr_text)
    results["organized_by"] = check_organized_by(ocr_text)
    results["location"] = check_location(ocr_text)
    results["date_time"] = check_date_time(ocr_text)
    results["full_names"] = check_full_names(ocr_text)
    results["helpline"] = check_helpline(ocr_text)
    results["email"] = check_email(ocr_text)
    results["website"] = check_website(ocr_text)

    # --- 4. Optionele AI-verfijning ---
    if ai_config and ai_config.get("api_key") and ocr_text.strip():
        ai_result = call_ai_verification(
            ai_config["api_key"], ai_config["base_url"], ai_config["model"], ocr_text
        )
        results["ai_result"] = ai_result

    # --- 5. Print-gereedheid ---
    if is_pdf and pdf_bytes:
        results["print_ready"] = check_print_ready_pdf(pdf_bytes)
        results["is_pdf"] = True
    else:
        results["print_ready"] = {
            "checked": False,
            "message": (
                "Dit is geen PDF-bestand. CMYK-kleurruimte en snijranden kunnen alleen "
                "betrouwbaar worden gecontroleerd in een PDF (JPG/PNG zijn altijd RGB). "
                "Upload het definitieve PDF-drukbestand, of maak er eerst een aan met de "
                f"[bleed & CMYK-tool]({BLEED_TOOL_URL})."
            ),
        }
        results["is_pdf"] = False

    # --- Eindoordeel (verplichte eisen) ---
    contact_details_wrong = any(
        results[key]["present"] and not results[key]["correct"]
        for key in ("helpline", "email", "website")
    )
    results["approved"] = (
        results["logo"]["found"]
        and results["sentence"]["status"] == "ok"
        and not contact_details_wrong
    )

    return results


# =============================================================================
# UI
# =============================================================================

def render_check_line(icon_ok, label, ok, detail=""):
    icon = "✅" if ok else "❌"
    st.markdown(f"{icon} **{label}**" + (f" — {detail}" if detail else ""))


def _score_color(percent: int) -> str:
    if percent < 40:
        return "#e03131"   # rood
    elif percent < 75:
        return "#f08c00"   # oranje
    else:
        return "#2f9e44"   # groen


def render_score_circle(label: str, percent: int, detail: str = ""):
    """Toont een stoplicht-achtige scorecirkel (rood/oranje/groen) met het
    percentage erin, gevolgd door een label en optionele detailtekst."""
    percent = max(0, min(100, int(round(percent))))
    color = _score_color(percent)
    detail_html = f'<div style="font-size:13px; opacity:0.75; margin-top:2px;">{detail}</div>' if detail else ""
    html = f"""
    <div style="display:flex; align-items:center; gap:14px; margin:10px 0;">
      <div style="
          width:54px; height:54px; min-width:54px; border-radius:50%;
          background:{color}; color:white; font-weight:700;
          display:flex; align-items:center; justify-content:center;
          font-size:14px;">
        {percent}%
      </div>
      <div>
        <div style="font-weight:600;">{label}</div>
        {detail_html}
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _logo_score_to_percent(raw_score: float, threshold: float = 0.20, ceiling: float = 0.45) -> int:
    """
    Herschaalt de ruwe logo-matchingscore naar een intuïtief percentage.

    De ruwe score komt uit randcorrelatie op een sterk gecomprimeerd bereik
    (zelfs een perfect uitgelijnde, echte match haalt door JPEG-compressie en
    fijne details meestal maar ~0.25-0.40, tegenover ~0.03-0.15 voor iets dat
    duidelijk geen logo is) — een gebruiker heeft niets aan dat rauwe getal.
    Daarom wordt alles ONDER de detectiedrempel afgebeeld op 0-50% (rood/
    oranje) en alles ER BOVEN op 50-100% (oranje/groen), zodat de kleur
    van de cirkel altijd overeenkomt met de ✅/❌-uitslag.
    """
    if raw_score <= 0:
        return 0
    if raw_score < threshold:
        return int(round(50 * (raw_score / threshold)))
    if raw_score >= ceiling:
        return 100
    return int(round(50 + 50 * (raw_score - threshold) / (ceiling - threshold)))


def main():
    st.title("🖼️ CA Drukwerk Checker")
    st.caption(
        "Controleert Nederlandstalige CA-flyers, posters en ander drukwerk op de "
        "vereisten voor goedkeuring door de PI-commissie."
    )

    if not TESSERACT_AVAILABLE:
        st.warning(
            "⚠️ Tesseract OCR is niet beschikbaar op deze server. Tekstcontroles "
            "(6de-Traditie-zin, organisator, locatie, datum/tijd, namen) kunnen niet "
            "worden uitgevoerd totdat dit is geïnstalleerd. Zie README voor installatie-instructies."
        )
    if not PYMUPDF_AVAILABLE:
        st.info("ℹ️ PyMuPDF ontbreekt — PDF-ondersteuning en print-gereedheidscontrole zijn uitgeschakeld.")

    with st.sidebar:
        st.header("⚙️ Instellingen")
        st.markdown("**Referentielogo's:**")
        templates = get_logo_templates()
        if templates:
            st.success(f"{len(templates)} officiële logo-varianten geladen")
            with st.expander("Toon geladen varianten"):
                for t in templates:
                    st.write(f"• {t['name']}")
        else:
            st.error("Geen logo's gevonden in de 'assets' map")

        if st.button("🔄 Logo's opnieuw inladen"):
            get_logo_templates(force_reload=True)
            st.success("Logo's opnieuw ingeladen.")

        st.markdown("---")
        st.markdown("**Optionele AI-verfijning**")
        st.caption(
            "Niet verplicht. Met een gratis of eigen OpenAI-compatibele API-sleutel "
            "(bv. Groq) worden de tekstcontroles extra verfijnd. Zonder sleutel werkt "
            "alles puur op OCR + regels."
        )
        use_ai = st.checkbox("AI-verfijning gebruiken", value=False)
        ai_config = None
        if use_ai:
            api_key = st.text_input("API-sleutel", type="password")
            base_url = st.text_input("API base URL", value="https://api.groq.com/openai/v1")
            model = st.text_input("Model", value="llama-3.1-8b-instant")
            if api_key:
                ai_config = {"api_key": api_key, "base_url": base_url, "model": model}

        st.markdown("---")
        st.markdown("### 📝 Eisen voor goedkeuring")
        st.markdown(
            "**Verplicht:**\n"
            "- ✅ Officieel Nederlands CA-logo\n"
            "- ✅ 6de-Traditie-zin (correct)\n"
            "- ✅ Correcte hulplijn/e-mail/website, *indien vermeld*\n\n"
            "**Aanbevolen (indien van toepassing):**\n"
            "- Georganiseerd door\n"
            "- Adres/locatie of Zoomlink\n"
            "- Datum en tijd\n\n"
            "**Let op (Traditie 12):**\n"
            "- Geen volledige namen — gebruik voornaam + eerste letter achternaam"
        )
        st.markdown("---")
        st.markdown(f"**Nog niet printklaar?** Gebruik de [bleed & CMYK-tool]({BLEED_TOOL_URL}).")

    uploaded_file = st.file_uploader(
        "Upload een flyer, poster of ander drukwerk",
        type=["png", "jpg", "jpeg", "pdf"],
        help="PDF wordt aangeraden voor een betrouwbare CMYK/snijrand-check.",
    )

    if uploaded_file is None:
        return

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📤 Geüpload bestand")
        if uploaded_file.name.lower().endswith(".pdf"):
            st.info(f"PDF: {uploaded_file.name}")
        else:
            st.image(Image.open(uploaded_file), use_container_width=True)
        uploaded_file.seek(0)

    with st.spinner("🔍 Analyseren..."):
        results = analyze_file(uploaded_file, ai_config)

    with col2:
        st.subheader("📊 Resultaat")

        if results.get("errors"):
            for e in results["errors"]:
                st.error(e)
            return

        if results["approved"]:
            st.success("✅ Voldoet aan de verplichte eisen voor goedkeuring")
        else:
            st.error("❌ Voldoet NIET aan alle verplichte eisen")

        st.markdown("#### Verplichte controles")

        logo = results["logo"]
        logo_percent = _logo_score_to_percent(logo["score"])
        logo_detail = (
            f"beste kandidaat: {logo['name']}" if logo["name"] else "geen enkele kandidaat gevonden"
        )
        render_score_circle("Officieel Nederlands CA-logo", logo_percent, logo_detail)
        if not logo["found"]:
            st.caption(
                "⚠️ Onder de detectiedrempel — geen betrouwbare match. Dit kan kloppen "
                "(geen logo aanwezig), maar controleer bij twijfel visueel of het logo "
                "er echt niet op staat, vooral bij een drukke achtergrond of lage resolutie."
            )

        sentence = results["sentence"]
        sentence_percent = int(round(sentence["score"] * 100))
        if sentence["status"] == "ok":
            render_score_circle("6de-Traditie-zin", sentence_percent, "correct aanwezig")
        elif sentence["status"] == "likely_typo":
            render_score_circle("6de-Traditie-zin", sentence_percent, "wijkt af op onderstaande punten")
            st.caption(
                "Let op: dit kunnen echte spelfouten op het drukwerk zijn, maar OCR "
                "leest soms ook correct gespelde tekst verkeerd (bv. bij een gestileerd "
                "lettertype). Controleer onderstaande afwijkingen handmatig tegen het origineel."
            )
            for d in sentence["differences"]:
                st.write(f"— gevonden: *\"{d['gevonden']}\"* → verwacht: *\"{d['verwacht']}\"*")
        else:
            render_score_circle("6de-Traditie-zin", sentence_percent, "niet gevonden")

        st.markdown("#### Aanbevolen controles")
        render_check_line("", "Georganiseerd door vermeld", results["organized_by"])
        loc = results["location"]
        render_check_line("", "Adres/locatie of Zoomlink vermeld", loc["found"])
        dt = results["date_time"]
        render_check_line("", "Datum vermeld", dt["found_date"])
        render_check_line("", "Tijd vermeld", dt["found_time"])

        st.markdown("#### Contactgegevens (indien aanwezig, moet correct zijn)")
        for key, label, expected in (
            ("helpline", "Hulplijn", CORRECT_PHONE_DISPLAY),
            ("email", "E-mailadres", CORRECT_EMAIL),
            ("website", "Website", CORRECT_WEBSITE_DOMAIN),
        ):
            info = results[key]
            if not info["present"]:
                st.write(f"⚪ {label} niet aangetroffen (niet verplicht)")
            elif info["correct"]:
                st.write(f"✅ {label} correct: \"{info['found']}\"")
            else:
                found_display = info["found"] or "(geen herkenbaar nummer/adres na het label)"
                st.error(f"❌ {label} onjuist — gevonden: \"{found_display}\", verwacht: \"{expected}\"")

        st.markdown("#### Anonimiteit (Traditie 12)")
        names = results["full_names"]
        if names:
            st.warning(
                "⚠️ Mogelijk volledige naam/namen gevonden: " + ", ".join(names) + ". "
                "Volgens Traditie 12 dienen we ons 12-stappen-werk anoniem te doen. "
                "Gebruik bij voorkeur alleen voornaam + eerste letter achternaam (bv. 'Jan V.')."
            )
        else:
            st.success("✅ Geen volledige namen gedetecteerd")

        st.markdown("#### Print-gereedheid")
        pr = results["print_ready"]
        if not pr.get("checked"):
            st.info(pr.get("message", "Kon niet worden gecontroleerd."))
        else:
            cmyk_ok = pr["cmyk_found"] and not pr["rgb_found"]
            render_check_line(
                "", "CMYK-kleurruimte", cmyk_ok,
                "geen ingebedde afbeeldingen gevonden" if pr.get("no_embedded_images") else
                ("gebruikt CMYK" if cmyk_ok else "bevat RGB-content — niet drukklaar"),
            )
            render_check_line(
                "", "Snijranden (bleed)", pr["has_bleed"],
                f"paginaformaat {pr['width_mm']}×{pr['height_mm']} mm",
            )
            if not cmyk_ok or not pr["has_bleed"]:
                st.info(f"Nog niet volledig printklaar? Gebruik de [bleed & CMYK-tool]({BLEED_TOOL_URL}).")

        if results.get("ai_result") and not results["ai_result"].get("error"):
            st.markdown("#### 🤖 AI-verfijning (aanvullend)")
            st.json(results["ai_result"])
        elif results.get("ai_result", {}).get("error"):
            st.caption(f"AI-verfijning mislukt: {results['ai_result']['error']}")

        with st.expander("📄 Ruwe OCR-tekst (debug)"):
            st.text(results.get("ocr_text", "(geen tekst)"))


if __name__ == "__main__":
    main()
