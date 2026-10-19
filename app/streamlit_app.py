"""BhuNetra app (Phase 5, heat only). Run from the repo root:  streamlit run app/streamlit_app.py"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)   # configs/ and data/ are read relative to the repo root

import pandas as pd
import pydeck as pdk
import streamlit as st

from bhunetra import nlq
from bhunetra.features.heat import load_yaml
from bhunetra.service import BAND_STYLE, band, build_replay, contributions, find_inputs, uncertainty_note

T = {
 "en": dict(title="BhuNetra: heat risk for India", sub="Research prototype. Heat only (rain, air quality, fire are not built yet).",
   disclaimer="Not an official warning system. Follow IMD / NDMA / local authorities.",
   replay="REPLAY of real past data (through {d}). This is NOT live.", snap="Offline snapshot dated {d}, bundled with the project.",
   lang="Language", date="Pick a day", horizon="Days ahead", dist="District", low="Low", moderate="Moderate", high="High",
   map="Heat risk on {d}, {h} day(s) ahead", top="Highest-risk districts", happened="What actually happened",
   yes="Heat event occurred", no="No heat event", why="Why this risk?", info="About this layer (source, licence, limits)",
   q="Ask a question (English)", qph="Which districts in Uttar Pradesh have high heat risk tomorrow?", sqlh="Query that was run",
   unc="Typical uncertainty: the 80% range of next-day maximum temperature is about {w:.1f} C wide (measured on 2024, coverage {c:.0%}).",
   because="Heat risk is {lvl} mainly because {a} and {b}.", why_low="Heat risk is low because {r}.",
   low_a="today's maximum {v:.1f} C is below the {m:.0f} C minimum for a heat event", low_b="temperature is only {v:.1f} C above normal (a heat event needs {m:.1f} C or more)",
   low_c="temperature is {v:.1f} C below normal", none="No districts match.", prob="Probability",
   f_tmax="today's maximum temperature is {v:.1f} C", f_dep="temperature is {a:.1f} C {w} normal", f_m3="the 3-day average maximum is {v:.1f} C",
   above="above", below="below", n_tmax="Today's max", n_dep="Above normal", n_m3="3-day average", chart_series="Push toward heat",
   chart_cap="Taller bar = this factor raises the heat risk more. Bars below zero lower it. (Units: log-odds, from the logistic model.)", sample="Only 60 sampled districts are covered, not all 735.",
   limits=["Source: Open-Meteo Historical Weather API (ERA5-based reanalysis, about 25 km grid). Licence CC BY 4.0, non-commercial use.",
           "District outlines: geoBoundaries (ODbL). Country borders on the background map come from CARTO/OpenStreetMap. Both may differ from official Indian maps; this project takes no position on disputed borders.",
           "Heat event = IMD-style rule on grid temperature, simplified (see docs/targets.md). Not station data.",
           "The model uses past days only (no weather forecast). It is weak at spotting the FIRST day of a heat spell.",
           "Risk bands (Low below 10%, High from 40%) are a display choice, not official alert levels."]),
 "hi": dict(title="भूनेत्र: भारत में गर्मी का जोखिम", sub="शोध प्रोटोटाइप। अभी सिर्फ़ गर्मी (बारिश, हवा की गुणवत्ता, आग अभी नहीं बने)।",
   disclaimer="यह आधिकारिक चेतावनी प्रणाली नहीं है। IMD / NDMA / स्थानीय प्रशासन के निर्देश मानें।",
   replay="यह पिछले असली डेटा का रीप्ले है ({d} तक)। यह लाइव नहीं है।", snap="ऑफ़लाइन स्नैपशॉट, तारीख {d}, प्रोजेक्ट के साथ आता है।",
   lang="भाषा", date="दिन चुनें", horizon="कितने दिन आगे", dist="ज़िला", low="कम", moderate="मध्यम", high="अधिक",
   map="{d} को गर्मी का जोखिम, {h} दिन आगे", top="सबसे ज़्यादा जोखिम वाले ज़िले", happened="असल में क्या हुआ",
   yes="गर्मी की लहर आई", no="गर्मी की लहर नहीं आई", why="यह जोखिम क्यों?", info="इस परत के बारे में (स्रोत, लाइसेंस, सीमाएँ)",
   q="सवाल पूछें (अंग्रेज़ी में)", qph="Which districts in Uttar Pradesh have high heat risk tomorrow?", sqlh="जो क्वेरी चली",
   unc="सामान्य अनिश्चितता: अगले दिन के अधिकतम तापमान की 80% सीमा लगभग {w:.1f} °C चौड़ी है (2024 पर मापा, कवरेज {c:.0%})।",
   because="गर्मी का जोखिम {lvl} है, मुख्य कारण: {a}, और {b}।", why_low="गर्मी का जोखिम कम है क्योंकि {r}।",
   low_a="आज का अधिकतम तापमान {v:.1f} °C है, जो गर्मी की लहर के लिए ज़रूरी {m:.0f} °C से कम है", low_b="तापमान सामान्य से सिर्फ़ {v:.1f} °C ज़्यादा है (गर्मी की लहर के लिए {m:.1f} °C या ज़्यादा चाहिए)",
   low_c="तापमान सामान्य से {v:.1f} °C कम है", none="कोई ज़िला नहीं मिला।", prob="संभावना",
   f_tmax="आज का अधिकतम तापमान {v:.1f} °C है", f_dep="तापमान सामान्य से {a:.1f} °C {w} है", f_m3="पिछले 3 दिनों का औसत अधिकतम तापमान {v:.1f} °C है",
   above="ज़्यादा", below="कम", n_tmax="आज का अधिकतम", n_dep="सामान्य से अधिक", n_m3="3 दिन का औसत", chart_series="गर्मी की ओर झुकाव",
   chart_cap="ऊँचा बार = यह कारण गर्मी का जोखिम ज़्यादा बढ़ाता है। शून्य से नीचे का बार जोखिम घटाता है। (इकाई: log-odds, लॉजिस्टिक मॉडल से।)", sample="सिर्फ़ 60 चुने हुए ज़िले शामिल हैं, सभी 735 नहीं।",
   limits=["स्रोत: Open-Meteo Historical Weather API (ERA5 आधारित, लगभग 25 किमी ग्रिड)। लाइसेंस CC BY 4.0, सिर्फ़ गैर-व्यावसायिक उपयोग।",
           "ज़िलों की सीमाएँ: geoBoundaries (ODbL)। पीछे के नक्शे की देश-सीमाएँ CARTO/OpenStreetMap से हैं। दोनों भारत के आधिकारिक नक्शों से अलग हो सकती हैं; विवादित सीमाओं पर यह प्रोजेक्ट कोई रुख नहीं लेता।",
           "गर्मी की लहर = ग्रिड तापमान पर IMD जैसा सरल नियम (docs/targets.md देखें)। यह स्टेशन डेटा नहीं है।",
           "मॉडल सिर्फ़ बीते दिनों का डेटा लेता है (मौसम पूर्वानुमान नहीं)। गर्मी के दौर का पहला दिन पहचानने में यह कमज़ोर है।",
           "जोखिम के स्तर (10% से कम = कम, 40% से ज़्यादा = अधिक) दिखाने का तरीका हैं, आधिकारिक अलर्ट नहीं।"]),
}

st.set_page_config(page_title="BhuNetra", page_icon="🛰", layout="centered")


@st.cache_resource(show_spinner="Loading data and fitting the default model...")
def load():
    inp = find_inputs(ROOT)
    return inp, build_replay(inp)


lang = "hi" if st.radio("Language / भाषा", ["English", "हिंदी"], horizontal=True) == "हिंदी" else "en"
t = T[lang]
cfg = load_yaml("configs/app.yaml")
st.title(t["title"]); st.caption(t["sub"])
st.warning(cfg["app"]["disclaimer"] if lang == "en" else t["disclaimer"])

try:
    inp, R = load()
except FileNotFoundError as e:
    st.error(f"DATA UNAVAILABLE: {e}")   # honest failure, never fake values
    st.stop()

tab = R["table"]
st.info(t["replay"].format(d=R["data_through"]))
if inp["mode"] == "snapshot":
    st.caption(t["snap"].format(d=inp["meta"]["fetched_at_utc_range"][1][:10]))
st.caption(t["sample"])

dates = sorted(tab["date"].dt.date.unique())
hot_day = tab.groupby(tab["date"].dt.date)["heat_today"].sum().idxmax()   # default: the day with most heat events
day = st.select_slider(t["date"], options=dates, value=hot_day)
h = st.radio(t["horizon"], [1, 2, 3], horizontal=True)
d = tab[tab["date"].dt.date == day].copy()
d["pct"] = (d[f"p{h}"] * 100).round(1)
d["band"] = d[f"p{h}"].map(lambda p: band(p, cfg))
d["color"] = d["band"].map(lambda b: BAND_STYLE[b]["color"])
d["radius"] = d["band"].map(lambda b: BAND_STYLE[b]["radius"])
d["label"] = d["band"].map({"low": t["low"], "moderate": t["moderate"], "high": t["high"]})

st.subheader(t["map"].format(d=day, h=h))
st.pydeck_chart(pdk.Deck(
    layers=[pdk.Layer("ScatterplotLayer", data=d[["lon", "lat", "name", "state", "pct", "label", "color", "radius"]],
                      get_position="[lon, lat]", get_fill_color="color", get_radius="radius", pickable=True,
                      stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1)],
    initial_view_state=pdk.ViewState(latitude=22.5, longitude=79, zoom=3.3),
    tooltip={"html": "<b>{name}</b>, {state}<br/>{label}: {pct}%"}))
dot = lambda b, px: f'<span style="display:inline-block;width:{px}px;height:{px}px;border-radius:50%;background:{BAND_STYLE[b]["hex"]};vertical-align:middle"></span>'
st.markdown(f"{dot('low', 10)} {t['low']} (&lt;10%) &nbsp;&nbsp; {dot('moderate', 14)} {t['moderate']} &nbsp;&nbsp; {dot('high', 18)} {t['high']} (≥40%)", unsafe_allow_html=True)
st.dataframe(d.sort_values("pct", ascending=False)[["name", "state", "pct", "label"]].head(10)
             .rename(columns={"name": t["dist"], "state": "State", "pct": f"% ({t['prob']})", "label": ""}),
             hide_index=True, width="stretch")

with st.expander("ⓘ " + t["info"]):
    for line in t["limits"]:
        st.write("• " + line)
    st.write(f"• {R['n_districts']} districts, data through {R['data_through']}.")

st.subheader(t["dist"])
names = sorted(d["name"] + " (" + d["state"].fillna("?") + ")")
top_name = (d.sort_values("pct", ascending=False).iloc[0]["name"] + " (" + str(d.sort_values("pct", ascending=False).iloc[0]["state"] if pd.notna(d.sort_values("pct", ascending=False).iloc[0]["state"]) else "?") + ")")
pick = st.selectbox(t["dist"], names, index=names.index(top_name), label_visibility="collapsed")
row = d[(d["name"] + " (" + d["state"].fillna("?") + ")") == pick].iloc[0]
c = st.columns(3)
for i, k in enumerate((1, 2, 3)):
    c[i].metric(f"+{k}d", f"{row[f'p{k}'] * 100:.0f}%", {"low": t["low"], "moderate": t["moderate"], "high": t["high"]}[band(row[f'p{k}'], cfg)], delta_color="off")
tgt = row[f"heat_h{h}"]
st.write(f"**{t['happened']} (+{h}d):** " + (t["yes"] if tgt == 1 else t["no"]))

st.markdown(f"**{t['why']}**")
cb = contributions(R["models"][h], row)
fact = {"tmax": t["f_tmax"].format(v=row["tmax"]),
        "departure": t["f_dep"].format(a=abs(row["departure"]), w=t["above"] if row["departure"] >= 0 else t["below"]),
        "tmax_mean3": t["f_m3"].format(v=row["tmax_mean3"])}
bnd = band(row[f"p{h}"], cfg)
lvl = {"low": t["low"], "moderate": t["moderate"], "high": t["high"]}[bnd]
if bnd == "low":
    # Low risk: explain from the documented event rule (distance to the 40 C / +4.5 C thresholds), not model coefficients.
    th = load_yaml("configs/thresholds.yaml")["heat"]
    tmin, dmin = th["region_min_tmax_c"]["plains"], th["departure_heat_wave_c"]
    if row["tmax"] < tmin:
        why = t["low_a"].format(v=row["tmax"], m=tmin)
    elif row["departure"] < 0:
        why = t["low_c"].format(v=abs(row["departure"]))
    else:
        why = t["low_b"].format(v=row["departure"], m=dmin)
    st.write(t["why_low"].format(r=why))
else:
    order = cb.sort_values(ascending=False).index[:2]      # biggest pushes TOWARD heat
    st.write(t["because"].format(lvl=lvl, a=fact[order[0]], b=fact[order[1]]))
st.bar_chart(cb.rename(index={"tmax": t["n_tmax"], "departure": t["n_dep"], "tmax_mean3": t["n_m3"]}).rename(t["chart_series"]))
st.caption(t["chart_cap"])
u = uncertainty_note()
if u:
    st.caption(t["unc"].format(w=u[1]["width"], c=u[1]["coverage"]))

st.subheader(t["q"])
question = st.text_input(t["q"], placeholder=t["qph"], label_visibility="collapsed")
if question:
    try:
        states = sorted(tab["state"].dropna().unique())
        spec = nlq.parse(question, states, cfg["risk_bands"])
        sql, params, out = nlq.run(tab, pd.Timestamp(day), spec)
        st.caption(f"{spec['level']} (≥{spec['min_p']:.0%}), {spec['horizon']} day(s), state: {spec['state'] or 'all'}")
        st.dataframe(out, hide_index=True, width="stretch") if len(out) else st.write(t["none"])
        with st.expander(t["sqlh"]):
            st.code(sql, language="sql"); st.write("params:", [str(p) for p in params])
    except nlq.Unparsed as e:
        st.warning(str(e))
