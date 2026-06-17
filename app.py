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

def create_bleed_image(original_img, bleed_pixels, method, custom_color=None):
    width, height = original_img.size
    new_width = width + (bleed_pixels * 2)
    new_height = height + (bleed_pixels * 2)
    
    if method == "Wit / Geselecteerde Kleur":
        color = custom_color if custom_color else (255, 255, 255)
        new_img = Image.new('RGB', (new_width, new_height), color)
        new_img.paste(original_img, (bleed_pixels, bleed_pixels))
        
    elif method == "Spiegelen (Mirror)":
        # Veiligheidslaag tegen subpixel-kieren
        new_img = original_img.resize((new_width, new_height), Image.Resampling.NEAREST)
        new_img.paste(original_img, (bleed_pixels, bleed_pixels))
        
        # Spiegel randen met 1 pixel extra overlap
        top_mirror = original_img.crop((0, 0, width, bleed_pixels + 1))
        top_mirror = top_mirror.transpose(Image.FLIP_TOP_BOTTOM)
        new_img.paste(top_mirror, (bleed_pixels, 0))
        
        bottom_mirror = original_img.crop((0, height - bleed_pixels - 1, width, height))
        bottom_mirror = bottom_mirror.transpose(Image.FLIP_TOP_BOTTOM)
        new_img.paste(bottom_mirror, (bleed_pixels, new_height - bleed_pixels))
        
        left_mirror = original_img.crop((0, 0, bleed_pixels + 1, height))
        left_mirror = left_mirror.transpose(Image.FLIP_LEFT_RIGHT)
        new_img.paste(left_mirror, (0, bleed_pixels))
        
        right_mirror = original_img.crop((width - bleed_pixels - 1, 0, width, height))
        right_mirror = right_mirror.transpose(Image.FLIP_LEFT_RIGHT)
        new_img.paste(right_mirror, (new_width - bleed_pixels, bleed_pixels))
        
        # Hoeken
        top_left = original_img.crop((0, 0, bleed_pixels + 1, bleed_pixels + 1)).transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.FLIP_LEFT_RIGHT)
        new_img.paste(top_left,
