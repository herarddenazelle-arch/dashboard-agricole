import ssl
import certifi
import os
from datetime import datetime
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials

# --- Configuration de la page ---
st.set_page_config(
    page_title="Pilotage Céréales",
    page_icon="🌾",
    layout="centered"
)

# CSS mobile-first
st.markdown("""
<style>
    /* Réduire les marges générales */
    .block-container { padding: 1rem 0.75rem 2rem; }

    /* Boutons pleine largeur et plus grands */
    div.stButton > button {
        width: 100%;
        padding: 0.75rem 1rem;
        font-size: 1.05rem;
        border-radius: 10px;
    }

    /* Inputs plus grands pour le touch */
    input[type="text"], input[type="number"] {
        font-size: 1.1rem !important;
        padding: 0.6rem !important;
    }

    /* Selectbox plus grand */
    div[data-baseweb="select"] { font-size: 1.05rem; }

    /* Titre principal */
    h1 { font-size: 1.5rem !important; line-height: 1.3; }
    h2, h3 { font-size: 1.2rem !important; }

    /* Metric plus lisible */
    div[data-testid="metric-container"] {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 0.75rem;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Connexion Google Sheets ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_credentials():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return creds

# --- Fonctions utilitaires ---
def fr_to_float(valeur):
    try:
        valeur_str = str(valeur).strip()
        if "," in valeur_str and "." in valeur_str:
            valeur_str = valeur_str.replace(".", "").replace(",", ".")
        elif "," in valeur_str:
            valeur_str = valeur_str.replace(",", ".")
        return float(valeur_str)
    except Exception:
        return 0.0

def float_to_fr(valeur, decimales=2):
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")

@st.cache_data(ttl=300)
def load_data():
    creds = get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open("dashboard_agricole")

    prix_df = pd.DataFrame(sh.worksheet("prix_vivescia").get_all_records())
    ventes_df = pd.DataFrame(sh.worksheet("ventes").get_all_records())
    params_df = pd.DataFrame(sh.worksheet("parametres").get_all_records())

    prix_df["date"] = pd.to_datetime(prix_df["date"])
    prix_df["prix"] = prix_df["prix"].apply(fr_to_float)

    ventes_df["date"] = pd.to_datetime(ventes_df["date"])
    ventes_df["quantite"] = ventes_df["quantite"].apply(fr_to_float)
    ventes_df["prix_vente"] = ventes_df["prix_vente"].apply(fr_to_float)

    params_df["surface"] = params_df["surface"].apply(fr_to_float)
    params_df["rendement_moyen"] = params_df["rendement_moyen"].apply(fr_to_float)
    params_df["volume_total_estime"] = params_df["volume_total_estime"].apply(fr_to_float)

    return prix_df, ventes_df, params_df

# --- Initialisation de la session ---
if "page" not in st.session_state:
    st.session_state.page = "selection"
if "campagne" not in st.session_state:
    st.session_state.campagne = None
if "culture" not in st.session_state:
    st.session_state.culture = None

# --- Chargement des données ---
try:
    prix_df_init, ventes_df_init, params_df_init = load_data()
except Exception as e:
    st.error(f"Erreur de connexion : {e}")
    st.stop()

# ============================================================
# PAGE 1 — Sélection campagne + culture
# ============================================================
if st.session_state.page == "selection":

    st.title("🌾 Pilotage Céréales")
    st.markdown("---")

    # Sélecteur campagne
    annee_courante = str(datetime.now().year)
    campagnes_disponibles = sorted(params_df_init["campagne"].unique().tolist())

    if annee_courante in campagnes_disponibles:
        index_defaut = campagnes_disponibles.index(annee_courante)
    else:
        index_defaut = len(campagnes_disponibles) - 1

    campagne_sel = st.selectbox(
        "📅 Campagne",
        options=campagnes_disponibles,
        index=index_defaut
    )

    # Filtrage cultures selon campagne
    params_camp = params_df_init[params_df_init["campagne"] == campagne_sel]
    cultures_dispo = params_camp["culture"].tolist()

    if not cultures_dispo:
        st.warning("Aucune culture trouvée pour cette campagne.")
        st.stop()

    # Sélecteur culture
    culture_sel = st.selectbox("🌱 Culture", options=cultures_dispo)

    st.markdown("")

    # Bouton navigation
    if st.button("📊 Voir le tableau de bord →"):
        st.session_state.campagne = campagne_sel
        st.session_state.culture = culture_sel
        st.session_state.page = "dashboard"
        st.rerun()

    # Bouton rafraîchir discret
    st.markdown("")
    if st.button("🔄 Rafraîchir les données"):
        st.cache_data.clear()
        st.rerun()

# ============================================================
# PAGE 2 — Tableau de bord (graphique + saisie vente)
# ============================================================
elif st.session_state.page == "dashboard":

    campagne_selectionnee = st.session_state.campagne
    culture_sel = st.session_state.culture

    # Filtrage données
    prix_df = prix_df_init[prix_df_init["campagne"] == campagne_selectionnee]
    ventes_df = ventes_df_init[ventes_df_init["campagne"] == campagne_selectionnee]
    params_df = params_df_init[params_df_init["campagne"] == campagne_selectionnee].reset_index(drop=True)

    cultures = params_df["culture"].tolist()

    # --- En-tête ---
    col_back, col_titre = st.columns([1, 4])
    with col_back:
        if st.button("← Retour"):
            st.session_state.page = "selection"
            st.rerun()
    with col_titre:
        st.markdown(f"### {culture_sel} — {campagne_selectionnee}")

    st.markdown("---")

    # --- Changement de culture rapide ---
    culture_sel = st.selectbox("🌱 Culture", options=cultures,
                                index=cultures.index(culture_sel) if culture_sel in cultures else 0,
                                key="culture_dashboard")
    st.session_state.culture = culture_sel

    # --- Infos de la culture ---
    row_info = params_df[params_df["culture"] == culture_sel]
    if not row_info.empty:
        surface = row_info.iloc[0]["surface"]
        rendement = row_info.iloc[0]["rendement_moyen"]
        col_s, col_r = st.columns(2)
        col_s.metric("📐 Surface", f"{float_to_fr(surface, 1)} ha")
        col_r.metric("📦 Rendement moyen", f"{float_to_fr(rendement, 1)} t/ha")

    # --- Graphique prix + ventes ---
    st.subheader("📈 Prix Vivescia & mes ventes")

    prix_culture = prix_df[prix_df["culture"] == culture_sel].sort_values("date")
    ventes_culture = ventes_df[ventes_df["culture"] == culture_sel]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=prix_culture["date"],
        y=prix_culture["prix"],
        mode="lines+markers",
        name="Prix Vivescia",
        line=dict(color="#2196F3", width=2)
    ))
    fig.add_trace(go.Scatter(
        x=ventes_culture["date"],
        y=ventes_culture["prix_vente"],
        mode="markers",
        name="Mes ventes",
        marker=dict(size=14, color="#FF5722", symbol="star")
    ))
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Prix (€/t)",
        yaxis=dict(tickformat=",.2f"),
        legend=dict(orientation="h", y=-0.25),
        height=350,
        margin=dict(t=20, b=60, l=10, r=10)
    )
    st.plotly_chart(fig, use_container_width=True, key="graphique_prix")

    # --- Jauge engagement ---
    st.subheader("📊 Engagement")

    row = params_df[params_df["culture"] == culture_sel]
    if not row.empty:
        volume_total = row.iloc[0]["volume_total_estime"]
        vendu = ventes_df[ventes_df["culture"] == culture_sel]["quantite"].sum()
        pct = (vendu / volume_total * 100) if volume_total > 0 else 0

        st.metric(
            label=f"🌱 {culture_sel}",
            value=f"{float_to_fr(pct, 1)} %",
            delta=f"{float_to_fr(vendu, 0)} t / {float_to_fr(volume_total, 0)} t"
        )

        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=pct,
            number={"suffix": "%", "valueformat": ".1f"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#4CAF50"},
                "steps": [
                    {"range": [0, 33], "color": "#FFEBEE"},
                    {"range": [33, 66], "color": "#FFF9C4"},
                    {"range": [66, 100], "color": "#E8F5E9"},
                ],
                "threshold": {
                    "line": {"color": "red", "width": 3},
                    "thickness": 0.75,
                    "value": 80
                }
            }
        ))
        fig_gauge.update_layout(height=220, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_gauge, use_container_width=True, key=f"gauge_{campagne_selectionnee}_{culture_sel}")

    # --- PMP ---
    st.subheader("💰 Prix Moyen Pondéré")

    v = ventes_df[ventes_df["culture"] == culture_sel]
    if not v.empty and v["quantite"].sum() > 0:
        pmp = (v["prix_vente"] * v["quantite"]).sum() / v["quantite"].sum()
        prix_jour_serie = prix_df[prix_df["culture"] == culture_sel]["prix"]
        prix_jour = prix_jour_serie.iloc[-1] if not prix_jour_serie.empty else 0
        delta = pmp - prix_jour
        st.metric(
            label=f"PMP {culture_sel}",
            value=f"{float_to_fr(pmp)} €/t",
            delta=f"{float_to_fr(delta)} € vs prix du jour"
        )
    else:
        st.metric(label=f"PMP {culture_sel}", value="Aucune vente")

    st.markdown("---")

    # --- Saisie d'une nouvelle vente ---
    st.subheader("➕ Enregistrer une vente")

    with st.form("nouvelle_vente", clear_on_submit=True):
        culture_form = culture_sel
        quantite_saisie = st.text_input("Quantité (t)", value="0", help="Ex : 12,5")
        prix_saisie = st.text_input("Prix (€/t)", value="0", help="Ex : 423,5")
        date_vente = st.date_input("Date de vente")
        submitted = st.form_submit_button("✅ Enregistrer la vente")

        if submitted:
            quantite = fr_to_float(quantite_saisie)
            prix = fr_to_float(prix_saisie)

            if quantite <= 0:
                st.error("❌ La quantité doit être supérieure à 0.")
            elif prix <= 0:
                st.error("❌ Le prix doit être supérieur à 0.")
            else:
                try:
                    creds = get_credentials()
                    gc = gspread.authorize(creds)
                    sh = gc.open("dashboard_agricole")
                    sh.worksheet("ventes").append_row([
                        str(date_vente),
                        culture_form,
                        str(quantite).replace(".", ","),
                        str(prix).replace(".", ","),
                        campagne_selectionnee
                    ])
                    st.success(
                        f"✅ Vente enregistrée : {float_to_fr(quantite, 1)} t de {culture_form} "
                        f"à {float_to_fr(prix)} €/t"
                    )
                    st.cache_data.clear()
                except Exception as e:
                    st.error(f"Erreur lors de l'enregistrement : {e}")
