# IFC Geom Checker — MVP

Geometriska modellkontroller som IDS inte klarar.

## Första regeln

**`wall_top_reaches_slab_above`** + **`wall_bottom_reaches_slab_below`**
Innervägg ska nå UK bjälklag ovan och ÖK bjälklag under.

## Filstruktur

```
ifc-geom-checker/
├── app.py                  # Streamlit-UI
├── geometry.py             # bbox-extraktion från IFC
├── rules.py                # regellogik
├── requirements.txt
├── .python-version         # låser Python-version på Streamlit Cloud
├── .streamlit/
│   └── config.toml         # upload-limit 500 MB
└── .gitignore
```

## Köra lokalt

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy på Streamlit Community Cloud

1. Pusha repo:t till GitHub (publikt eller anslut privat repo)
2. Gå till https://share.streamlit.io och koppla repot
3. Sätt "Main file path" till `app.py`
4. Python-versionen läses från `.python-version`

**Varning: RAM-tak.** Streamlit Cloud ger ~1 GB RAM per app. `ifcopenshell.geom.create_shape` mot en stor projekt-IFC kan slå i taket. Om det händer: kör lokalt eller på Pi istället, eller sänk scope till en våning per körning.

## Arkitektur

| Fil | Ansvar |
|---|---|
| `geometry.py` | Extraktion av bbox från IFC. Ingen regellogik. |
| `rules.py` | Regler som tar bbox-data och returnerar violations. Ingen IFC-läsning. |
| `app.py` | Streamlit-UI. Laddar upp, anropar de andra två. Ingen logik. |

Separationen gör att regler kan testas utan IFC-filer, och nya regler kan läggas till i `rules.py` utan att röra UI.

## Begränsningar i MVP

- **Ingen XY-overlap-matchning** — en vägg matchas mot närmaste bjälklag i Z. Ger falska positiva för väggar vid fasad om ytterbjälklag saknas.
- **Innerväggsfilter**: Utesluter endast väggar där `Pset_WallCommon.IsExternal = True`.
- **Enhet antas vara meter**. Om projektet är i mm måste `unit_factor_to_mm` i `rules.py` justeras.
- **Ingen BCF-export** — tabell i UI.
- **Ingen parallellkörning** — seriell loop, inte `ifcopenshell.geom.iterator`.

## Nästa steg

1. Kör på en projekt-IFC, se vad som flaggas
2. Lägg till XY-overlap om falska positiva stör
3. BCF-export
4. Fler regler: övergolv vid vägg, tillval/frånval
5. Parallell iterator för fart
