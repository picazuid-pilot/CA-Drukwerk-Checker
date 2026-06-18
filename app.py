import streamlit as st
import numpy as np
from PIL import Image, ImageChops, ImageStat
import os
from pathlib import Path
import tempfile
from scipy import ndimage
from skimage.metrics import structural_similarity as ssim
from skimage import exposure
import matplotlib.pyplot as plt
import io

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
                # Skip engelstalige logo's
                if "en" not in file.stem.lower() and "eng" not in file.stem.lower():
                    try:
                        img = Image.open(file).convert('RGBA')
                        logos[file.stem] = np.array(img)
                    except Exception as e:
                        st.warning(f"Kon logo niet laden: {file.name}")
        return logos
    
    def _load_english_logos(self):
        """Laad de engelstalige logo's die niet gebruikt mogen worden"""
        english = {}
        if self.assets_folder.exists():
            for file in self.assets_folder.glob("*.png"):
                if "en" in file.stem.lower() or "eng" in file.stem.lower():
                    try:
                        img = Image.open(file).convert('RGBA')
                        english[file.stem] = np.array(img)
                    except:
                        pass
        return english
    
    def _image_to_array(self, img):
        """Converteer PIL Image naar numpy array"""
        if isinstance(img, Image.Image):
            return np.array(img.convert('RGBA'))
        return img
    
    def check_background_uniformity(self, img_array, threshold=15):
        """
        Check of een transparant logo een egale achtergrondkleur heeft
        threshold: maximale kleurverschil voor 'egale' kleur
        """
        if img_array.shape[2] == 4:  # Heeft alpha kanaal
            alpha = img_array[:, :, 3]
            if np.any(alpha < 255):  # Er is transparantie
                # Check alleen de niet-transparante pixels
                non_transparent = img_array[alpha > 0][:, :3]
                if len(non_transparent) > 0:
                    std_dev = np.std(non_transparent, axis=0)
                    max_std = np.max(std_dev)
                    if max_std <= threshold:
                        return True, f"Achtergrond is egaal (std: {max_std:.2f})"
                    else:
                        return False, f"Achtergrond is niet egaal (std: {max_std:.2f})"
        return True, "Geen transparantie gedetecteerd"
    
    def check_distortion(self, img_array, reference_array):
        """Check of het logo niet gestretched of vervormd is"""
        if img_array.shape != reference_array.shape:
            return False, f"Afmetingen komen niet overeen: {img_array.shape} vs {reference_array.shape}"
        
        # Check aspect ratio
        h, w = img_array.shape[:2]
        ref_h, ref_w = reference_array.shape[:2]
        
        aspect_ratio = w / h
        ref_aspect = ref_w / ref_h
        
        if abs(aspect_ratio - ref_aspect) > 0.05:
            return False, f"Aspect ratio afwijkend: {aspect_ratio:.2f} vs {ref_aspect:.2f}"
        
        return True, "Geen vervorming gedetecteerd"
    
    def check_effects(self, img_array):
        """Check of er schaduwen, emboss of andere effecten zijn"""
        # Convert to grayscale
        if img_array.shape[2] >= 3:
            gray = np.dot(img_array[:, :, :3], [0.2989, 0.5870, 0.1140])
        else:
            gray = img_array[:, :, 0]
        
        # Check voor schaduwen met edge detection (simpele gradient)
        grad_x = np.gradient(gray, axis=1)
        grad_y = np.gradient(gray, axis=0)
        gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)
        
        # Edge density
        edge_threshold = np.mean(gradient_magnitude) + 2 * np.std(gradient_magnitude)
        edges = gradient_magnitude > edge_threshold
        edge_density = np.sum(edges) / edges.size
        
        if edge_density > 0.2:
            return False, f"Te veel randen gedetecteerd (mogelijk schaduw of emboss): {edge_density:.2f}"
        
        # Check voor gradient/kleurovergangen
        if np.mean(gradient_magnitude) > 30:
            return False, f"Kleurovergangen gedetecteerd (mogelijk 3D effect): {np.mean(gradient_magnitude):.2f}"
        
        return True, "Geen ongewenste effecten gedetecteerd"
    
    def match_logo(self, uploaded_img_array):
        """Vergelijk het geüploade logo met referenties"""
        best_match = None
        best_score = 0
        
        for name, ref_array in self.reference_logos.items():
            try:
                # Resize voor vergelijking
                if uploaded_img_array.shape != ref_array.shape:
                    # Resize ref naar upload formaat
                    ref_pil = Image.fromarray(ref_array)
                    ref_resized = ref_pil.resize((uploaded_img_array.shape[1], uploaded_img_array.shape[0]))
                    ref_array_resized = np.array(ref_resized)
                else:
                    ref_array_resized = ref_array
                
                # Bereken gelijkenis (SSIM) - alleen RGB
                if uploaded_img_array.shape[2] >= 3 and ref_array_resized.shape[2] >= 3:
                    upload_rgb = uploaded_img_array[:, :, :3]
                    ref_rgb = ref_array_resized[:, :, :3]
                    
                    # Resize voor SSIM (als te groot)
                    if upload_rgb.shape[0] > 500 or upload_rgb.shape[1] > 500:
                        upload_rgb = upload_rgb[::2, ::2, :]
                        ref_rgb = ref_rgb[::2, ::2, :]
                    
                    # Bereken SSIM (met fallback voor kleine afbeeldingen)
                    try:
                        from skimage.metrics import structural_similarity as ssim_func
                        score = ssim_func(upload_rgb, ref_rgb, channel_axis=2, data_range=255)
                    except:
                        # Fallback: gebruik mean squared error
                        mse = np.mean((upload_rgb - ref_rgb) ** 2)
                        score = 1 - (mse / (255 ** 2))
                
                    if score > best_score:
                        best_score = score
                        best_match = name
            except Exception as e:
                continue
        
        return best_match, best_score
    
    def check_english_logo(self, img_array):
        """Check of het een engelstalig logo is (niet toegestaan)"""
        for name, eng_array in self.english_logos.items():
            try:
                # Vergelijk met engelstalig logo
                if img_array.shape[2] >= 3 and eng_array.shape[2] >= 3:
                    upload_rgb = img_array[:, :, :3]
                    eng_rgb = eng_array[:, :, :3]
                    
                    # Resize voor vergelijking
                    if upload_rgb.shape != eng_rgb.shape:
                        eng_pil = Image.fromarray(eng_rgb)
                        eng_resized = eng_pil.resize((upload_rgb.shape[1], upload_rgb.shape[0]))
                        eng_rgb = np.array(eng_resized)
                    
                    # Bereken gelijkenis
                    from skimage.metrics import structural_similarity as ssim_func
                    score = ssim_func(upload_rgb, eng_rgb, channel_axis=2, data_range=255)
                    
                    if score > 0.85:  # Hoge gelijkenis
                        return True, name, score
            except:
                pass
        return False, None, 0
    
    def analyze_logo(self, image_path):
        """Volledige analyse van een logo"""
        try:
            img = Image.open(image_path).convert('RGBA')
            img_array = np.array(img)
        except Exception as e:
            return {"error": f"Kon afbeelding niet laden: {str(e)}"}
        
        results = {
            "valid": True,
            "checks": {},
            "errors": [],
            "warnings": []
        }
        
        # 1. Check of het een engelstalig logo is
        is_english, eng_name, eng_score = self.check_english_logo(img_array)
        if is_english:
            results["valid"] = False
            results["errors"].append(f"❌ Engelstalig logo gebruikt: {eng_name} (score: {eng_score:.2f})")
            return results
        
        # 2. Check of het logo matcht met referenties
        match_name, match_score = self.match_logo(img_array)
        if match_name and match_score > 0.7:
            results["checks"]["match"] = f"✅ Match gevonden: {match_name} (score: {match_score:.2f})"
            ref_logo = self.reference_logos[match_name]
        else:
            results["valid"] = False
            results["errors"].append(f"❌ Geen match met officieel logo (score: {match_score:.2f})")
            return results
        
        # 3. Check achtergrond uniformiteit
        uniform, msg = self.check_background_uniformity(img_array)
        results["checks"]["background"] = f"{'✅' if uniform else '❌'} {msg}"
        if not uniform:
            results["valid"] = False
            results["errors"].append(f"Achtergrond: {msg}")
        
        # 4. Check distortion
        no_distortion, msg = self.check_distortion(img_array, ref_logo)
        results["checks"]["distortion"] = f"{'✅' if no_distortion else '❌'} {msg}"
        if not no_distortion:
            results["valid"] = False
            results["errors"].append(f"Vervorming: {msg}")
        
        # 5. Check effects
        no_effects, msg = self.check_effects(img_array)
        results["checks"]["effects"] = f"{'✅' if no_effects else '❌'} {msg}"
        if not no_effects:
            results["valid"] = False
            results["errors"].append(f"Effecten: {msg}")
        
        return results

