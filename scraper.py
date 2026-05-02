import ssl
import certifi
import os
import json
from datetime import date

os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

URL_LOGIN = "https://www.arterre.net/coop/"
URL_COTATIONS = "https://www.arterre.net/coop/mes-apports/bourse-aux-cereales/cotations"

# --- Identifiants : depuis variables d'environnement ou valeurs directes ---
LOGIN = os.environ.get("ARTERRE_LOGIN", "votre_identifiant")
MOT_DE_PASSE = os.environ.get("ARTERRE_PASSWORD", "votre_mot_de_passe")

# --- Campagnes à récupérer ---
ANNEES_RECOLTE = ["2026", "2027"]

# --- Cultures à récupérer ---
CULTURES_CIBLES = {
    "BLES POLYVALENTS": "Blé",
    "COLZA D'HIVER": "Colza",
    "OP 2R RGT PLANET(ORGETTE)": "Orge",
    "ESC KWS FARO(ORGETTE)": "Escourgeon",
    "TOURNESOL OLEIQUE": "Tournesol"
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_sheet():
    """Connexion Google Sheets depuis variable d'environnement ou fichier local."""
    gsheet_creds = os.environ.get("GSHEET_CREDENTIALS")
    if gsheet_creds:
        creds_dict = json.loads(gsheet_creds)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        print("  ✅ Credentials chargés depuis variable d'environnement")
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        print("  ✅ Credentials chargés depuis fichier local")
    gc = gspread.authorize(creds)
    return gc.open("dashboard_agricole").worksheet("prix_vivescia")

def get_iframe(page):
    """Récupère la frame contenant les cotations."""
    for frame in page.frames:
        if "mesapports.arterre.net" in frame.url:
            return frame
    return None

def attendre_iframe_avec_select(page, max_tentatives=10, delai=5000):
    """Attend que l'iframe soit chargée, avec rechargement de page si nécessaire."""
    for essai_page in range(3):
        print(f"⏳ Attente du chargement de l'iframe (essai {essai_page+1}/3)...")
        for i in range(max_tentatives):
            frame = get_iframe(page)
            if frame:
                selects = frame.query_selector_all("select")
                if len(selects) > 0:
                    print(f"  ✅ Iframe chargée avec {len(selects)} select(s) après {i+1} tentative(s)")
                    return frame
            print(f"  Tentative {i+1}/{max_tentatives} — iframe pas encore prête...")
            page.wait_for_timeout(delai)

        print(f"  ⚠️ Iframe non trouvée — rechargement de la page...")
        page.goto(URL_COTATIONS, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(5000)

        try:
            page.click("text=Poursuivre", timeout=3000)
            page.wait_for_timeout(2000)
        except:
            pass

    print("❌ Impossible de charger l'iframe après 3 rechargements")
    return None

def extraire_prix(cellule_texte):
    """Extrait le premier prix numérique d'une cellule."""
    prix_texte = cellule_texte.split("\n")[0].strip()
    prix_texte = prix_texte.split("(")[0].strip()
    return prix_texte

def attendre_tableau(frame, page, nb_lignes_min=5, max_tentatives=20, delai=5000):
    """Attend que le tableau soit chargé avec suffisamment de lignes."""
    print("⏳ Attente du rechargement du tableau...")
    for tentative in range(max_tentatives):
        page.wait_for_timeout(delai)
        lignes_test = frame.query_selector_all("table tr")
        print(f"  Tentative {tentative+1} : {len(lignes_test)} lignes détectées")
        if len(lignes_test) > nb_lignes_min:
            print("  ✅ Tableau chargé !")
            return True
    print("  ⚠️ Tableau non chargé après toutes les tentatives")
    return False

def scrape_annee(frame, page, annee):
    """Scrape les prix pour une année donnée."""
    prix_recuperes = {}

    print(f"\n📅 Sélection de l'année {annee}...")
    selects = frame.query_selector_all("select")
    selects[0].select_option(label=annee)
    print(f"  ✅ Année {annee} sélectionnée")
    page.wait_for_timeout(3000)

    print("🔄 Clic sur ACTUALISER...")
    frame.click("text=ACTUALISER")

    tableau_ok = attendre_tableau(frame, page)
    if not tableau_ok:
        print(f"  ❌ Tableau non chargé pour {annee}")
        return prix_recuperes

    print(f"\n💰 Recherche des prix pour {annee}...")
    lignes = frame.query_selector_all("table tr")

    for ligne in lignes:
        cellules = ligne.query_selector_all("td")
        if not cellules:
            continue

        th = ligne.query_selector("th")
        if th:
            nom_ligne = th.inner_text().strip().upper()
        else:
            nom_ligne = cellules[0].inner_text().strip().upper()
            nom_ligne = nom_ligne.split("\n")[0].strip()

        for cle, nom_culture in CULTURES_CIBLES.items():
            if nom_culture in prix_recuperes:
                continue
            if cle.upper() == nom_ligne:
                prix_texte = extraire_prix(cellules[0].inner_text().strip())
                try:
                    prix = float(prix_texte.replace(",", ".").replace(" ", ""))
                    prix_recuperes[nom_culture] = prix
                    print(f"  ✅ {nom_culture} : {prix} €/t")
                except ValueError:
                    print(f"  ⚠️ Prix non lisible pour {nom_culture} : '{prix_texte}'")

    for cle, nom in CULTURES_CIBLES.items():
        if nom not in prix_recuperes:
            print(f"  ❌ {nom} ({cle}) : non trouvé")

    return prix_recuperes

def scrape_toutes_annees():
    resultats = {}

    # Mode headless automatique si on est sur GitHub Actions
    est_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    headless = True if est_github_actions else False
    print(f"🖥️ Mode headless : {headless}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        # --- Connexion ---
        print("🌐 Ouverture du site Arterre...")
        page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(3000)

        try:
            page.click("text=Poursuivre", timeout=5000)
            print("  ✅ Cookies acceptés")
            page.wait_for_timeout(2000)
        except:
            pass

        print("🔐 Connexion en cours...")
        page.fill("input[placeholder='Utilisateur']", LOGIN)
        page.fill("input[placeholder='Mot de passe']", MOT_DE_PASSE)
        page.click("text=CONNEXION")
        page.wait_for_timeout(6000)

        try:
            page.click("text=×", timeout=3000)
            print("  ✅ Popup fermée")
            page.wait_for_timeout(1000)
        except:
            pass

        # --- Navigation vers les cotations ---
        print("📊 Navigation vers les cotations...")
        page.goto(URL_COTATIONS, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(5000)

        try:
            page.click("text=Poursuivre", timeout=3000)
            page.wait_for_timeout(2000)
        except:
            pass

        # --- Attendre l'iframe ---
        frame = attendre_iframe_avec_select(page, max_tentatives=10, delai=5000)
        if not frame:
            browser.close()
            return {}

        # --- Scraper chaque année ---
        for annee in ANNEES_RECOLTE:
            print(f"\n{'='*50}")
            print(f"  CAMPAGNE {annee}")
            print(f"{'='*50}")
            prix_annee = scrape_annee(frame, page, annee)
            resultats[annee] = prix_annee

        browser.close()

    return resultats

def push_to_sheets(resultats):
    print("\n📤 Envoi vers Google Sheets...")
    ws = get_sheet()
    today = date.today().isoformat()

    for annee, prix_dict in resultats.items():
        print(f"\n  Campagne {annee} :")
        for culture, prix in prix_dict.items():
            ws.append_row([today, culture, prix, annee])
            print(f"    ✅ {culture} : {prix} €/t → Sheets")

    print("\n✅ Terminé !")

if __name__ == "__main__":
    resultats = scrape_toutes_annees()
    if resultats:
        push_to_sheets(resultats)
    else:
        print("❌ Aucun prix récupéré.")