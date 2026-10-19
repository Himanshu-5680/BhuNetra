<p align="center">
  <img src="docs/readme-banner.svg" alt="BhuNetra. Earth's eye on India's hazards. Real public data. Plain words." width="100%">
</p>

<p align="center">
  <img alt="Real public data only" src="https://img.shields.io/badge/data-real%20public%20sources-111111?style=for-the-badge">
  <img alt="No API key for the core page" src="https://img.shields.io/badge/core%20page-no%20API%20key-5294ff?style=for-the-badge&labelColor=111111">
  <img alt="English and Hindi" src="https://img.shields.io/badge/language-English%20%2B%20Hindi-facc00?style=for-the-badge&labelColor=111111">
  <img alt="Not an official warning" src="https://img.shields.io/badge/status-not%20an%20official%20warning-ff4d50?style=for-the-badge&labelColor=111111">
</p>

BhuNetra means **earth's eye**. It is an open research project for India: one place where a person can read heat, rain, air, and recent earthquakes, see which public source produced each number, and open that same response.

It is not a government site. It is not an IMD, CPCB, or NDMA warning. In an emergency, call **112**.

## Vision

India already has hazard information. It is scattered, often in a technical dialect, and easy to mistake for an official alert when a page looks official.

BhuNetra is the opposite bet.

| | |
|---|---|
| **01** | A resident, a student, or an NGO worker can type a city and read the number in plain English or Hindi. |
| **02** | Every number names its source, its time, and what it is not. |
| **03** | A researcher can rerun the heat work, compare it with a simple baseline, and see where it fails. |
| **04** | If a source does not answer, the card stays empty. A missing value is never filled with zero. |

The long aim is a multi-hazard platform: heat, wind, rain, fire, and earthquakes, with a reason next to each figure. The public page today shows the layers that can be fetched with no key. The research code today is a heat study on a sample of districts, not a national warning model.

Three readers are the point of the project:

- a beginner who wants to see how real data moves from a public API to a screen
- a citizen or NGO worker who needs a number they can check
- a scientist who needs the split, the baseline, and the failure written down

## What a search shows

The public page asks four named sources. Nothing else.

| Stamp | What you read | Source | What it is not |
|---|---|---|---|
| **NOW / HEAT** | Model temperature now, and the highest of the next three daily values | [Open-Meteo Forecast](https://open-meteo.com/) | Not a street sensor. Not an IMD heatwave declaration. |
| **RAIN** | Sum of daily precipitation over those three days | Open-Meteo Forecast | Not a flood warning. |
| **AIR** | Current US AQI and PM2.5 | [Open-Meteo Air Quality](https://open-meteo.com/) (CAMS) | Not the Indian CPCB scale. The model is coarse, about 45 km over India. |
| **QUAKES** | Count of magnitude 3+ events within 300 km, last 30 days | [USGS catalogue](https://earthquake.usgs.gov/) | Not a prediction. Zero events is not a safety certificate. |

Under the city name, **Check this yourself** lists the coordinates and an **Open JSON** link for each request. The number on the card should be in that file.

Fires are not drawn. NASA FIRMS needs a key, and a keyless page does not invent detections. There is no 0–100 risk index, because that would need a population layer joined in the open. This page does not load one.

## Design

The interface takes its colours, border, radius, and press from [neobrutalism components](https://www.neobrutalism.dev/) ([ekmas/neobrutalism-components](https://github.com/ekmas/neobrutalism-components)), then gives each colour a job on a hazard page.

| Colour | Hex | Job on this site |
|---|---|---|
| Page blue | `#d6e9fe` | The paper. Same family as the library background. |
| Action blue | `#5294ff` | A button, the word NETRA, rain on hover. Black text stays on it. |
| Caution yellow | `#facc00` | The top warning bar, and quake cards on hover. |
| Heat red | `#ff4d50` | A high reading, and heat cards on hover. |
| Air green | `#05e17a` | Clearer air, and air cards on hover. |
| Ink | `#111111` | The 2px frame and the 4px hard shadow. |

Resting controls sit 4px up and to the left of a solid shadow. Hover moves them `4px` down and right and removes the shadow, in `160ms` with an ease-out curve. That is the library button: `hover:translate-x-boxShadowX hover:translate-y-boxShadowY hover:shadow-none`.

The same press is on the nav, language and theme buttons, search, source cards, result cards, and the live/cached stamps. Source cards also change colour as they press: forecast red, air green, place search blue, earthquakes yellow.

Dark mode keeps those four accents and flips the paper to near-black, with a blue shadow so the press is still visible. The eye mark in the header and in the browser tab is a small blue-and-yellow iris, in the spirit of the BhuNetra logo. The locator map is a schematic. It is not a survey and it is not a statement about any boundary.

## Run the public page

From the folder that contains `serve.py` and `bhunetra.html` (one level above this package in the local project):

```bash
python serve.py
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/).

`serve.py` calls only the four endpoints above. It fetches weather, air, and quakes together, and keeps a successful answer in memory for 10 minutes. A second search for the same place can come back from that cache, and the stamp says **cached** rather than pretending the network was instant. If you open the HTML file without the server, the page asks those same sources from the browser.

Python 3.11 or newer. The page server uses the standard library only.

## Run the research package

From this directory:

```bash
pip install -e ".[app,dev,ml]"
pytest
streamlit run app/streamlit_app.py
```

The Streamlit app is a **replay** of bundled past weather for the heat study. Its banner says it is not live. The default heat model is a 3-feature logistic regression, chosen because it beat LightGBM on PR-AUC in the checks we ran. LightGBM stays in the repo as a comparison.

On days a heat spell starts, that logistic model caught **19%** one day ahead, **11%** two days ahead, and **25%** three days ahead. Those figures are onset recall on the 2024 test, not an overall accuracy. The sample is **60** districts, not all of India. Because onset detection is weak, the public page shows the source forecast instead of that model's probability.

Details live in `reports/heat_results.md`, `docs/decisions.md`, and `DATA_SOURCES.md`.

## Hindi

The public page carries the same facts in Hindi and English. Switch with **हिंदी** in the header. The research notes in this repository are in English.

भूनेत्र का अर्थ है धरती की आँख। यह भारत के लिए एक खुला शोध पृष्ठ है। शहर लिखो। गर्मी, बारिश, हवा और हाल के भूकंप असली सार्वजनिक स्रोतों से आते हैं। हर अंक बताता है कि वह कहाँ से आया, और वह क्या नहीं है। यह IMD, CPCB या NDMA की चेतावनी नहीं है। आपात स्थिति में 112 डायल करें।

## Principles

1. Real public data, or an honest empty card.
2. No guessed endpoint. The page and `serve.py` call only documented URLs.
3. No single accuracy badge. A model that misses most onset days does not get to wear one.
4. No account, no API key, and no sign-up for the core page.
5. Official instructions outrank this screen.

## License

MIT. Open-Meteo forecast and archive data are free for non-commercial use under their terms (CC BY 4.0). Credit the upstream source when you reuse a number.
