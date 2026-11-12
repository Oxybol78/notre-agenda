"""
Fonction serverless Vercel — Agenda unifié
===========================================
Agrège deux sources en un seul flux :
  - Notion          → les chronos où Christophe est affecté
  - Google Calendar → agenda perso Gmail

Accessible sur : /api/agenda?code=XXXX  (+ &mode=chronos pour le tableau de bord)

Accès : un code par personne. ACCESS_CODE = Christophe (Notion + Google perso) ;
Romain et Paul ont chacun un code (stocké ici sous forme d'empreinte SHA-256, le
dépôt étant public) : ils voient les chronos Notion de leur côté (« mes chronos »,
« avec qui je fais équipe »…), sans jamais l'agenda Google de Christophe.

Variables d'environnement attendues (Vercel) :
  ACCESS_CODE
  NOTION_TOKEN
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
"""

from http.server import BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import hmac
import hashlib
from datetime import date, datetime, timedelta, timezone

NOTION_DB_ID  = "5d07a861-e0a1-4362-8a10-d4ce61acad0c"
CHRISTOPHE_ID = "345ad871-6b2c-4534-b79a-889b6dabec3d"

# Équipe : identifiant Notion + empreinte SHA-256 du code d'accès de chaque personne.
# (Le dépôt est public : on ne stocke JAMAIS un code en clair.)
EQUIPE = {
    "romain": {"id":   "5b3af71b-23af-49ef-b1d5-f2c46d651124",
               "hash": "67649323ba9633b560b96ea9750ed493d9887cbe68de3d3ebd8583ae7a7ec038"},
    "paul":   {"id":   "3bd8fcdb-585d-43f0-94cd-6a1ee314bddd",
               "hash": "64511619b3696dfc405b9d4c26aca1017b46a884234f93ca07316a1cd9923269"},
}


def _profil(fourni):
    """Qui est-ce ? -> (nom, id Notion, accès Google) ou None si code inconnu."""
    f = fourni.encode("utf-8")
    empreinte = hashlib.sha256(f).hexdigest()
    trouve = None
    attendu = os.environ.get("ACCESS_CODE", "")
    # compare_digest : évite de révéler un code par le temps de réponse
    if attendu and hmac.compare_digest(f, attendu.encode("utf-8")):
        trouve = ("christophe", CHRISTOPHE_ID, True)
    for nom, p in EQUIPE.items():
        if hmac.compare_digest(empreinte, p["hash"]) and not trouve:
            trouve = (nom, p["id"], False)
    return trouve

# Fenêtre de temps affichée
JOURS_PASSE  = 7
JOURS_FUTUR  = 365


# ══════════════════════════════════════════════════════════════════════
#  Handler HTTP
# ══════════════════════════════════════════════════════════════════════

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # --- Contrôle du code d'accès ---------------------------------
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        fourni = (params.get("code") or [""])[0]

        profil = _profil(fourni)
        if not profil:
            self._json({"error": "unauthorized", "events": []}, status=401)
            return
        qui, uid, google = profil

        # --- Mode diagnostic : /api/agenda?code=XXXX&cals=1 -------------
        # Liste les agendas Google visibles, pour régler GOOGLE_CALENDARS.
        if (params.get("cals") or [""])[0] and google:
            try:
                token = _google_token()
                data = _req(
                    "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                    headers={"Authorization": f"Bearer {token}"},
                )
                noms = [
                    {"nom": c.get("summary", ""), "principal": c.get("primary", False)}
                    for c in data.get("items", [])
                ]
                self._json({"agendas_google": noms})
            except Exception as e:
                self._json({"error": str(e)}, status=500)
            return

        # --- Mode tableau de bord : /api/agenda?code=XXXX&mode=chronos ---
        # Tous les chronos Notion (pas seulement ceux de Christophe), &year=AAAA.
        if (params.get("mode") or [""])[0] == "chronos":
            try:
                an = (params.get("year") or [""])[0]
                an = int(an) if an.isdigit() and 2000 <= int(an) <= 2100 else date.today().year
                events = _notion_chronos(an, uid)
                events.sort(key=lambda e: (e["start"], e["title"]))
                self._json({
                    "events":      events,
                    "profil":      qui,
                    "errors":      [],
                    "last_update": datetime.now(timezone(timedelta(hours=2))).strftime("%H:%M"),
                })
            except Exception as e:
                self._json({"error": str(e), "events": [], "errors": [f"notion: {e}"]},
                           status=500)
            return

        # --- Mode « perdus » : fiches perdues / annulées / reportées sans date ---
        if (params.get("mode") or [""])[0] == "perdus":
            try:
                self._json({"perdus": _notion_perdus(), "errors": []})
            except Exception as e:
                self._json({"error": str(e), "perdus": [], "errors": [f"notion: {e}"]}, status=500)
            return

        # --- Collecte des deux sources --------------------------------
        events  = []
        erreurs = []

        sources = [("notion", lambda: _notion(uid))]
        if google:                     # l'agenda Google perso reste à Christophe
            sources.append(("google", _google))

        for nom, fonction in sources:
            try:
                events.extend(fonction())
            except Exception as e:
                # Une source en panne ne doit pas tuer l'autre
                erreurs.append(f"{nom}: {e}")

        events.sort(key=lambda e: (e["start"], e["title"]))

        self._json({
            "events":      events,
            "profil":      qui,
            "errors":      erreurs,
            "last_update": datetime.now(timezone(timedelta(hours=2))).strftime("%H:%M"),
        })

    # --- utilitaires ---------------------------------------------------

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# ══════════════════════════════════════════════════════════════════════
#  Helpers réseau
# ══════════════════════════════════════════════════════════════════════