def main():
    st.title("🖼️ CA Flyer Logo Checker")
    st.markdown("""
    ### Controleer of de officiële Nederlandstalige CA logo's correct zijn gebruikt
    
    **Deze checker controleert:**
    * ✅ Of het logo matcht met de officiële referentie
    * ✅ Of de achtergrond egaal is (bij transparante logo's)
    * ✅ Of het logo niet gestretched of vervormd is
    * ✅ Of er geen ongewenste effecten zijn (schaduwen, emboss, etc.)
    * ❌ Of er geen Engelstalige logo's zijn gebruikt
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
            
            # Toon afbeeldingsinfo
            st.caption(f"Afmetingen: {image.size[0]}x{image.size[1]} pixels")
        
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
                
                # Toon warnings (indien van toepassing)
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
            
            # Toon een voorbeeld
            st.markdown("---")
            st.markdown("**Voorbeeld referentie logo:**")
            if checker.reference_logos:
                first_logo = list(checker.reference_logos.keys())[0]
                st.image(checker.reference_logos[first_logo], width=150)
        else:
            st.warning("⚠️ Geen referentie logo's gevonden in 'assets' folder")
            st.info("Plaats de officiële CA logo's in de 'assets' folder")
        
        if checker.english_logos:
            st.markdown("---")
            st.markdown("**❌ Niet-toegestane Engelstalige logo's:**")
            for name in checker.english_logos.keys():
                st.write(f"🚫 {name}")
        
        st.markdown("---")
        st.markdown("### 📝 Vereisten voor logo's")
        st.markdown("""
        ✅ Officieel CA logo (Nederlands)
        ✅ Geen transparante achtergrond
        ✅ Geen bewerkingen
        ✅ Correcte afmetingen
        ✅ Geen effecten
        """)
        
        st.markdown("---")
        st.markdown("### 💡 Tips")
        st.markdown("""
        - Zet alle officiële logo's in de `assets` folder
        - Gebruik PNG bestanden voor transparantie
        - Geef logo's duidelijke namen
        - Engelstalige logo's moeten 'en' in de naam hebben
        """)

if __name__ == "__main__":
    main()
