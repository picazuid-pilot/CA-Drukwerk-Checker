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
import hashlib
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
# Logo-verificatie (op basis van vervangbare officiële PDF-referenties)
# =============================================================================
# Dit vervangt de eerdere aanpak (vergelijken tegen 12 kleurvarianten als PNG).
# In plaats daarvan wordt het logo dat op de flyer staat rechtstreeks getoetst
# aan wat de merkrichtlijnen voorschrijven (zie de C.A. Brand Guide):
#   - het logo moet ONVERANDERD zijn: geen vervorming, geen andere verhoudingen
#   - de inkt (ring, letters, tekst) moet één egale kleur zijn — geen effecten
#   - alles BINNEN de buitenste cirkel dat geen inkt is (de 'gaten' tussen de
#     letters/ringen) moet ook één egale kleur zijn — er mag dus geen foto,
#     patroon of kleurverloop doorheen het logo schijnen
#   - alles BUITEN de buitenste cirkel is vrij (dat hoort niet bij het logo)
#
# De referentie komt uit twee (of vier) vervangbare PDF-bestanden in
# LOGO_REFERENCE_FOLDER: telkens een 'inner'- en 'outer'-TM/®-variant (het
# ™- of ®-teken staat resp. binnen of buiten de buitenste ring). Een andere
# taal/regio kan die PDF's simpelweg vervangen door hun eigen officiële
# logo-PDF's, met dezelfde bestandsnaamconventie:
#   <iets>_TM_inner.pdf / <iets>_TM_outer.pdf / <iets>_R_inner.pdf / <iets>_R_outer.pdf
# (matching is niet hoofdlettergevoelig en zoekt naar 'inner'/'outer' en
# 'tm'/'r' als losse woorden in de bestandsnaam)

LOGO_REFERENCE_FOLDER = Path(__file__).parent / "logo_reference"
LOGO_REFERENCE_DPI = 100          # resolutie waarop de PDF-referentie gerasterd wordt
LOGO_REFERENCE_FIXED_SIZE = 220   # vaste werkgrootte voor alle vergelijkingen (snelheid + consistentie)
LOGO_REFERENCE_PAD = 1.05         # kleine marge rond de buitenste cirkel bij het uitsnijden
# Ophogen bij elke structurele wijziging aan load_logo_reference() (bv. een
# nieuwe/andere sleutel in de teruggegeven dict). Dit dwingt de cache hieronder
# af te breken, zelfs als de PDF-bestanden zelf ongewijzigd blijven — dit is
# precies de klasse bug die eerder een KeyError veroorzaakte toen de cache
# een dict van een oudere codeversie bleef vasthouden.
LOGO_REFERENCE_SCHEMA_VERSION = 1

# Drempels, empirisch bepaald op echt fotografeerd/gescand drukwerk (zie
# projectnotities): dunne inktlijnen scoren door hun grotere rand-t.o.v.-
# oppervlakte-verhouding altijd lager op 'egale kleur' dan een vlak gat-gebied,
# dus de inkt-drempel ligt bewust lager dan de gat-drempel.
GAP_COLOR_DIST_THRESHOLD = 40
GAP_UNIFORM_MIN_FRACTION = 0.65
INK_COLOR_DIST_THRESHOLD = 40
INK_UNIFORM_MIN_FRACTION = 0.35
ASPECT_RATIO_TOLERANCE = 0.08     # max. 8% afwijking tussen breedte/hoogte-as toegestaan


def _prep_edges(gray_array, blur_ksize=3):
    """Canny edge-map, licht geblurd zodat kleine drukwerkartefacten geen ruis geven."""
    blurred = cv2.GaussianBlur(gray_array, (blur_ksize, blur_ksize), 0)
    return cv2.Canny(blurred, 50, 150)


def _soft_edges(edges, k=13):
    """Vervaagt een binaire randenkaart tot een vloeiende 'randkans'-kaart,
    zodat vormvergelijking tolerant is voor kleine misalignment (JPEG-
    compressie, lichte schaalafwijking) zonder de algehele vorm te verliezen."""
    return cv2.GaussianBlur(edges.astype(np.float32), (k, k), 0)


def _classify_reference_filename(stem: str):
    """Leidt (mark_type, position) af uit een referentie-bestandsnaam, bv.
    '..._Transparent_Background_-_Outer_TM' -> ('tm', 'outer')."""
    lower = stem.lower()
    if re.search(r"(^|[_\-\s])tm([_\-\s]|$)", lower) or lower.endswith("tm"):
        mark = "tm"
    elif re.search(r"(^|[_\-\s])r([_\-\s]|$)", lower) or lower.endswith("_r"):
        mark = "r"
    else:
        mark = "tm"
    position = "outer" if "outer" in lower else ("inner" if "inner" in lower else "onbekend")
    return mark, position


