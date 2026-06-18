import streamlit as st
import cv2
import numpy as np
from PIL import Image
import os
from pathlib import Path
import tempfile
from scipy import ndimage
from skimage.metrics import structural_similarity as ssim
import matplotlib.pyplot as plt

# Configuratie
st.set_page_config(
    page_title="CA Flyer Checker",
    page_icon="✅",
    layout="wide"
)

class CAFlyerChecker:
    def __init__(self, assets_folder="assets"):
        self.assets_folder = Path(assets_folder)
        self.reference_logos = self._load_reference_logos()
        self.english_logos = self._load_english_logos()
        
    def _load_reference_logos(self):
        """Laad alle officiële Nederlandstalige referentie logo's"""
        logos = {}
        if self.assets_folder.exists():
            for file in self.assets_folder.glob("*.png"):
                # Skip engelstalige logo's (je kunt deze later filteren)
                if "en" not in file.stem.lower():
                    try:
                        img = cv2.imread(str(file), cv2.IMREAD_UNCHANGED)
                        if img is not None:
                            logos[file.stem] = img
                    except Exception as e:
                        st.warning(f"Kon logo niet laden: {file.name}")
        return logos
    
    def _load_english_logos(self):
        """Laad de engelstalige logo's die niet gebruikt mogen worden"""
        english = {}
        for file in self.assets_folder.glob("*en*.png"):
            try:
                img = cv2.imread(str(file), cv2.IMREAD_UNCHANGED)
                if img is not None:
                    english[file.stem] = img
            except:
                pass
        return english
    
    def check_background_uniformity(self, img, threshold=10):
        """
        Check of een transparant logo een egale achtergrondkleur heeft
        threshold: maximale kleurverschil voor 'egale' kleur
        """
        if img.shape[2] == 4:  # Heeft alpha kanaal
            alpha = img[:, :, 3]
            if np.any(alpha < 255):  # Er is transparantie
                # Check alleen de niet-transparante pixels
                non_transparent = img[alpha > 0][:, :3]
                if len(non_transparent) > 0:
                    std_dev = np.std(non_transparent, axis=0)
                    max_std = np.max(std_dev)
                    if max_std <= threshold:
                        return True, f"Achtergrond is egaal (std: {max_std:.2f})"
                    else:
                        return False, f"Achtergrond is niet egaal (std: {max_std:.2f})"
        return True, "Geen transparantie gedetecteerd"
    
    def check_distortion(self, img, reference_img):
        """Check of het logo niet gestretched of vervormd is"""
        if img.shape != reference_img.shape:
            return False, "Afmetingen komen niet overeen met referentie"
        
        # Check aspect ratio
        h, w = img.shape[:2]
        ref_h, ref_w = reference_img.shape[:2]
        
        aspect_ratio = w / h
        ref_aspect = ref_w / ref_h
        
        if abs(aspect_ratio - ref_aspect) > 0.05:
            return False, f"Aspect ratio afwijkend: {aspect_ratio:.2f} vs {ref_aspect:.2f}"
        
        return True, "Geen vervorming gedetecteerd"
    
    def check_effects(self, img):
        """Check of er schaduwen, emboss of andere effecten zijn"""
        gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
        
        # Check voor schaduwen met edge detection
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size
        
        if edge_density > 0.3:  # Te veel edges kan duiden op effecten
            return False, f"Te veel randen gedetecteerd (mogelijk schaduw of emboss): {edge_density:.2f}"
        
        # Check voor gradient/kleurovergangen
        grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)
        
        if np.mean(gradient_magnitude) > 50:
            return False, "Kleurovergangen gedetecteerd (mogelijk 3D effect)"
        
        return True, "Geen ongewenste effecten gedetecteerd"
    
    def match_logo(self, uploaded_img):
        """Vergelijk het geüploade logo met referenties"""
        best_match = None
        best_score = 0
        
        for name, ref_logo in self.reference_logos.items():
            # Resize voor vergelijking
            if uploaded_img.shape != ref_logo.shape:
                ref_resized = cv2.resize(ref_logo, (uploaded_img.shape[1], uploaded_img.shape[0]))
            else:
                ref_resized = ref_logo
            
            # Bereken gelijkenis (SSIM)
            if uploaded_img.shape[2] == 4 and ref_resized.shape[2] == 4:
                # Alleen RGB vergelijken
                score = ssim(
                    uploaded_img[:, :, :3], 
                    ref_resized[:, :, :3], 
                    multichannel=True
                )
            else:
                gray1 = cv2.cvtColor(uploaded_img[:, :, :3], cv2.COLOR_BGR2GRAY)
                gray2 = cv2.cvtColor(ref_resized[:, :, :3], cv2.COLOR_BGR2GRAY)
                score = ssim(gray1, gray2)
            
            if score > best_score:
                best_score = score
                best_match = name
        
        return best_match, best_score
    
    def check_english_logo(self, img):
        """Check of het een engelstalig logo is (niet toegestaan)"""
        for name, eng_logo in self.english_logos.items():
            # Vergelijk met engelstalig logo
            if img.shape[2] == 4 and eng_logo.shape[2] == 4:
                score = ssim(
                    img[:, :, :3], 
                    eng_logo[:, :, :3], 
                    multichannel=True
                )
                if score > 0.85:  # Hoge gelijkenis
                    return True, name, score
        return False, None, 0
    
    def analyze_logo(self, image_path):
        """Volledige analyse van een logo"""
        img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return {"error": "Kon afbeelding niet laden"}
        
        results = {
            "valid": True,
            "checks": {},
            "errors": [],
            "warnings": []
        }
        
        # 1. Check of het een engelstalig logo is
        is_english, eng_name, eng_score = self.check_english_logo(img)
        if is_english:
            results["valid"] = False
            results["errors"].append(f"Engelstalig logo gebruikt: {eng_name}")
            return results
        
        # 2. Check of het logo matcht met referenties
        match_name, match_score = self.match_logo(img)
        if match_name and match_score > 0.7:
            results["checks"]["match"] = f"Match gevonden: {match_name} (score: {match_score:.2f})"
            ref_logo = self.reference_logos[match_name]
        else:
            results["valid"] = False
            results["errors"].append(f"Geen match met officieel logo (score: {match_score:.2f})")
            return results
        
        # 3. Check achtergrond uniformiteit
        uniform, msg = self.check_background_uniformity(img)
        results["checks"]["background"] = msg
        if not uniform:
            results["valid"] = False
            results["errors"].append(f"Achtergrond: {msg}")
        
        # 4. Check distortion
        no_distortion, msg = self.check_distortion(img, ref_logo)
        results["checks"]["distortion"] = msg
        if not no_distortion:
            results["valid"] = False
            results["errors"].append(f"Vervorming: {msg}")
        
        # 5. Check effects
        no_effects, msg = self.check_effects(img)
        results["checks"]["effects"] = msg
        if not no_effects:
            results["valid"] = False
            results["errors"].append(f"Effecten: {msg}")
        
        return results

