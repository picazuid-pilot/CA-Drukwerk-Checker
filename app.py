import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import os
import re
import tempfile
from collections import Counter

# ReportLab proberen te laden voor PDF generatie
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# Pagina-instellingen voor de internetbrowser
st.set_page_config(
    page_title="C.A. Holland - Flyer Matrix & Bleed Tool",
    page_icon="📐",
    layout="wide"
)

# C.A. Huisstijl CSS
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    h1, h2, h3 { color: #00594F; }
    .report-title { font-weight: bold; font-size: 20px; color: #00594F; border-bottom: 2px solid #00594F; padding-bottom: 5px; }
    .stAlert { margin-top: 10px; }
    </style>
    """, unsafe_allow_html=True)

# Constanten
CA_GREEN_RGB = (0, 89, 79)
CA_GREEN_HEX = "#00594F"
CA_HOLLAND_PHONE_CLEAN = "0610192770"
CA_HOLLAND_EMAIL_REGEX = r'[A-Za-z0-9._%+-]+@ca-holland\.nl'
ANY_EMAIL_REGEX = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

FORMATS = {
    "A5": (148, 210),
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "A1": (594, 841),
    "A0": (841, 1189)
}

# --- KERNFUNCTIONS ---

def get_dominant_color(image):
    small_img = image.resize((100, 100))
    small_img = small_img.quantize(colors=64).convert('RGB')
    pixels = list(small_img.getdata())
    return Counter(pixels).most_common(1)[0][0]

def check_tradition_6(full_text):
    text_lower = full_text.lower()
    indicators = [
        "traditie", "geest", "verbonden", "kerken", "sekten", 
        "politieke", "hulpverlenende", "instanties", "ca is niet", "c.a."
    ]
    matches = 0
    for word in indicators:
        if word in text_lower:
            matches += 1
        elif word == "verbonden" and ("verbon" in text_lower or "verb0n" in text_lower):
            matches += 1
        elif word == "instanties" and ("instanti" in text_lower or "instanf" in text_lower):
            matches += 1
    return matches >= 3

def create_bleed_image(original_