def _find_outer_ring(ink_mask_uint8):
    """Vindt de buitenste ring van het logo-ontwerp: de contour met de
    grootste 'minEnclosingCircle'-straal. Dit isoleert bewust de hoofdring
    van een eventueel los ™/®-teken dat buiten de ring kan staan (dat teken
    is fysiek klein, dus zijn eigen omcirkelende straal is nooit de grootste)."""
    contours, _ = cv2.findContours(ink_mask_uint8, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    best = max(contours, key=lambda c: cv2.minEnclosingCircle(c)[1])
    (cx, cy), r = cv2.minEnclosingCircle(best)
    return cx, cy, r


def load_logo_reference(path: Path, fixed_size=LOGO_REFERENCE_FIXED_SIZE, pad=LOGO_REFERENCE_PAD):
    """
    Rasterizeert een referentie-PDF (met transparantie) en bouwt daaruit:
      - ink_mask:   waar de inkt (ring/letters/tekst) staat, binnen de buitenste cirkel
      - gap_mask:   waar geen inkt is maar wel binnen de buitenste cirkel (moet 1 kleur zijn)
      - soft_edges: vervaagde randenkaart voor vormvergelijking
    Alles op een vaste, vierkante werkgrootte zodat elke kandidaat op de
    pagina er 1-op-1 mee te vergelijken is (zie score_logo_candidate).
    """
    doc = fitz.open(str(path))
    page = doc[0]
    zoom = LOGO_REFERENCE_DPI / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
    doc.close()

    alpha = arr[:, :, 3]
    ink_full = (alpha > 128).astype(np.uint8)

    ring = _find_outer_ring(ink_full)
    if ring is None:
        return None
    cx, cy, r = ring

    half = int(r * pad)
    x0, y0 = max(0, int(cx - half)), max(0, int(cy - half))
    x1, y1 = int(cx + half), int(cy + half)
    crop_ink = ink_full[y0:y1, x0:x1]
    if crop_ink.size == 0:
        return None

    yy, xx = np.mgrid[0:crop_ink.shape[0], 0:crop_ink.shape[1]]
    local_cx, local_cy = cx - x0, cy - y0
    dist = np.sqrt((xx - local_cx) ** 2 + (yy - local_cy) ** 2)
    circle_mask = dist <= r

    ink_mask = (crop_ink > 0) & circle_mask
    gap_mask = circle_mask & ~ink_mask

    ink_small = cv2.resize(ink_mask.astype(np.uint8), (fixed_size, fixed_size),
                            interpolation=cv2.INTER_NEAREST).astype(bool)
    gap_small = cv2.resize(gap_mask.astype(np.uint8), (fixed_size, fixed_size),
                            interpolation=cv2.INTER_NEAREST).astype(bool)
    circle_small = cv2.resize(circle_mask.astype(np.uint8), (fixed_size, fixed_size),
                               interpolation=cv2.INTER_NEAREST).astype(bool)

    edges = _prep_edges(cv2.resize(crop_ink * 255, (fixed_size, fixed_size)))
    soft = _soft_edges(edges)

    mark, position = _classify_reference_filename(path.stem)

    return {
        "name": path.stem, "mark": mark, "position": position,
        "ink_mask": ink_small, "gap_mask": gap_small, "circle_mask": circle_small,
        "soft_edges": soft,
    }


def load_logo_references(folder: Path):
    """
    Laadt alle referentie-PDF's uit de map (elk los te vervangen door de
    officiële logo-PDF van een andere taal/regio, zelfde bestandsnaamconventie).

    Elke referentie wordt gecachet op basis van de INHOUD van het PDF-bestand
    (md5-hash) plus een schemaversie — niet op basis van het bestandspad alleen.
    Dat betekent: vervang je het PDF-bestand door een andere taalversie, dan
    wordt die automatisch opnieuw ingeladen (de hash verandert), en verandert
    de interne structuur van load_logo_reference() ooit, dan breekt het ophogen
    van LOGO_REFERENCE_SCHEMA_VERSION de cache eveneens af. Dat voorkomt de
    eerdere klasse bug waarbij een gecachete, verouderde datastructuur bleef
    hangen na een codewijziging.
    """
    references = []
    if not folder.exists():
        return references
    for path in sorted(folder.glob("*.pdf")):
        try:
            file_hash = hashlib.md5(path.read_bytes()).hexdigest()
            ref = _load_logo_reference_cached(str(path), file_hash, LOGO_REFERENCE_SCHEMA_VERSION)
            if ref is not None:
                references.append(ref)
        except Exception:
            continue
    return references


@st.cache_resource(show_spinner=False)
def _load_logo_reference_cached(path_str: str, file_hash: str, schema_version: int):
    return load_logo_reference(Path(path_str))


def _color_uniformity(pixels_rgb, close_thresh):
    """
    Robuuste 'is dit in essentie 1 egale kleur'-metriek: gebruikt de MEDIAAN
    (niet het gemiddelde) als referentiekleur, omdat een minderheid rand-/
    antialiasing-pixels het gemiddelde anders scheeftrekt terwijl de mediaan
    gewoon de dominante kleur blijft weerspiegelen. Retourneert de fractie
    pixels die dicht bij die mediaankleur ligt, plus de mediaankleur zelf.
    """
    if len(pixels_rgb) < 20:
        return None, None
    median_color = np.median(pixels_rgb, axis=0)
    dist = np.linalg.norm(pixels_rgb.astype(float) - median_color, axis=1)
    fraction_close = float((dist < close_thresh).mean())
    return fraction_close, median_color.astype(int).tolist()


def _aspect_ratio_check(region_gray, tolerance=ASPECT_RATIO_TOLERANCE):
    """
    Controleert of de gevonden logo-regio niet is uitgerekt/vervormd: fit een
    ellips op de grootste rand-contour in de regio en vergelijk de lange en
    korte as. Een onvervormd (cirkelvormig) logo geeft een as-verhouding
    dicht bij 1.0; een horizontaal of verticaal uitgerekt logo wijkt af.
    """
    edges = _prep_edges(region_gray)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if len(c) >= 5]
    if not contours:
        return None, None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 500:
        # Val terug op de grootste beschikbare contour, ook al is die klein
        largest = max(contours, key=len)
    try:
        (_, _), (major, minor), _ = cv2.fitEllipse(largest)
    except cv2.error:
        return None, None
    if major == 0 or minor == 0:
        return None, None
    ratio = max(major, minor) / min(major, minor)
    deviation = ratio - 1.0
    ok = deviation <= tolerance
    return ok, round(ratio, 3)