def _req(url, data=None, headers=None, method="GET", form=False):
    if data is not None and not form:
        data = json.dumps(data).encode("utf-8")
    elif form:
        data = urllib.parse.urlencode(data).encode("utf-8")

    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _bornes():
    """Fenêtre [aujourd'hui - 7j, aujourd'hui + 365j]."""
    today = date.today()
    return today - timedelta(days=JOURS_PASSE), today + timedelta(days=JOURS_FUTUR)


# ══════════════════════════════════════════════════════════════════════
#  Source 1 — Notion (les chronos)
# ══════════════════════════════════════════════════════════════════════

def _notion(uid=CHRISTOPHE_ID):
    """Agenda partagé : uniquement les chronos où la personne est affectée."""
    debut, _ = _bornes()
    return _notion_pages({
        "and": [
            {"property": "Chronométreur", "people": {"contains": uid}},
            {"property": "Date",          "date":   {"on_or_after": debut.isoformat()}},
            {"property": "Statut",        "select": {"does_not_equal": "Annulé"}},
            {"property": "Statut",        "select": {"does_not_equal": "Perdu"}},
        ]
    }, uid)


def _notion_chronos(annee, uid=CHRISTOPHE_ID):
    """Tableau de bord : TOUS les chronos de la base (tag « Chrono »), tous statuts
    confondus, pour une année civile donnée (une année à la fois : requêtes
    légères). Le filtrage par statut se fait côté navigateur."""
    # La base mélange chronos, séminaires, congés, récups, télétravail, RDV...
    # Seuls les éléments taggés « Chrono » sont des chronos.
    pages = _notion_pages({
        "and": [
            {"property": "Date", "date": {"on_or_after": f"{annee}-01-01"}},
            {"property": "Date", "date": {"before":      f"{annee + 1}-01-01"}},
            {"property": "Tags", "multi_select": {"contains": "Chrono"}},
        ]
    }, uid)
    return [e for e in pages if not _est_tache(e["title"])]


# Fiches taguées « Chrono » qui sont en fait des tâches de préparation ou des tests
_TACHES = ("dossard", "collage", "corne de brume", "médaille", "medaille",
           "t-shirt", "tshirt", "personnalisation arche")


def _est_tache(titre):
    t = (titre or "").strip().lower()
    return t == "test" or t.startswith(_TACHES)


PERDUS = ("Perdu", "Annulé", "Reporté", "Déjà Client à relancer",
          "Client relancé en attente de retour")


def _date_synchro(texte):
    """La synchro Google Agenda garde la date de l'événement (AAAAMMJJ) dans le champ
    technique « Notion Automation Data », même quand la date Notion a été effacée."""
    import re
    m = re.search(r";(20\d{2})(\d{2})(\d{2});[a-z]+\s*$", texte or "")
    if not m:
        return ""
    a, mo, j = m.groups()
    return f"{a}-{mo}-{j}" if 1 <= int(mo) <= 12 and 1 <= int(j) <= 31 else ""