def main():
    st.title("🖼️ CA Flyer Logo Checker")
    st.markdown("""
    ### Controleer of de officiële Nederlandstalige CA logo's correct zijn gebruikt
    * ✅ Logo moet onbewerkt zijn
    * ✅ Geen transparantie of egale achtergrond
    * ✅ Geen stretching of vervorming
    * ✅ Geen schaduwen of andere effecten
    * ❌ Geen Engelstalige logo's
    """)
    
    # Initialize checker
    checker = CAFlyerChecker()
    
    # Upload sectie
    uploaded_file = st.file_uploader(
        "Upload een flyer (PNG of JPG)",
        type=['png', 'jpg', 'jpeg'],
        help="Upload een afbeelding van de flyer met het CA logo"
    )
    
    if uploaded_file is not None:
        # Toon de geüploade afbeelding
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("📤 Geüploade flyer")
            image = Image.open(uploaded_file)
            st.image(image, use_column_width=True)
        
        # Sla tijdelijk op voor analyse
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = Path(tmp_file.name)
        
        # Voer analyse uit
        with st.spinner("🔍 Analyseren van het logo..."):
            results = checker.analyze_logo(tmp_path)
        
        # Toon resultaten
        with col2:
            st.subheader("📊 Analyse resultaten")
            
            if "error" in results:
                st.error(f"❌ Fout: {results['error']}")
            else:
                # Algemene status
                if results["valid"]:
                    st.success("✅ Logo voldoet aan alle eisen!")
                else:
                    st.error("❌ Logo voldoet NIET aan de eisen")
                
                # Toon checks
                st.markdown("---")
                st.markdown("#### 🔍 Uitgevoerde controles:")
                
                for check, msg in results.get("checks", {}).items():
                    st.write(f"• **{check}**: {msg}")
                
                # Toon fouten
                if results.get("errors"):
                    st.markdown("---")
                    st.markdown("#### ❌ Fouten gevonden:")
                    for error in results["errors"]:
                        st.error(f"• {error}")
                
                # Toon warnings
                if results.get("warnings"):
                    st.markdown("---")
                    st.markdown("#### ⚠️ Waarschuwingen:")
                    for warning in results["warnings"]:
                        st.warning(f"• {warning}")
        
        # Cleanup
        os.unlink(tmp_path)
    
    # Toon referentie logo's in sidebar
    with st.sidebar:
        st.header("📋 Officiële logo's")
        
        if checker.reference_logos:
            st.markdown("**Toegestane Nederlandstalige logo's:**")
            for name in checker.reference_logos.keys():
                st.write(f"✅ {name}")
        else:
            st.warning("Geen referentie logo's gevonden in assets folder")
        
        if checker.english_logos:
            st.markdown("---")
            st.markdown("**❌ Niet-toegestane Engelstalige logo's:**")
            for name in checker.english_logos.keys():
                st.write(f"🚫 {name}")
        
        st.markdown("---")
        st.markdown("### 📝 Vereisten")
        st.markdown("""
        - Officieel CA logo (Nederlands)
        - Geen transparante achtergrond
        - Geen bewerkingen
        - Correcte afmetingen
        - Geen effecten
        """)

if __name__ == "__main__":
    main()
