"""PhytoSense++ replay dashboard.   Run from repo root:  streamlit run dashboard/app.py
Replays logged data through a Python mirror of the firmware: quality gate -> bounded-memory baseline -> persistence alert."""
import os, sys
import numpy as np, pandas as pd, streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
sys.path.insert(0, os.path.dirname(__file__))
import engine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATASETS = {
    "v7 trial (2.7 h, firmware v7)": ("data/trial_v7.csv", None),
    "90-min preflight (2.6 h)": ("data/preflight_90min.csv", None),
    "Oct 18-19 clean run (16 h)": ("data/phytosense_trial_log.csv", "2026-10-18 07:33"),
    "Oct 13-14 railed front-end (fault case)": ("data/phytosense_trial_log.csv", "2026-10-13"),
}
LIME, GREEN, DARK, MUTED = "#b4dc3c", "#3f8f4e", "#1c2b22", "#6b7a72"

st.set_page_config(page_title="PhytoSense++", page_icon="🌿", layout="wide")

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Inter', system-ui, sans-serif; color: #1c2b22; }
.stApp { background: radial-gradient(1200px 600px at 10% -10%, #dcebe4 0%, rgba(220,235,228,0) 60%),
                     linear-gradient(135deg, #e6efeb 0%, #f3f7f5 55%, #e9f0ec 100%); }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], footer { visibility: hidden; }
.block-container { padding-top: 1.2rem; max-width: 1400px; }
section[data-testid="stSidebar"] { background: rgba(255,255,255,.72); backdrop-filter: blur(14px); border-right: 1px solid rgba(0,0,0,.05); }
section[data-testid="stSidebar"] * { color: #1c2b22; }
.topbar { display:flex; align-items:center; gap:14px; margin-bottom:6px; }
.logo { width:44px; height:44px; border-radius:50%; background:#fff; display:flex; align-items:center; justify-content:center;
        font-weight:700; font-size:20px; color:#3f8f4e; box-shadow:0 6px 18px rgba(40,80,60,.12); }
.chip { background:rgba(255,255,255,.8); border-radius:999px; padding:7px 16px; font-size:13px; color:#3b4a42; box-shadow:0 4px 14px rgba(40,80,60,.07); }
.chip .dot { color:#6fb43a; }
.stTabs [data-baseweb="tab-list"] { gap:10px; border:none; }
.stTabs [data-baseweb="tab"] { background:rgba(255,255,255,.65); border-radius:999px; padding:8px 22px; height:auto; color:#3b4a42; font-weight:500; }
.stTabs [aria-selected="true"] { background:#fff; box-shadow:0 6px 18px rgba(40,80,60,.12); color:#1c2b22; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
/* cards */
.st-key-card_green, .st-key-card_white, .st-key-card_gray, .st-key-card_plain {
  border-radius:26px; padding:18px 20px; box-shadow:0 14px 34px rgba(40,80,60,.10); }
.st-key-card_green { background: linear-gradient(160deg, #c3e45a 0%, #9fd043 100%); color:#17321c; }
.st-key-card_white { background:#fff; }
.st-key-card_gray  { background: linear-gradient(160deg, #8d9d92 0%, #7a8b80 100%); color:#fff; }
.st-key-card_plain { background:rgba(255,255,255,.85); }
.card-title { font-size:18px; font-weight:600; margin:0; }
.card-sub { font-size:12.5px; opacity:.75; margin:2px 0 6px 0; }
.badge { display:inline-block; background:#17321c; color:#fff; border-radius:999px; padding:3px 12px; font-size:12px; font-weight:600; }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px; }
.cell { background:#f4f7f5; border-radius:14px; padding:12px 14px; }
.cell .lbl { font-size:12.5px; color:#3b4a42; display:flex; gap:6px; align-items:center; }
.cell .val { font-size:19px; font-weight:600; margin-top:3px; color:#1c2b22; }
.cell .val small { font-size:12px; font-weight:400; color:#6b7a72; }
.hero { position:relative; height:440px; }
.hero h1 { font-size:34px; font-weight:300; margin:6px 0 0 4px !important; padding:0 !important; letter-spacing:-.5px; }
.hero h1 b { font-weight:600; }
.hero p { margin:4px 0 0 6px; color:#6b7a72; font-size:13.5px; }
.ring { position:absolute; left:50%; transform:translateX(-50%); top:95px; width:310px; height:310px; border-radius:50%;
        background: radial-gradient(circle at 35% 30%, rgba(255,255,255,.95), rgba(255,255,255,.35) 60%, rgba(255,255,255,.1));
        box-shadow: 0 0 60px rgba(255,255,255,.9), inset 0 0 30px rgba(255,255,255,.8); }
.plantsvg { position:absolute; left:50%; transform:translateX(-50%); top:78px; width:330px; }
.tag { position:absolute; background:rgba(255,255,255,.85); border-radius:14px; padding:8px 14px; box-shadow:0 8px 22px rgba(40,80,60,.10); }
.tag span { display:block; font-size:11.5px; color:#6b7a72; }
.tag b { font-size:17px; font-weight:600; }
.t1 { left:3%; top:175px; } .t2 { left:73%; top:150px; } .t3 { left:75%; top:290px; }
.ok { color:#2e8b4a; } .warn { color:#e08a00; } .bad { color:#d23b3b; }
.kpi { background:#fff; border-radius:20px; padding:14px 18px; box-shadow:0 10px 26px rgba(40,80,60,.08); }
.kpi .k { font-size:12.5px; color:#6b7a72; } .kpi .v { font-size:26px; font-weight:600; margin-top:2px; }
.note { background:rgba(255,255,255,.8); border-left:5px solid #b4dc3c; border-radius:14px; padding:12px 16px; font-size:13px; color:#3b4a42; margin-top:10px; }
[data-testid="stPlotlyChart"] { border-radius:16px; }

/* ---- force light colours even if the browser/Streamlit is in dark mode ---- */
:root { color-scheme: light; }
[data-testid="stWidgetLabel"] *, [data-testid="stCaptionContainer"] *, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3,
.stMarkdown p, [data-testid="stSidebar"] h3, [data-testid="stHeading"] * { color: #1c2b22 !important; }
div[data-baseweb="select"] > div { background:#ffffff !important; border-color:#d5e0da !important; }
div[data-baseweb="select"] * { color:#1c2b22 !important; }
[data-baseweb="popover"] ul, [data-baseweb="popover"] li, [data-baseweb="popover"] div[role="listbox"] { background:#ffffff !important; color:#1c2b22 !important; }
[data-baseweb="popover"] li:hover { background:#e8f3df !important; }
[data-testid="stSliderThumbValue"], [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] { color:#3f8f4e !important; }
.st-key-card_gray .stMarkdown p, .st-key-card_gray .stMarkdown div { color:#ffffff !important; }
.st-key-card_green .stMarkdown p { color:#17321c !important; }
.hero .stMarkdown p, .hero p { color:#6b7a72 !important; }
.hero h1, .hero h1 b { color:#1c2b22 !important; }
.badge { color:#ffffff !important; }
</style>
""", unsafe_allow_html=True)

PLANT_SVG = """<svg viewBox="0 0 320 340" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="lg1" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1f6b34"/><stop offset="1" stop-color="#6cbf4a"/></linearGradient>
<linearGradient id="lg2" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2d8a3e"/><stop offset="1" stop-color="#9ad35a"/></linearGradient>
<linearGradient id="pot" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ebe7df"/><stop offset=".5" stop-color="#fbfaf7"/><stop offset="1" stop-color="#e3ded4"/></linearGradient>
</defs>
<ellipse cx="170" cy="326" rx="95" ry="8" fill="#1c2b22" opacity=".10"/>
<path d="M165 255 C 95 235, 60 170, 95 105 C 135 135, 160 190, 165 255 Z" fill="url(#lg1)"/>
<path d="M170 255 C 120 210, 118 120, 170 40 C 205 100, 200 190, 170 255 Z" fill="url(#lg2)"/>
<path d="M175 255 C 230 225, 262 160, 240 90 C 195 120, 175 190, 175 255 Z" fill="url(#lg1)"/>
<path d="M165 262 C 100 270, 48 235, 40 190 C 95 190, 145 215, 165 262 Z" fill="url(#lg2)" opacity=".95"/>
<path d="M178 262 C 240 268, 292 238, 300 195 C 240 195, 192 220, 178 262 Z" fill="url(#lg2)" opacity=".95"/>
<path d="M170 255 L170 70" stroke="#e8f5d8" stroke-width="1.6" opacity=".55"/>
<path d="M100 262 Q100 322 170 324 Q240 322 240 262 Z" fill="url(#pot)"/>
<ellipse cx="170" cy="262" rx="70" ry="10" fill="#d8d3c8"/>
</svg>"""

# ---------------------------------------------------------------- sidebar
sb = st.sidebar
sb.markdown("### Controls")
name = sb.selectbox("Dataset", list(DATASETS))
z_thr = sb.slider("Deviation threshold |z| >", 2.0, 8.0, 3.0, 0.5)
persist = sb.slider("Persistence (consecutive samples)", 1, 60, 10)
sb.caption("Firmware default: z>3, persistence 10")
inj_kind = sb.selectbox("Inject a synthetic fault (demo)", ["none", "railed", "flatline", "spike", "step +6 SD"])
win_min = sb.slider("Window shown (minutes)", 5, 120, 30)

@st.cache_data(show_spinner="Loading data...")
def get_data(rel, start):
    d = engine.load(os.path.join(ROOT, rel), start)
    if rel.endswith("phytosense_trial_log.csv") and start == "2026-10-13":
        d = d[d["t"] < "2026-10-15"]
    return d.reset_index(drop=True)

@st.cache_data(show_spinner="Running replay...")
def get_run(rel, start, z, p, kind, i0):
    d = get_data(rel, start)
    bio = d["bioelectric_raw"].values.astype(float)
    if kind != "none": bio = engine.inject(bio, i0, kind)
    r = engine.run(bio, d["lo_plus"].values, d["lo_minus"].values, z, p)
    r["bio"] = bio
    return r

rel, start = DATASETS[name]
d = get_data(rel, start)
if len(d) < 400:
    st.error("Not enough rows in this dataset."); st.stop()
N = len(d)
pos = sb.slider("Position (sample index)", 0, N - 1, min(N // 2, N - 1), 60)
r = get_run(rel, start, z_thr, persist, inj_kind, pos)
r["t"] = d["t"].values
w = win_min * 60
a, b = max(0, pos - w // 2), min(N, pos + w // 2)
seg = r.iloc[a:b]; ds = d.iloc[a:b]
cur, row = r.iloc[pos], d.iloc[pos]

# ---------------------------------------------------------------- derived values
def num(v, fmt, lo=None, hi=None):
    try:
        v = float(v)
    except Exception:
        return "—"
    if np.isnan(v) or (lo is not None and not lo <= v <= hi): return "—"
    return fmt.format(v)

hrs = (d["t"].iloc[-1] - d["t"].iloc[0]).total_seconds() / 3600
onsets = int((r["alert"] & ~r["alert"].shift(1, fill_value=False)).sum())
rej = (r["reason"] != "none").mean() * 100
quality = (seg["reason"] == "none").mean() * 100
seg_alerts = int((seg["alert"] & ~seg["alert"].shift(1, fill_value=False)).sum())
if cur["alert"]: state, cls = "Deviation", "warn"
elif cur["reason"] != "none": state, cls = "Rejected: " + str(cur["reason"]), "bad"
elif cur["status"] == "cold_start": state, cls = "Learning baseline", "warn"
else: state, cls = "Healthy", "ok"
zt = num(cur["z"], "{:+.2f}")

def clean_fig(fig, h):
    fig.update_layout(height=h, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return fig

# ---------------------------------------------------------------- top bar
st.markdown(f'<div class="topbar"><div class="logo">P</div>'
            f'<div class="chip"><span class="dot">●</span>&nbsp; Live replay &nbsp;·&nbsp; {name}</div></div>',
            unsafe_allow_html=True)
tab_plant, tab_an = st.tabs(["My Plant", "Analytics"])

# ================================================================ MY PLANT
with tab_plant:
    left, right = st.columns([1.55, 1], gap="large")
    with left:
        tagcls = {"ok": "ok", "warn": "warn", "bad": "bad"}[cls]
        st.markdown(
            f'<div class="hero"><h1>Plant <b>Signal Monitor</b></h1>'
            f'<p>Real-time bioelectric stress monitoring &nbsp;·&nbsp; {pd.Timestamp(cur["t"]).strftime("%d %b %Y, %H:%M:%S")}</p>'
            f'<div class="ring"></div><div class="plantsvg">{PLANT_SVG}</div>'
            f'<div class="tag t1"><span>Bio level</span><b>{num(cur["bio"], "{:,.0f}")} ADC</b></div>'
            f'<div class="tag t2"><span>Plant state</span><b class="{tagcls}">{state}</b></div>'
            f'<div class="tag t3"><span>z-score</span><b>{zt}</b></div></div>',
            unsafe_allow_html=True)
        if inj_kind != "none":
            st.info(f"Synthetic **{inj_kind}** fault injected at the current position — see how the gate and alert react.")
    with right:
        with st.container(key="card_green"):
            st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:center">'
                        f'<div><p class="card-title">Signal Trend</p><p class="card-sub">Last {win_min} min around position</p></div>'
                        f'<span class="badge">{seg_alerts} alert{"s" if seg_alerts != 1 else ""}</span></div>', unsafe_allow_html=True)
            f1 = go.Figure(go.Scatter(x=seg["t"], y=seg["bio"], mode="lines", line=dict(color="#17321c", width=2),
                                      fill="tozeroy", fillcolor="rgba(255,255,255,.38)"))
            lo_, hi_ = np.nanmin(seg["bio"]), np.nanmax(seg["bio"]); pad = max((hi_ - lo_) * .15, 5)
            f1.update_yaxes(range=[lo_ - pad, hi_ + pad])
            st.plotly_chart(clean_fig(f1, 150), use_container_width=True, config={"displayModeBar": False})
        st.write("")
        with st.container(key="card_white"):
            st.markdown(
                '<p class="card-title">Plant Details</p><p class="card-sub">Real-time conditions</p>'
                '<div class="grid2">'
                f'<div class="cell"><div class="lbl">🌡️ Temperature</div><div class="val">{num(row["temp_c"], "{:.1f}", -10, 60)} <small>°C</small></div></div>'
                f'<div class="cell"><div class="lbl">💧 Humidity</div><div class="val">{num(row["humidity_pct"], "{:.0f}", 0, 100)} <small>%</small></div></div>'
                f'<div class="cell"><div class="lbl">⏲️ Air pressure</div><div class="val">{num(row["pressure_hpa"], "{:.0f}", 850, 1100)} <small>hPa</small></div></div>'
                f'<div class="cell"><div class="lbl">📶 Signal quality</div><div class="val">{quality:.0f} <small>% good</small></div></div>'
                '</div>', unsafe_allow_html=True)
        st.write("")
        with st.container(key="card_gray"):
            st.markdown(f'<div style="display:flex;justify-content:space-between"><div><p class="card-title">Live Signal</p>'
                        f'<p class="card-sub">Deviation from baseline, last 100 s</p></div>'
                        f'<div style="font-size:15px;opacity:.9">{pd.Timestamp(cur["t"]).strftime("%H:%M:%S")}</div></div>', unsafe_allow_html=True)
            tail = r.iloc[max(0, pos - 100):pos + 1]
            dev = (tail["bio"] - tail["bio"].median()).clip(-80, 80)
            colors = ["#ffb347" if al else "#e6efe3" for al in tail["alert"]]
            f2 = go.Figure(go.Bar(x=list(range(len(dev))), y=dev, marker_color=colors, marker_line_width=0))
            f2.update_layout(bargap=.35)
            st.plotly_chart(clean_fig(f2, 110), use_container_width=True, config={"displayModeBar": False})
    st.markdown('<div class="note"><b>Honest scope:</b> the soil channel is not shown (it tracks the bioelectric channel and is not validated); '
                'irrigation control is not part of this replay; stress detection on real plant events is not yet validated. '
                'Fault injection is synthetic.</div>', unsafe_allow_html=True)

# ================================================================ ANALYTICS
with tab_an:
    kc = st.columns(5)
    for col, (k, v) in zip(kc, [("Samples", f"{N:,}"), ("Duration", f"{hrs:.1f} h"), ("Rejected by gate", f"{rej:.1f}%"),
                                ("Alert events", f"{onsets}"), ("Alerts / hour", f"{onsets / hrs:.2f}")]):
        col.markdown(f'<div class="kpi"><div class="k">{k}</div><div class="v">{v}</div></div>', unsafe_allow_html=True)
    st.write("")
    with st.container(key="card_plain"):
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[.55, .22, .23], vertical_spacing=.05,
                            subplot_titles=("Bioelectric signal and baseline band (mean ± z·SD)", "z-score (good samples only)", "Temperature / humidity"))
        fig.add_trace(go.Scattergl(x=seg["t"], y=seg["bio"], mode="lines", name="bio (ADC counts)", line=dict(width=1.3, color=GREEN)), 1, 1)
        ok = seg["mean"].notna()
        if ok.any():
            up = seg["mean"] + z_thr * seg["sd"]; lo = seg["mean"] - z_thr * seg["sd"]
            fig.add_trace(go.Scatter(x=seg["t"][ok], y=up[ok], line=dict(width=0), showlegend=False, hoverinfo="skip"), 1, 1)
            fig.add_trace(go.Scatter(x=seg["t"][ok], y=lo[ok], fill="tonexty", line=dict(width=0), name="baseline band",
                                     fillcolor="rgba(180,220,60,.28)"), 1, 1)
        bad = seg["reason"] != "none"
        fig.add_trace(go.Scattergl(x=seg["t"][bad], y=seg["bio"][bad], mode="markers", name="rejected by gate",
                                   marker=dict(color="#d23b3b", symbol="x", size=5), text=seg["reason"][bad]), 1, 1)
        fig.add_trace(go.Scattergl(x=seg["t"][seg["alert"]], y=seg["bio"][seg["alert"]], mode="markers", name="ALERT",
                                   marker=dict(color="#ff9f1c", size=7)), 1, 1)
        fig.add_trace(go.Scattergl(x=seg["t"], y=seg["z"].clip(-10, 10), mode="lines", name="z", line=dict(width=1, color="#5b7f6a")), 2, 1)
        for s_ in (z_thr, -z_thr): fig.add_hline(y=s_, line_dash="dash", line_color="#d23b3b", row=2, col=1)
        fig.add_trace(go.Scattergl(x=ds["t"], y=ds["temp_c"].where(ds["temp_c"].between(-10, 60)), name="temp °C", line=dict(color="#e08a00")), 3, 1)
        fig.add_trace(go.Scattergl(x=ds["t"], y=ds["humidity_pct"].where(ds["humidity_pct"].between(0, 100)), name="humidity %", line=dict(color="#3a86c8")), 3, 1)
        fig.update_layout(height=720, margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h"),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter, sans-serif", color=DARK))
        fig.update_xaxes(gridcolor="rgba(0,0,0,.06)"); fig.update_yaxes(gridcolor="rgba(0,0,0,.06)")
        st.plotly_chart(fig, use_container_width=True)
    st.write("")
    l, rr = st.columns(2, gap="large")
    with l:
        st.subheader("Why the gate rejected samples")
        rc = r["reason"].value_counts().rename_axis("reason").reset_index(name="samples")
        st.dataframe(rc, hide_index=True, use_container_width=True)
    with rr:
        st.subheader("Alert events")
        ev = r[r["alert"] & ~r["alert"].shift(1, fill_value=False)][["t", "bio", "z"]].copy()
        ev[["bio", "z"]] = ev[["bio", "z"]].round(1)
        st.dataframe(ev.tail(50), hide_index=True, use_container_width=True)
    st.caption(f"Baseline memory: {engine.BASELINE_N} float32 samples = {engine.BASELINE_N * 4 / 1024:.1f} KB, constant regardless of run length. "
               "Firmware build: RAM 27,500 B (8.4%), Flash 362,893 B (10.9%) on ESP32-S3.")