def _refine_circle_candidate(page_gray, cx, cy, r, pad=1.3):
    """
    Verfijnt een ruwe Hough-cirkelschatting tot de precieze buitenste ring.

    Hough-cirkeldetectie geeft een goede eerste locatie, maar de straal kan
    een paar procent afwijken van de werkelijke ringrand — genoeg om de dunne
    inktlijnen (ring/tekst) net verkeerd uit te lijnen bij het samplen van
    kleuren, ook al blijft de algehele vormscore prima. Deze functie zoekt in
    een iets ruimer uitgesneden gebied naar de contour met de grootste
    omcirkelende straal die dicht bij de oorspronkelijke schatting ligt (dat
    is vrijwel altijd de werkelijke buitenste ring), en levert een preciezer
    (cx, cy, r) terug in dezelfde (pagina-)coördinaten.
    """
    h, w = page_gray.shape
    half = int(r * pad)
    x0, y0 = max(0, int(cx - half)), max(0, int(cy - half))
    x1, y1 = min(w, int(cx + half)), min(h, int(cy + half))
    if x1 - x0 < 20 or y1 - y0 < 20:
        return cx, cy, r

    region = page_gray[y0:y1, x0:x1]
    edges = _prep_edges(region)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return cx, cy, r

    candidates = []
    for c in contours:
        (ccx, ccy), rr = cv2.minEnclosingCircle(c)
        if 0.6 * r <= rr <= 1.4 * r:
            candidates.append((rr, ccx, ccy))
    if not candidates:
        return cx, cy, r

    rr, ccx, ccy = max(candidates, key=lambda t: t[0])
    return x0 + ccx, y0 + ccy, rr


