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
    layout="wide"
)

# --- Connexion Google Sheets ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# --- Fonctions utilitaires ---
def fr_to_float(valeur):
    """Convertit une valeur française (virgule) en float."""
    try:
        valeur_str = str(valeur).strip()
        # Cas : séparateur de milliers avec point et décimale avec virgule (ex: 1.210,5)
        if "," in valeur_str and "." in valeur_str:
            valeur_str = valeur_str.replace(".", "").replace(",", ".")
        # Cas : virgule seule comme décimale (ex: 210,5)
        elif "," in valeur_str:
            valeur_str = valeur_str.replace(",", ".")
        # Cas : point seul comme décimale (ex: 210.5) — on laisse tel quel
        return float(valeur_str)
    except:
        return 0.0

def float_to_fr(valeur, decimales=2):
    """Convertit un float en chaîne française avec virgule."""
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")

@st.cache_data(ttl=300)
def load_data():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open("dashboard_agricole")

    prix_df = pd.DataFrame(sh.worksheet("prix_vivescia").get_all_records())
    ventes_df = pd.DataFrame(sh.worksheet("ventes").get_all_records())
    params_df = pd.DataFrame(sh.worksheet("parametres").get_all_records())

    # Conversion des colonnes numériques avec virgule
    prix_df["date"] = pd.to_datetime(prix_df["date"])
    prix_df["prix"] = prix_df["prix"].apply(fr_to_float)

    ventes_df["date"] = pd.to_datetime(ventes_df["date"])
    ventes_df["quantite"] = ventes_df["quantite"].apply(fr_to_float)
    ventes_df["prix_vente"] = ventes_df["prix_vente"].apply(fr_to_float)

    params_df["surface"] = params_df["surface"].apply(fr_to_float)
    params_df["rendement_moyen"] = params_df["rendement_moyen"].apply(fr_to_float)
    params_df["volume_total_estime"] = params_df["volume_total_estime"].apply(fr_to_float)

    return prix_df, ventes_df, params_df

# --- Titre + bouton rafraîchir ---
col_titre, col_refresh = st.columns([5, 1])
with col_titre:
    st.title("🌾 Tableau de bord — Commercialisation des céréales")
with col_refresh:
    st.write("")
    st.write("")
    if st.button("🔄 Rafraîchir les données"):
        st.cache_data.clear()
        st.rerun()

# --- Chargement initial des données ---
try:
    prix_df_init, ventes_df_init, params_df_init = load_data()
except Exception as e:
    st.error(f"Erreur de connexion : {e}")
    st.stop()

# --- Sélecteur de campagne ---
annee_courante = str(datetime.now().year)
campagnes_disponibles = sorted(params_df_init["campagne"].unique().tolist())

if annee_courante in campagnes_disponibles:
    index_defaut = campagnes_disponibles.index(annee_courante)
else:
    index_defaut = len(campagnes_disponibles) - 1

campagne_selectionnee = st.selectbox(
    "📅 Campagne (année de récolte)",
    options=campagnes_disponibles,
    index=index_defaut
)

# --- Filtrage par campagne ---
prix_df = prix_df_init[prix_df_init["campagne"] == campagne_selectionnee]
ventes_df = ventes_df_init[ventes_df_init["campagne"] == campagne_selectionnee]
params_df = params_df_init[params_df_init["campagne"] == campagne_selectionnee].reset_index(drop=True)

# --- Vérification qu'il y a des cultures ---
nb_cultures = len(params_df)
if nb_cultures == 0:
    st.warning("Aucune culture trouvée pour cette campagne.")
    st.stop()

# --- Section 1 : Graphique prix + points de vente ---
st.subheader("📈 Évolution des prix Vivescia")

cultures = params_df["culture"].tolist()
culture_sel = st.selectbox("Sélectionnez une culture", cultures)

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
    legend=dict(orientation="h"),
    height=400
)

st.plotly_chart(fig, use_container_width=True, key="graphique_prix")

# --- Section 2 : Jauges d'engagement ---
st.subheader("📊 Taux d'engagement par culture")

NB_PAR_LIGNE = 3
lignes = [params_df.iloc[i:i+NB_PAR_LIGNE] for i in range(0, nb_cultures, NB_PAR_LIGNE)]

for ligne_df in lignes:
    cols = st.columns(NB_PAR_LIGNE)
    for j, (_, row) in enumerate(ligne_df.iterrows()):
        culture = row["culture"]
        volume_total = row["volume_total_estime"]
        vendu = ventes_df[ventes_df["culture"] == culture]["quantite"].sum()
        pct = (vendu / volume_total * 100) if volume_total > 0 else 0

        with cols[j]:
            st.metric(
                label=f"🌱 {culture}",
                value=f"{float_to_fr(pct, 1)} %",
                delta=f"{float_to_fr(vendu, 0)} t vendues / {float_to_fr(volume_total, 0)} t"
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
            fig_gauge.update_layout(height=200, margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig_gauge, use_container_width=True, key=f"gauge_{campagne_selectionnee}_{culture}")

# --- Section 3 : Prix Moyen Pondéré ---
st.subheader("💰 Prix Moyen Pondéré (PMP)")

lignes_pmp = [params_df.iloc[i:i+NB_PAR_LIGNE] for i in range(0, nb_cultures, NB_PAR_LIGNE)]

for ligne_df in lignes_pmp:
    cols_pmp = st.columns(NB_PAR_LIGNE)
    for j, (_, row) in enumerate(ligne_df.iterrows()):
        culture = row["culture"]
        v = ventes_df[ventes_df["culture"] == culture]

        with cols_pmp[j]:
            if not v.empty and v["quantite"].sum() > 0:
                pmp = (v["prix_vente"] * v["quantite"]).sum() / v["quantite"].sum()
                prix_jour = prix_df[prix_df["culture"] == culture]["prix"].iloc[-1] if not prix_df[prix_df["culture"] == culture].empty else 0
                delta = pmp - prix_jour
                st.metric(
                    label=f"PMP {culture}",
                    value=f"{float_to_fr(pmp)} €/t",
                    delta=f"{float_to_fr(delta)} € vs prix du jour"
                )
            else:
                st.metric(label=f"PMP {culture}", value="Aucune vente")

# --- Section 4 : Saisie d'une nouvelle vente ---
st.subheader("➕ Enregistrer une nouvelle vente")

with st.form("nouvelle_vente", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns(4)
    culture = col1.selectbox("Culture", cultures)
    quantite_saisie = col2.text_input("Quantité (t)", value="0", help="Utilisez la virgule : ex. 12,5")
    prix_saisie = col3.text_input("Prix (€/t)", value="0", help="Utilisez la virgule : ex. 423,5")
    date_vente = col4.date_input("Date de vente")
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
                creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
                gc = gspread.authorize(creds)
                sh = gc.open("dashboard_agricole")
                sh.worksheet("ventes").append_row([
                    str(date_vente),
                    culture,
                    str(quantite).replace(".", ","),
                    str(prix).replace(".", ","),
                    campagne_selectionnee
                ])
                st.success(f"✅ Vente enregistrée : {float_to_fr(quantite, 1)} t de {culture} à {float_to_fr(prix)} €/t")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Erreur lors de l'enregistrement : {e}")