def _notion_perdus():
    """Fiches perdues / annulées / reportées dont la date a été effacée dans Notion.
    Année de rattachement : date de l'événement retrouvée dans la synchro Google
    (« historique »), sinon année de création de la fiche (« creation »)."""
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN absent")
    body = {
        "filter": {"and": [
            {"property": "Tags", "multi_select": {"contains": "Chrono"}},
            {"property": "Date", "date": {"is_empty": True}},
            {"or": [{"property": "Statut", "select": {"equals": st}} for st in PERDUS]},
        ]},
        "page_size": 100,
    }
    headers = {
        "Authorization":  f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    }
    out, cursor = [], None
    while True:
        if cursor:
            body["start_cursor"] = cursor
        data = _req(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                    data=body, headers=headers, method="POST")
        for page in data.get("results", []):
            p = page.get("properties", {})
            titre = "".join(b.get("plain_text", "")
                            for b in p.get("Evènement", {}).get("title", [])).strip()
            if _est_tache(titre):
                continue
            nad = "".join(b.get("plain_text", "")
                          for b in p.get("Notion Automation Data", {}).get("rich_text", []))
            d = _date_synchro(nad)
            cree = (page.get("created_time") or "")[:10]
            out.append({
                "statut": (p.get("Statut", {}).get("select") or {}).get("name", ""),
                "an":     int((d or cree)[:4] or 0),
                "date":   d,
                "source": "historique" if d else "creation",
                "title":  titre,
                "url":    page.get("url", ""),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def _notion_pages(filtre, uid=CHRISTOPHE_ID):
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN absent")

    body = {
        "filter": filtre,
        "page_size": 100,
        "sorts": [{"property": "Date", "direction": "ascending"}],
    }

    headers = {
        "Authorization":  f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    }

    out, cursor = [], None

    while True:
        if cursor:
            body["start_cursor"] = cursor

        data = _req(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            data=body, headers=headers, method="POST",
        )

        for page in data.get("results", []):
            p = page.get("properties", {})

            titre = "".join(
                b.get("plain_text", "") for b in p.get("Evènement", {}).get("title", [])
            ).strip()
            if not titre:
                continue

            d = p.get("Date", {}).get("date") or {}
            start = (d.get("start") or "")[:10]
            if not start:
                continue

            def ms(key):
                return [x.get("name", "") for x in p.get(key, {}).get("multi_select", [])]

            equipe = p.get("Chronométreur", {}).get("people", [])

            out.append({
                "source":   "notion",
                "title":    titre,
                "start":    start,
                "end":      (d.get("end") or "")[:10] or None,
                "allDay":   True,
                "url":      page.get("url", ""),
                "statut":   (p.get("Statut", {}).get("select") or {}).get("name", ""),
                "chronometreurs": [x.get("name", "") for x in equipe if x.get("name")],
                "nb_chrono":      len(equipe),
                "autres":         [x.get("name", "") for x in equipe
                                   if x.get("name") and x.get("id") != uid],
                "mine":           any(x.get("id") == uid for x in equipe),
                "tags":     ms("Tags"),
                "techno":   ms("Techno"),
                "materiel": ms("Matériel Chrono"),
                "type":     ms("Type Chrono"),
            })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return out


# ══════════════════════════════════════════════════════════════════════
#  Source 2 — Google Calendar
# ══════════════════════════════════════════════════════════════════════

def _google_token():
    cid    = os.environ.get("GOOGLE_CLIENT_ID")
    secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refr   = os.environ.get("GOOGLE_REFRESH_TOKEN")

    if not all((cid, secret, refr)):
        raise RuntimeError("variables Google incomplètes")

    data = _req(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id":     cid,
            "client_secret": secret,
            "refresh_token": refr,
            "grant_type":    "refresh_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST", form=True,
    )
    return data["access_token"]


def _google():
    token = _google_token()
    hdr   = {"Authorization": f"Bearer {token}"}

    debut, fin = _bornes()
    tmin = f"{debut.isoformat()}T00:00:00Z"
    tmax = f"{fin.isoformat()}T00:00:00Z"

    # Agendas à remonter. Vide = tous.
    # Ex. : GOOGLE_CALENDARS="Oxybol"  ou  "Oxybol,Famille"
    voulus = [
        c.strip().lower()
        for c in os.environ.get("GOOGLE_CALENDARS", "").split(",")
        if c.strip()
    ]

    # 1. Lister les agendas de l'utilisateur
    cals = _req(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        headers=hdr,
    )

    out = []

    for cal in cals.get("items", []):
        cal_id  = cal.get("id")
        cal_nom = cal.get("summary", "")

        # Filtre par nom d'agenda
        if voulus and cal_nom.strip().lower() not in voulus:
            continue

        # On saute les agendas de fêtes/anniversaires : trop de bruit
        if cal.get("id", "").endswith("#holiday@group.v.calendar.google.com"):
            continue
        if cal.get("id") == "addressbook#contacts@group.v.calendar.google.com":
            continue

        params = urllib.parse.urlencode({
            "timeMin":      tmin,
            "timeMax":      tmax,
            "singleEvents": "true",     # déplie les récurrences
            "orderBy":      "startTime",
            "maxResults":   "250",
        })

        page_token = None

        while True:
            url = (f"https://www.googleapis.com/calendar/v3/calendars/"
                   f"{urllib.parse.quote(cal_id)}/events?{params}")
            if page_token:
                url += f"&pageToken={page_token}"

            data = _req(url, headers=hdr)

            for ev in data.get("items", []):
                if ev.get("status") == "cancelled":
                    continue

                s = ev.get("start", {})
                e = ev.get("end", {})
                all_day = "date" in s

                out.append({
                    "source":   "google",
                    "title":    ev.get("summary", "(sans titre)"),
                    "start":    s.get("date") or s.get("dateTime", "")[:19],
                    "end":      e.get("date") or e.get("dateTime", "")[:19],
                    "allDay":   all_day,
                    "url":      ev.get("htmlLink", ""),
                    "lieu":     ev.get("location", ""),
                    "calendrier": cal_nom,
                })

            page_token = data.get("nextPageToken")
            if not page_token:
                break

    return out