def score_logo_candidate(page_rgb, cx, cy, r, references, pad=LOGO_REFERENCE_PAD,
                          fixed_size=LOGO_REFERENCE_FIXED_SIZE):
    """
    Beoordeelt één kandidaat-locatie (cirkel) op de pagina tegen alle
    referenties, en retourneert de resultaten voor de best passende referentie.
    """
    h, w = page_rgb.shape[:2]
    half = int(r * pad)
    x0, x1 = max(0, int(cx - half)), min(w, int(cx + half))
    y0, y1 = max(0, int(cy - half)), min(h, int(cy + half))
    if x1 - x0 < 20 or y1 - y0 < 20:
        return None

    region_rgb = page_rgb[y0:y1, x0:x1]
    region_rgb_resized = cv2.resize(region_rgb, (fixed_size, fixed_size), interpolation=cv2.INTER_AREA)
    region_gray = cv2.cvtColor(region_rgb_resized, cv2.COLOR_RGB2GRAY)
    region_edges = _prep_edges(region_gray)
    if np.count_nonzero(region_edges) < 30:
        return None
    region_soft = _soft_edges(region_edges)

    best = None
    for ref in references:
        try:
            result = cv2.matchTemplate(region_soft, ref["soft_edges"], cv2.TM_CCOEFF_NORMED)
            shape_score = float(result[0, 0]) if result.size == 1 else float(result.max())
        except cv2.error:
            continue

        gap_pixels = region_rgb_resized[ref["gap_mask"]]
        ink_pixels = region_rgb_resized[ref["ink_mask"]]
        gap_fraction, gap_color = _color_uniformity(gap_pixels, GAP_COLOR_DIST_THRESHOLD)
        ink_fraction, ink_color = _color_uniformity(ink_pixels, INK_COLOR_DIST_THRESHOLD)

        candidate_result = {
            "reference_name": ref["name"], "shape_score": shape_score,
            "gap_fraction": gap_fraction, "gap_color": gap_color,
            "gap_uniform": (gap_fraction is not None and gap_fraction >= GAP_UNIFORM_MIN_FRACTION),
            "ink_fraction": ink_fraction, "ink_color": ink_color,
            "ink_uniform": (ink_fraction is not None and ink_fraction >= INK_UNIFORM_MIN_FRACTION),
        }

        # Kies de referentie met de beste vormscore als 'beste match' voor deze kandidaat
        if best is None or shape_score > best["shape_score"]:
            best = candidate_result

    if best is None:
        return None

    aspect_ok, aspect_ratio = _aspect_ratio_check(region_gray)
    best["aspect_ok"] = aspect_ok
    best["aspect_ratio"] = aspect_ratio
    best["bbox"] = (x0, y0, x1 - x0, y1 - y0)
    return best


