# CA Drukwerk Checker v3

Controleert Nederlandstalig CA PI-drukwerk (flyers, posters, ander drukwerk)
automatisch op de eisen voor goedkeuring.

## Wat wordt gecontroleerd

**Verplicht voor goedkeuring:**
- Het officiële logo, **onveranderd gebruikt**:
  - de vorm komt overeen met de officiële referentie
  - de achtergrond BINNEN de buitenste cirkel (de open ruimtes tussen letters/
    ringen) is één egale kleur — er mag geen foto, patroon of kleurverloop
    doorheen schijnen
  - de inkt (ring, letters, ringtekst) is één egale kleur — geen effecten
    (schaduw, gloed, kleurovergang)
  - geen vervorming: de verhouding tussen breedte- en hoogte-as moet kloppen
    (het logo is een cirkel, dus mag niet zijn uitgerekt)
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

## Het logo: hoe en waarom dit anders werkt dan tekstherkenning

Eerdere versies vergeleken tegen 12 kant-en-klare kleurvarianten (PNG's).
Dat bleek niet te doen wat er eigenlijk gevraagd wordt: of het logo
*onveranderd* is gebruikt, ongeacht in welke kleur. Deze versie werkt
fundamenteel anders:

1. **Referentie = 2 vervangbare PDF's**, niet 12 vaste plaatjes — zie
   `logo_reference/`. Uit elke referentie-PDF wordt bij het inladen
   automatisch afgeleid:
   - de **buitenste ring** (via de contour met de grootste omcirkelende
     straal — dit isoleert de hoofdring van een eventueel los ™/®-teken
     dat er los naast staat),
   - een **inktmasker** (waar de ring/letters/tekst staan) en een
     **gatmasker** (de open ruimtes daartussen, binnen de buitenste cirkel).
2. Op de pagina wordt eerst met een Hough-cirkeldetectie gezocht naar
   cirkelvormige kandidaten (alle officiële varianten zijn een cirkelvormig
   zegel). De sterkste kandidaten worden vervolgens **lokaal verfijnd**
   (positie én schaal, met coördinaat-afdaling) — dit bleek in de praktijk
   nodig: Hough's eerste schatting lokaliseert het logo goed, maar niet
   pixel-nauwkeurig genoeg om de dunne inktlijnen betrouwbaar te bemonsteren.
3. Op de best uitgelijnde kandidaat wordt vervolgens getoetst:
   - **vormgelijkenis** (vervaagde randcorrelatie tegen de referentie),
   - **kleur-egaliteit van de achtergrond** binnen de buitenste cirkel
     (gesampled op de exacte gat-posities uit de referentie; gemeten via de
     mediaankleur, niet het gemiddelde — een minderheid rand-/antialiasing-
     pixels trekt een gemiddelde scheef terwijl de mediaan de dominante
     kleur blijft weerspiegelen),
   - **kleur-egaliteit van de inkt** zelf (dezelfde methode, op de inkt-
     posities),
   - **aspectratio** (ellips-fit op de gevonden randen; een onvervormd logo
     geeft een as-verhouding dicht bij 1.0).

Alle vier moeten slagen voor `compliant: True`. Alleen de vorm vinden
(`found: True`) is dus niet voldoende voor goedkeuring — precies zoals
bedoeld: een gestretcht logo, of een logo met een foto zichtbaar door de
transparante delen, wordt gevonden (de vorm klopt) maar afgekeurd (de
kleur- of vervormingscontrole faalt).

### Referentiebestanden vervangen (andere taal/regio)

Een ander land kan zijn eigen officiële logo-PDF's in `logo_reference/`
zetten, met dezelfde naamconventie (moet de woorden 'inner'/'outer' en
'tm'/'r' bevatten, bv. `English_-_Outer_TM.pdf`). Geen codewijziging nodig
— de app leest bij elke wijziging van de bestandsinhoud automatisch opnieuw
in (zie hieronder, "Caching").

De PDF moet **transparantie** bevatten (de inkt ondoorzichtig, de rest van
de pagina transparant) — dat is hoe het inkt-/gatmasker wordt afgeleid.

### Caching (en waarom dit eerder een KeyError veroorzaakte)

Elke referentie wordt gecachet op basis van een hash van de bestandsinhoud
plus een schemaversie (`LOGO_REFERENCE_SCHEMA_VERSION` in `app.py`). Dat
lost een eerdere bug op: een simpele `@st.cache_resource` op een dunne
wrapper-functie werd niet automatisch ongeldig na een code-wijziging aan de
onderliggende laadfunctie (Streamlit hasht de broncode van de gedecoreerde
functie zelf, niet die van de functies die zij aanroept) — waardoor een
oude, verouderde datastructuur in het geheugen bleef hangen na een deploy en
alsnog gebruikt werd, met een `KeyError` tot gevolg. Nu breekt zowel een
gewijzigd PDF-bestand (de hash verandert) als een schemawijziging in de code
(handmatig ophogen) de cache af.

### Snelheid

De verfijningsstap (positie/schaal-optimalisatie) is rekenintensief: reken
op **15–30 seconden** per analyse, afhankelijk van de complexiteit van de
achtergrond. Dit is een bewuste afweging: een snellere, minder precieze
uitlijning gaf op echt fotomateriaal onbetrouwbare kleur-egaliteitsscores
(zie code-comments bij `_refine_candidate`). Verdere versnelling is
mogelijk (bv. minder kandidaten verfijnen, of de zoekstappen groter maken)
maar gaat ten koste van betrouwbaarheid — neem contact op als dit in de
praktijk te traag blijkt.

## Hoe de tekstcontroles werken (geen betaalde API's nodig)

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

1. Push deze map (inclusief de `logo_reference/`-map met de 2 officiële
   referentie-PDF's) naar een GitHub-repo.
2. Koppel de repo op [share.streamlit.io](https://share.streamlit.io).
3. Streamlit Cloud leest automatisch `requirements.txt` (Python-packages) én
   `packages.txt` (systeempakketten via apt — hier gebruikt voor Tesseract +
   het Nederlandse taalpakket). Geen verdere configuratie nodig.

## Mappenstructuur

```
ca_checker/
├── app.py                  # De volledige applicatie
├── requirements.txt        # Python-dependencies
├── packages.txt            # Systeempakketten (Tesseract) voor Streamlit Cloud
├── README.md
├── logo_reference/         # De officiële logo-referentie(s) — vervangbaar
│   ├── Dutch_-_..._Inner_TM.pdf
│   └── Dutch_-_..._Outer_TM.pdf
└── docs/
    └── C.A.-Brand-Guidelines-2025.pdf   # Alleen ter documentatie, niet
                                          # door de app ingelezen
```

## Bekende beperkingen

- CMYK/bleed-controle is alleen zinvol bij een PDF-upload; een los JPG/PNG is
  per definitie RGB en geeft daarom altijd de melding om het PDF-bestand aan
  te leveren of eerst de bleed/CMYK-tool te gebruiken.
- De naamdetectie is een heuristiek (regex op twee opeenvolgende
  hoofdletterwoorden) en kan enkele valse meldingen geven (bv. bij
  straatnamen). Dit is bewust een waarschuwing, geen harde afkeuring.
- OCR-kwaliteit hangt af van scan-/exportresolutie. Voor de beste resultaten:
  upload een PDF of een afbeelding van minimaal 150 DPI.
- De logo-verificatie is getest op één echt fotomateriaal-voorbeeld
  (flyer met foto-achtergrond) plus synthetische testgevallen. Bij zeer
  ongebruikelijke achtergronden (extreme patronen, zeer lage resolutie) kan
  de vorm-/aspectratio-diagnostiek minder betrouwbaar worden — de kleur-
  egaliteitscontroles blijven in dat geval de doorslaggevende, betrouwbare
  signalen.
