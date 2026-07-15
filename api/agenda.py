"""
Fonction serverless Vercel — Agenda unifié
===========================================
Agrège trois sources en un seul flux :
  - Notion          → les chronos où Christophe est affecté
  - Google Calendar → agenda perso Gmail
  - Outlook / Graph → agenda pro Oxybol

Accessible sur : /api/agenda?code=XXXX

Variables d'environnement attendues (Vercel) :
  ACCESS_CODE
  NOTION_TOKEN
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
  MS_CLIENT_ID, MS_TENANT_ID, MS_REFRESH_TOKEN
"""

from http.server import BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import hmac
from datetime import date, datetime, timedelta, timezone

NOTION_DB_ID  = "5d07a861-e0a1-4362-8a10-d4ce61acad0c"
CHRISTOPHE_ID = "345ad871-6b2c-4534-b79a-889b6dabec3d"

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
        attendu = os.environ.get("ACCESS_CODE", "")

        # compare_digest : évite de révéler le code par le temps de réponse
        if not attendu or not hmac.compare_digest(fourni, attendu):
            self._json({"error": "unauthorized", "events": []}, status=401)
            return

        # --- Collecte des trois sources -------------------------------
        events  = []
        erreurs = []

        for nom, fonction in (
            ("notion",  _notion),
            ("google",  _google),
            ("outlook", _outlook),
        ):
            try:
                events.extend(fonction())
            except Exception as e:
                # Une source en panne ne doit pas tuer les deux autres
                erreurs.append(f"{nom}: {e}")

        events.sort(key=lambda e: (e["start"], e["title"]))

        self._json({
            "events":      events,
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

def _notion():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN absent")

    debut, _ = _bornes()

    body = {
        "filter": {
            "and": [
                {"property": "Chronométreur", "people": {"contains": CHRISTOPHE_ID}},
                {"property": "Date",          "date":   {"on_or_after": debut.isoformat()}},
                {"property": "Statut",        "select": {"does_not_equal": "Annulé"}},
                {"property": "Statut",        "select": {"does_not_equal": "Perdu"}},
            ]
        },
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

            out.append({
                "source":   "notion",
                "title":    titre,
                "start":    start,
                "end":      (d.get("end") or "")[:10] or None,
                "allDay":   True,
                "url":      page.get("url", ""),
                "statut":   (p.get("Statut", {}).get("select") or {}).get("name", ""),
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

    # 1. Lister les agendas de l'utilisateur
    cals = _req(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        headers=hdr,
    )

    out = []

    for cal in cals.get("items", []):
        cal_id  = cal.get("id")
        cal_nom = cal.get("summary", "")

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


# ══════════════════════════════════════════════════════════════════════
#  Source 3 — Outlook / Microsoft Graph
# ══════════════════════════════════════════════════════════════════════

def _ms_token():
    cid    = os.environ.get("MS_CLIENT_ID")
    tenant = os.environ.get("MS_TENANT_ID")
    refr   = os.environ.get("MS_REFRESH_TOKEN")

    if not all((cid, tenant, refr)):
        raise RuntimeError("variables Microsoft incomplètes")

    # Client public : pas de client_secret
    data = _req(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "client_id":     cid,
            "refresh_token": refr,
            "grant_type":    "refresh_token",
            "scope":         "offline_access Calendars.Read",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST", form=True,
    )
    return data["access_token"]


def _outlook():
    token = _ms_token()
    hdr = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="Europe/Paris"',
    }

    debut, fin = _bornes()

    params = urllib.parse.urlencode({
        "startDateTime": f"{debut.isoformat()}T00:00:00",
        "endDateTime":   f"{fin.isoformat()}T00:00:00",
        "$select":       "subject,start,end,isAllDay,location,webLink",
        "$orderby":      "start/dateTime",
        "$top":          "250",
    })

    url = f"https://graph.microsoft.com/v1.0/me/calendarView?{params}"
    out = []

    while url:
        data = _req(url, headers=hdr)

        for ev in data.get("value", []):
            s = (ev.get("start") or {}).get("dateTime", "")[:19]
            e = (ev.get("end")   or {}).get("dateTime", "")[:19]
            all_day = ev.get("isAllDay", False)

            out.append({
                "source":  "outlook",
                "title":   ev.get("subject") or "(sans titre)",
                "start":   s[:10] if all_day else s,
                "end":     e[:10] if all_day else e,
                "allDay":  all_day,
                "url":     ev.get("webLink", ""),
                "lieu":    ((ev.get("location") or {}).get("displayName") or ""),
            })

        url = data.get("@odata.nextLink")

    return out