def _refine_candidate(page_rgb, cx, cy, r, references, passes=2,
                       r_range=16, r_step=2, xy_range=6, xy_step=1):
    """
    Verfijnt een grove Hough-kandidaat met coördinaat-afdaling (om beurten
    straal, x-positie en y-positie lokaal optimaliseren op vormscore).

    Nodig gebleken in de praktijk: Hough's eerste schatting lokaliseert het
    logo goed genoeg om te VINDEN, maar niet precies genoeg om de dunne
    inktlijnen pixel-voor-pixel te kunnen samplen (een paar pixels afwijking
    verschuift een dunne letter al grotendeels van zijn kleurvlak af, wat de
    inkt-egaliteitsscore onterecht laat kelderen). Coördinaat-afdaling is
    hier gekozen boven een volledige grid-search: vergelijkbare nauwkeurigheid,
    op een fractie van de rekentijd.
    """
    best_score = -1.0
    best_result = None
    for _ in range(passes):
        for dr in range(-r_range, r_range + 1, r_step):
            res = score_logo_candidate(page_rgb, cx, cy, r + dr, references)
            if res and res["shape_score"] > best_score:
                best_score, r, best_result = res["shape_score"], r + dr, res
        for dcx in range(-xy_range, xy_range + 1, xy_step):
            res = score_logo_candidate(page_rgb, cx + dcx, cy, r, references)
            if res and res["shape_score"] > best_score:
                best_score, cx, best_result = res["shape_score"], cx + dcx, res
        for dcy in range(-xy_range, xy_range + 1, xy_step):
            res = score_logo_candidate(page_rgb, cx, cy + dcy, r, references)
            if res and res["shape_score"] > best_score:
                best_score, cy, best_result = res["shape_score"], cy + dcy, res
        r_range = max(4, r_range // 2)
        xy_range = max(2, xy_range // 2)

    return best_result, cx, cy, r


def verify_logo_in_page(page_rgb_array, references, shape_threshold=0.20):
    """
    Zoekt en verifieert het CA-logo op de pagina.

    Strategie: Hough-cirkeldetectie lokaliseert kandidaten (alle varianten
    zijn een cirkelvormig zegel); de sterkste paar kandidaten worden daarna
    lokaal verfijnd (zie _refine_candidate) voor pixel-nauwkeurige uitlijning,
    en pas op die verfijnde positie wordt de vormscore, de kleur-egaliteit
    binnen het logo (inkt en 'gaten') en de aspectratio (vervormings-check)
    definitief bepaald.

    Retourneert een resultaat-dict (zie 'found'/'compliant' voor de twee
    kernvragen: staat het logo er, en is het onveranderd gebruikt).
    """
    empty = {
        "found": False, "compliant": False, "shape_score": 0.0,
        "reference_name": None, "gap_uniform": None, "gap_fraction": None,
        "ink_uniform": None, "ink_fraction": None, "aspect_ok": None,
        "aspect_ratio": None, "bbox": None,
    }
    if not references:
        return empty

    page_gray = cv2.cvtColor(page_rgb_array, cv2.COLOR_RGB2GRAY)
    page_h, page_w = page_gray.shape

    max_dim = 1200
    scale_factor = min(1.0, max_dim / max(page_h, page_w))
    work_rgb = (
        cv2.resize(page_rgb_array, (int(page_w * scale_factor), int(page_h * scale_factor)),
                   interpolation=cv2.INTER_AREA)
        if scale_factor < 1.0 else page_rgb_array
    )
    work_gray = cv2.cvtColor(work_rgb, cv2.COLOR_RGB2GRAY)
    work_h, work_w = work_gray.shape

    circle_input = cv2.medianBlur(work_gray, 5)
    circles = cv2.HoughCircles(
        circle_input, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=int(work_w * 0.06), param1=80, param2=35,
        minRadius=int(work_w * 0.015), maxRadius=int(work_w * 0.45),
    )

    if circles is None:
        return empty

    # Hough zoekt op de verkleinde 'work_rgb' voor snelheid, maar de fijne
    # inktlijnen verliezen daarbij te veel brondetail voor betrouwbare
    # kleursampling (een paar pixels afwijking op verkleinde schaal is
    # proportioneel een veel grotere fout). Daarom worden de kandidaten
    # teruggerekend naar de ORIGINELE resolutie, en gebeurt de verfijning +
    # definitieve scoring daar.
    #
    # Tweetraps-verfijning voor de snelheid: eerst een GOEDKOPE, grove
    # verfijning (1 pas, grote stappen) op alle kandidaten om te bepalen
    # welke overtuigend de beste is, en pas daarna de DURE, fijne verfijning
    # (2 passen, kleine stappen — nodig voor pixel-nauwkeurige inktsampling)
    # op alleen die ene winnaar. Dat scheelt een veelvoud aan rekentijd t.o.v.
    # iedere kandidaat meteen fijn verfijnen.
    TOP_N_TO_REFINE = 12
    inv_scale = 1.0 / scale_factor

    coarse_best = None
    for cx, cy, r in circles[0][:TOP_N_TO_REFINE]:
        full_cx, full_cy, full_r = cx * inv_scale, cy * inv_scale, r * inv_scale
        coarse, rcx, rcy, rr = _refine_candidate(
            page_rgb_array, full_cx, full_cy, full_r, references,
            passes=1, r_range=max(16, int(full_r * 0.15)), r_step=4,
            xy_range=max(6, int(full_r * 0.06)), xy_step=3,
        )
        if coarse is not None and (coarse_best is None or coarse["shape_score"] > coarse_best[0]["shape_score"]):
            coarse_best = (coarse, rcx, rcy, rr)

    if coarse_best is None:
        return empty

    _, cx0, cy0, r0 = coarse_best
    best, _, _, _ = _refine_candidate(page_rgb_array, cx0, cy0, r0, references, passes=2)
    if best is not None:
        best["_scale_factor"] = 1.0  # bbox van 'best' staat al in volledige-resolutie-coördinaten

    if best is None:
        return empty

    found = best["shape_score"] >= shape_threshold
    compliant = bool(found and best["gap_uniform"] and best["ink_uniform"] and best["aspect_ok"])

    bx, by, bw, bh = best["bbox"]
    sf = best["_scale_factor"]
    bbox_full = (int(bx / sf), int(by / sf), int(bw / sf), int(bh / sf))

    return {
        "found": found, "compliant": compliant,
        "shape_score": round(best["shape_score"], 3),
        "reference_name": best["reference_name"],
        "gap_uniform": best["gap_uniform"], "gap_fraction": best["gap_fraction"],
        "gap_color": best["gap_color"],
        "ink_uniform": best["ink_uniform"], "ink_fraction": best["ink_fraction"],
        "ink_color": best["ink_color"],
        "aspect_ok": best["aspect_ok"], "aspect_ratio": best["aspect_ratio"],
        "bbox": bbox_full,
    }



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
# Volledige analyse
# =============================================================================

@st.cache_resource(show_spinner=False)
def get_logo_references():
    return load_logo_references(LOGO_REFERENCE_FOLDER)


def analyze_file(uploaded_file, ai_config=None):
    results = {"errors": []}

    page_img, is_pdf, pdf_bytes = load_uploaded_file(uploaded_file)

    if page_img is None:
        results["errors"].append(
            "Kon PDF niet inlezen: PyMuPDF ontbreekt op de server. Voeg 'pymupdf' toe aan requirements.txt."
        )
        return results

    page_array = np.array(page_img)

    # --- 1. Logo-verificatie ---
    references = get_logo_references()
    if not references:
        results["logo"] = {
            "found": False, "compliant": False, "shape_score": 0.0, "reference_name": None,
            "gap_uniform": None, "ink_uniform": None, "aspect_ok": None,
            "note": "Geen referentie-PDF's gevonden in de 'logo_reference' map.",
        }
    else:
        results["logo"] = verify_logo_in_page(page_array, references)

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
        results["logo"]["compliant"]
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
        st.markdown("**Officiële logo-referentie:**")
        references = get_logo_references()
        if references:
            st.success(f"{len(references)} referentiebestand(en) geladen")
            with st.expander("Toon geladen referenties"):
                for r in references:
                    st.write(f"• {r['name']}  ({r['mark'].upper()}, {r['position']})")
            st.caption(
                "Andere taal/regio? Vervang de PDF's in de map `logo_reference/` door "
                "de officiële logo-PDF van dat land (zelfde naamconventie met 'inner'/"
                "'outer' en 'TM'/'R') — geen codewijziging nodig."
            )
        else:
            st.error("Geen referentie-PDF's gevonden in de 'logo_reference' map")

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
            "- ✅ Officieel logo, ONVERANDERD gebruikt: geen vervorming/andere "
            "verhoudingen, geen effecten, en zowel de inkt als de achtergrond "
            "binnen de buitenste cirkel in 1 egale kleur\n"
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
        shape_percent = _logo_score_to_percent(logo["shape_score"])
        ref_label = f"vergeleken met: {logo['reference_name']}" if logo["reference_name"] else "geen kandidaat gevonden"
        render_score_circle("Logo — vormgelijkenis", shape_percent, ref_label)

        if not logo["found"]:
            st.caption(
                "⚠️ Onder de detectiedrempel — geen betrouwbare match. Dit kan kloppen "
                "(geen logo aanwezig), maar controleer bij twijfel visueel of het logo "
                "er echt niet op staat, vooral bij een drukke achtergrond of lage resolutie."
            )
        else:
            gap_ok = logo["gap_uniform"]
            ink_ok = logo["ink_uniform"]
            aspect_ok = logo["aspect_ok"]

            gap_detail = (
                f"{round((logo['gap_fraction'] or 0) * 100)}% van de achtergrond binnen de "
                f"buitenste cirkel is 1 egale kleur" + (f" ({logo['gap_color']})" if logo.get("gap_color") else "")
            )
            render_check_line("", "Achtergrond binnen logo is 1 egale kleur (geen foto/patroon zichtbaar)", gap_ok, gap_detail)

            ink_detail = (
                f"{round((logo['ink_fraction'] or 0) * 100)}% van de inkt (ring/letters/tekst) is 1 egale kleur"
                + (f" ({logo['ink_color']})" if logo.get("ink_color") else "")
            )
            render_check_line("", "Inkt van het logo is 1 egale kleur (geen effecten)", ink_ok, ink_detail)

            aspect_detail = (
                f"as-verhouding {logo['aspect_ratio']}"
                if logo.get("aspect_ratio") is not None else "kon niet worden bepaald"
            )
            render_check_line("", "Geen vervorming — juiste verhoudingen (cirkelvormig)", bool(aspect_ok), aspect_detail)

            if not logo["compliant"]:
                st.warning(
                    "⚠️ Het logo is gevonden, maar wijkt af van het officiële ontwerp "
                    "(zie bovenstaande deelcontroles). Volgens de merkrichtlijnen mag het "
                    "logo niet vervormd, voorzien van effecten, of op een niet-egale "
                    "achtergrond geplaatst worden."
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
