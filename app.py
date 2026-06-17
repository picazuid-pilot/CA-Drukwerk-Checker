import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import cv2
import numpy as np
import requests
from io import BytesIO
from PIL import Image, ImageTk
import threading
from pathlib import Path
import re

# Kleurdefinities (Huisstijl CA)
CA_GREEN_RGB = (0, 89, 79) # BGR in OpenCV is (79, 89, 0)
CA_GREEN_HEX = "#00594F"

# Officiële contactgegevens van C.A. Holland
CA_HOLLAND_PHONE_CLEAN = "0610192770"
CA_HOLLAND_EMAIL_REGEX = r'[A-Za-z0-9._%+-]+@ca-holland\.nl' # Specifiek CA e-mailadres
ANY_EMAIL_REGEX = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

class CAFlyerCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📐 C.A. Holland - Officiële Flyer Matrix Checker")
        self.root.geometry("1100x850")
        self.root.configure(bg="#f0f2f6")
        
        # UI opbouw...
        self.create_widgets()
        
    def create_widgets(self):
        # Titel bar
        title_frame = tk.Frame(self.root, bg=CA_GREEN_HEX, height=60)
        title_frame.pack(fill=tk.X)
        title_label = tk.Label(title_frame, text="📐 C.A. HOLLAND FLYER MATRIX CHECKER", font=("Helvetica", 16, "bold"), fg="white", bg=CA_GREEN_HEX)
        title_label.pack(pady=15)
        
        # Hoofd opsplitsing (Links: Afbeelding & Knoppen, Rechts: Rapport)
        main_frame = tk.Frame(self.root, bg="#f0f2f6")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        left_frame = tk.Frame(main_frame, bg="#f0f2f6", width=450)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        
        right_frame = tk.Frame(main_frame, bg="#f0f2f6")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # Knoppen links
        self.select_btn = tk.Button(left_frame, text="📁 Selecteer Flyer Afbeelding", font=("Helvetica", 12, "bold"), bg=CA_GREEN_HEX, fg="white", command=self.select_image, padx=10, pady=5)
        self.select_btn.pack(fill=tk.X, pady=(0, 10))
        
        self.check_btn = tk.Button(left_frame, text="🔍 Start Controle", font=("Helvetica", 12, "bold"), bg="#e67e22", fg="white", state=tk.DISABLED, command=self.start_checking, padx=10, pady=5)
        self.check_btn.pack(fill=tk.X, pady=(0, 10))
        
        # Preview box
        self.preview_label = tk.Label(left_frame, text="Geen afbeelding geselecteerd", font=("Helvetica", 11), bg="#ffffff", relief=tk.SOLID, bd=1, height=25, width=45)
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        
        # Status & Resultaten rechts
        tk.Label(right_frame, text="📋 ANALYSERAPPORT & MATRIX EVALUATIE", font=("Helvetica", 12, "bold"), bg="#f0f2f6", fg=CA_GREEN_HEX).pack(anchor=tk.W, pady=(0, 5))
        
        self.results_text = scrolledtext.ScrolledText(right_frame, font=("Courier New", 11), bg="#ffffff", bd=1, relief=tk.SOLID)
        self.results_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Tags voor kleuren in het rapport
        self.results_text.tag_config("green", foreground="green", font=("Courier New", 11, "bold"))
        self.results_text.tag_config("red", foreground="red", font=("Courier New", 11, "bold"))
        self.results_text.tag_config("orange", foreground="#d35400", font=("Courier New", 11, "bold"))
        self.results_text.tag_config("blue", foreground="#2980b9", font=("Courier New", 12, "bold"))
        self.results_text.tag_config("bold", font=("Courier New", 11, "bold"))
        
        # Status bar onderin
        self.status_var = tk.StringVar(value="Status: Wachten op bestand...")
        status_label = tk.Label(self.root, textvariable=self.status_var, font=("Helvetica", 10, "italic"), anchor=tk.W, bg="#bdc3c7", padx=10, pady=3)
        status_label.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.image_path = None
        
    def select_image(self):
        path = filedialog.askopenfilename(filetypes=[("Afbeeldingen", "*.jpg *.jpeg *.png")])
        if path:
            self.image_path = path
            img = Image.open(path)
            img.thumbnail((400, 500))
            img_tk = ImageTk.PhotoImage(img)
            self.preview_label.config(image=img_tk, text="")
            self.preview_label.image = img_tk
            self.check_btn.config(state=tk.NORMAL)
            self.status_var.set(f"Bestand geladen: {Path(path).name}")
            self.results_text.delete(1.0, tk.END)
            
    def start_checking(self):
        if not self.image_path:
            return
        self.check_btn.config(state=tk.DISABLED, text="⚡ Analyseren...")
        self.status_var.set("Bezig met OCR tekstherkenning en kleurmatrix analyse...")
        threading.Thread(target=self.run_matrix_check).start()

    def check_tradition_6(self, full_text):
        """
        Geavanceerde trefwoordencombinatie om OCR-fouten (zoals verb0nden of instantis) 
        op te vangen zonder dat spelling de test direct laat falen.
        """
        text_lower = full_text.lower()
        
        # Kern-indicatoren van de 6e traditie
        indicators = [
            "traditie", "geest", "verbonden", "kerken", "sekten", 
            "politieke", "hulpverlenende", "instanties", "ca is niet", "c.a."
        ]
        
        # Tel hoeveel van de kernwoorden (of sterke gelijkenissen) aanwezig zijn
        matches = 0
        for word in indicators:
            if word in text_lower:
                matches += 1
            # Extra opvang voor bekende OCR-fouten
            elif word == "verbonden" and ("verbon" in text_lower or "verb0n" in text_lower):
                matches += 1
            elif word == "instanties" and ("instanti" in text_lower or "instanf" in text_lower):
                matches += 1
                
        # Als er minstens 3 cruciale termen in de tekst staan, is de traditietekst aanwezig
        return matches >= 3

    def run_matrix_check(self):
        try:
            # 1. OpenCV Image Processing & Kleuranalyse
            img_bgr = cv2.imread(self.image_path)
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
            
            # Bepaal het bereik voor CA-groen (H: 80-95, S: 40-255, V: 30-200)
            lower_green = np.array([75, 35, 25])
            upper_green = np.array([100, 255, 200])
            mask = cv2.inRange(hsv, lower_green, upper_green)
            
            green_pixels = np.count_nonzero(mask)
            total_pixels = img_bgr.shape[0] * img_bgr.shape[1]
            green_ratio = (green_pixels / total_pixels) * 100
            
            # Bereken dominante kleur in de groene zones om de afwijking te meten
            green_spots = cv2.bitwise_and(img_bgr, img_bgr, mask=mask)
            avg_bgr = cv2.mean(green_spots, mask=mask)[:3]
            
            color_deviation = 0
            if green_pixels > 500: # Alleen berekenen als er daadwerkelijk groen is gebruikt
                # Bereken Euclidische afstand tot officiële CA-groen (RGB: 0, 89, 79 -> BGR: 79, 89, 0)
                color_deviation = np.sqrt((avg_bgr[0]-79)**2 + (avg_bgr[1]-89)**2 + (avg_bgr[2]-0)**2)

            # 2. OCR Tekst Extractie via EasyOCR
            import easyocr
            reader = easyocr.Reader(['nl', 'en'], gpu=False)
            ocr_results = reader.readtext(self.image_path)
            
            full_text = " ".join([res[1] for res in ocr_results])
            clean_text_no_spaces = full_text.replace(" ", "")
            
            # --- VALIDATIE MATRIX ---
            
            # [A] KRITIEK (Directe afwijzing bij fout)
            # CA Logo check (EasyOCR leest logo's vaak als losse letters/TM tekens, of we scannen op de tekst 'Cocaine Anonymous')
            logo_found = "cocaine" in full_text.lower() or "anonymous" in full_text.lower() or "c.a." in full_text.lower()
            tradition_found = self.check_tradition_6(full_text)
            
            # [B] EVENEMENTGEGEVENS (Aanbevolen / Waarschuwingen)
            # Datum check via Regex (bijv: 12-12-2026 of 12 mrt)
            date_patterns = [
                r'\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}',
                r'\d{1,2}\s+(jan|feb|mrt|mar|apr|mei|may|jun|jul|aug|sep|okt|oct|nov|dec)'
            ]
            date_found = any(re.search(pat, full_text.lower()) for pat in date_patterns)
            
            # Tijd check (bijv: 19:30 of 20.00)
            time_found = re.search(r'\d{1,2}[:.]\d{2}', full_text) is not None
            
            # Adres / Locatie check
            loc_keywords = ["straat", "laan", "plein", "weg", "kerk", "gebouw", "centrum", "buurthuis", "zaal", "dijk"]
            postal_code_found = re.search(r'\d{4}\s?[A-Z]{2}', full_text.upper()) is not None
            address_found = any(kw in full_text.lower() for kw in loc_keywords) or postal_code_found
            
            # Zoom Gegevens check
            zoom_link_found = any(z in full_text.lower() for z in ["zoom.us", "zoomgov", "zoom meting", "online meeting"])
            zoom_credentials = "meeting id" in full_text.lower() or "wachtwoord" in full_text.lower() or "passcode" in full_text.lower() or "id:" in full_text.lower()
            
            # Organisator check
            org_keywords = ["groep", "district", "area", "werkgroep", "commissie", "ca holland"]
            organizer_found = any(okw in full_text.lower() for okw in org_keywords)
            
            # [C] AANBEVOLEN CONTACTGEGEVENS
            phone_found = CA_HOLLAND_PHONE_CLEAN in clean_text_no_spaces or "061019" in clean_text_no_spaces
            
            # FIX: Alleen echte e-mails via Regex valideren om valse "@" meldingen van het logo te voorkomen!
            email_match = re.search(ANY_EMAIL_REGEX, full_text)
            email_found = email_match is not None
            is_official_email = re.search(CA_HOLLAND_EMAIL_REGEX, full_text.lower()) is not None if email_found else False
            
            web_found = "www.ca-holland.nl" in clean_text_no_spaces.lower() or "ca-holland.nl" in clean_text_no_spaces.lower()

            # --- RAPPORTAGE SAMENSTELLEN ---
            results = []
            results.append(["================================================================", "bold"])
            results.append(["📝 C.A. HOLLAND FLYER CONTROLE RAPPORT", "bold", "blue"])
            results.append(["================================================================", "bold"])
            results.append(["\n🛑 KRITIEKE CONTROLES (Verplicht voor goedkeuring)", "bold"])
            
            if logo_found:
                results.append(["✅ Officieel CA-logo / Naamvermelding gevonden", "green"])
            else:
                results.append(["❌ Officieel CA-logo of C.A. naamvermelding NIET gedetecteerd", "red"])
                
            if tradition_found:
                results.append(["✅ 6e Traditie verklaring correct aanwezig", "green"])
            else:
                results.append(["❌ 6e Traditie ontbreekt of is onleesbaar (Verplicht: 'niet verbonden aan kerken...')", "red"])

            results.append(["\n📅 EVENEMENTGEGEVENS", "bold"])
            results.append([f"{'✅' if date_found else '⚠️'} Datum {'gevonden' if date_found else 'niet gevonden (Aanbevolen)'}", "green" if date_found else "orange"])
            results.append([f"{'✅' if time_found else '⚠️'} Tijdstip {'gevonden' if time_found else 'niet gevonden (Aanbevolen)'}", "green" if time_found else "orange"])
            
            if address_found or postal_code_found:
                results.append(["✅ Fysiek adres of locatiegegevens gedetecteerd", "green"])
            elif zoom_link_found:
                results.append(["✅ Online evenement: Zoom/Online link gedetecteerd", "green"])
                results.append([f"{'✅' if zoom_credentials else '⚠️'} Zoom Meeting ID/Wachtwoord {'ingevuld' if zoom_credentials else 'niet expliciet gevonden'}", "green" if zoom_credentials else "orange"])
            else:
                results.append(["⚠️ Geen fysiek adres óf Zoom-locatie gedetecteerd", "orange"])
                
            results.append([f"{'✅' if organizer_found else '⚠️'} Organiserende entiteit (Groep/District/Area) {'herkend' if organizer_found else 'niet expliciet vermeld'}", "green" if organizer_found else "orange"])

            results.append(["\n📞 AANBEVOLEN CONTACTGEGEVENS", "bold"])
            results.append([f"{'✅' if phone_found else '⚠️'} Landelijke Hulplijn (06-10192770) {'gevonden' if phone_found else 'niet vermeld'}", "green" if phone_found else "orange"])
            
            if email_found:
                if is_official_email:
                    results.append(["✅ Officieel info@ca-holland.nl e-mailadres gevonden", "green"])
                else:
                    results.append([f"✅ Alternatief e-mailadres gevonden ({email_match.group(0)})", "green"])
            else:
                results.append(["⚠️ Geen e-mailadres gevonden", "orange"])
                
            results.append([f"{'✅' if web_found else '⚠️'} Website (www.ca-holland.nl) {'gevonden' if web_found else 'niet vermeld'}", "green" if web_found else "orange"])

            results.append(["\n🎨 HUISSTIJL & KLEURENMATRIX", "bold"])
            if green_ratio > 0.5:
                results.append([f"ℹ️ Huisstijlgroen gedetecteerd op {green_ratio:.1f}% van de flyer.", "bold"])
                if color_deviation <= 35:
                    results.append(["✅ Groen-kleurspectrum komt exact overeen met de CA-huisstijl (#00594F)", "green"])
                else:
                    results.append([f"⚠️ Gedetecteerd groen wijkt af van officiële CA-huisstijl (Afwijking: {color_deviation:.1f} > 35)", "orange"])
            else:
                results.append(["ℹ️ Neutrale flyer: Geen of nauwelijks CA-huisstijlgroen gebruikt.", "bold"])

            # --- EINDOORDEEL ---
            results.append(["\n" + "=" * 64, "bold"])
            results.append(["📌 EINDCONCLUSIE & ADVIES", "bold", "blue"])
            results.append(["=" * 64, "bold"])
            
            # De flyer wordt ALLEEN afgekeurd als het Logo óf de 6e traditie ontbreekt!
            if not logo_found or not tradition_found:
                results.append(["❌ FLYER AFGEKEURD VOOR DISTRIBUTIE", "red"])
                results.append(["\nReden: De flyer mist kritieke juridische of spirituele basiselementen", "bold"])
                if not logo_found:
                    results.append(" -> De naam 'Cocaine Anonymous' of het logo ontbreekt ter identificatie.")
                if not tradition_found:
                    results.append(" -> De verplichte 6e Traditie-tekst inzake niet-verbondenheid ontbreekt of is onleesbaar.")
            else:
                results.append(["✅ FLYER GOEDGEKEURD VOOR DISTRIBUTIE", "green"])
                results.append(["\nDit bestand voldoet aan alle kritieke eisen van CA Holland.", "bold"])
                if not date_found or not time_found or not address_found:
                    results.append("⚠️ Let op: Controleer handmatig of de waarschuwingen omtrent datum/tijd/locatie cruciaal zijn voor dit specifieke evenement.")

            # Update Textbox in GUI
            self.update_results_box(results)
            self.status_var.set("✅ Controle succesvol voltooid!")
            
        except Exception as e:
            self.update_results_box([[f"❌ FOUT TIJDENS ANALYSE: {str(e)}", "red"]])
            self.status_var.set("❌ Fout opgetreden")
        finally:
            self.check_btn.config(state=tk.NORMAL, text="🔍 Start Controle")
            
    def update_results_box(self, results):
        self.results_text.delete(1.0, tk.END)
        for item in results:
            if isinstance(item, list):
                text = item[0]
                tag = item[1] if len(item) > 1 else ""
                self.results_text.insert(tk.END, text + "\n", tag)
            else:
                self.results_text.insert(tk.END, item + "\n")
        self.results_text.see(tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    app = CAFlyerCheckerApp(root)
    root.mainloop()
