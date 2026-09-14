# CA Drukwerk Checker v2

Controleert Nederlandstalig CA PI-drukwerk (flyers, posters, ander drukwerk)
automatisch op de eisen voor goedkeuring.

## Wat wordt gecontroleerd

**Verplicht voor goedkeuring:**
- Gebruik van een officieel Nederlands CA-logo (in elke kleur-/achtergrondvariant)
- De letterlijke 6de-Traditie-zin, met detectie van spelfouten/afwijkingen
  (bekende schrijfvarianten zoals "6e" i.p.v. "6de" en "CA" i.p.v. "C.A."
  worden geaccepteerd, zie `WORD_VARIANT_MAP` in `app.py`)
- Correcte hulplijn, e-mailadres en website — **alleen als ze vermeld staan**.
  Opmaakvarianten (spaties/streepjes/hoofdletters, met of zonder www./https://)
  zijn toegestaan; een verkeerd cijfer of een typfout in het domein niet.

**Aanbevolen (indien van toepassing op het drukwerk):**
- "Georganiseerd door"-vermelding
- Adres/locatie of Zoomlink
- Datum en tijd

**Waarschuwing (Traditie 12 - anonimiteit):**
- Volledige namen (voornaam + achternaam voluit). "Voornaam A." wordt niet gevlagd.

**Print-gereedheid (alleen betrouwbaar bij een PDF-upload):**
- CMYK-kleurruimte
- Snijranden (bleed) t.o.v. standaard papierformaten
- Verwijst naar de bestaande bleed/CMYK-tool als het bestand nog niet klaar is

## Hoe het werkt (geen betaalde API's nodig)

- **Logo-detectie**: shape-based (edge/contour) template matching op meerdere
  schalen. Werkt onafhankelijk van de kleurvariant (wit/zwart/groene outline,
  transparante/witte/groene achtergrond), omdat alleen de vorm van het logo
  wordt vergeleken, niet de kleur.
- **Tekstcontrole**: OCR via Tesseract (Nederlandse taalset) + woord-voor-woord
  vergelijking met de verplichte zin. Afwijkingen worden per woord getoond
  ("gevonden: X → verwacht: Y"), zodat je zelf kunt beoordelen of het een
  echte spelfout is of een OCR-leesfout.
- **PDF-ondersteuning**: via PyMuPDF (geen systeemafhankelijkheden zoals
  poppler nodig — belangrijk voor gratis/shared hosting).

Alles werkt **zonder enige API-sleutel**. Optioneel kan in de zijbalk een
OpenAI-compatibele API-sleutel (bv. een gratis Groq-sleutel) worden ingevuld
om de tekstcontroles aanvullend te laten verfijnen door een taalmodel — dit
is nooit verplicht.

## Lokaal draaien

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Tesseract OCR moet apart op het systeem geïnstalleerd worden (dit is geen
Python-package):

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-nld

# macOS (homebrew)
brew install tesseract tesseract-lang
```

Start de app:

```bash
streamlit run app.py
```

## Deployen op Streamlit Community Cloud (gratis)

1. Push deze map (inclusief de `assets/`-map met de 12 officiële logo's) naar
   een GitHub-repo.
2. Koppel de repo op [share.streamlit.io](https://share.streamlit.io).
3. Streamlit Cloud leest automatisch `requirements.txt` (Python-packages) én
   `packages.txt` (systeempakketten via apt — hier gebruikt voor Tesseract +
   het Nederlandse taalpakket). Geen verdere configuratie nodig.

## Mappenstructuur

```
ca_checker/
├── app.py              # De volledige applicatie
├── requirements.txt    # Python-dependencies
├── packages.txt        # Systeempakketten (Tesseract) voor Streamlit Cloud
├── README.md
└── assets/             # De 12 officiële Nederlandse CA-logovarianten
    └── Dutch_-_*.png
```

Voeg je hier later extra officiële logovarianten toe (bv. een vernieuwd
ontwerp), plaats het PNG-bestand gewoon in `assets/` — de app pikt het
automatisch op bij de eerstvolgende herstart.

## Bekende beperkingen

- CMYK/bleed-controle is alleen zinvol bij een PDF-upload; een los JPG/PNG is
  per definitie RGB en geeft daarom altijd de melding om het PDF-bestand aan
  te leveren of eerst de bleed/CMYK-tool te gebruiken.
- De naamdetectie is een heuristiek (regex op twee opeenvolgende
  hoofdletterwoorden) en kan enkele valse meldingen geven (bv. bij
  straatnamen). Dit is bewust een waarschuwing, geen harde afkeuring.
- OCR-kwaliteit hangt af van scan-/exportresolutie. Voor de beste resultaten:
  upload een PDF of een afbeelding van minimaal 150 DPI.
