"""Tests de l'API (sans réseau : Notion et Google sont simulés).

Lancer :  python3 -m unittest discover -s tests -v
"""
import hashlib
import http.server
import importlib.util
import json
import os
import pathlib
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

os.environ.update(ACCESS_CODE="code-christophe", NOTION_TOKEN="x")
_spec = importlib.util.spec_from_file_location(
    "agenda", pathlib.Path(__file__).resolve().parent.parent / "api" / "agenda.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

ROMAIN, PAUL, CHRISTOPHE = A.EQUIPE["romain"]["id"], A.EQUIPE["paul"]["id"], A.CHRISTOPHE_ID


def page(titre, debut, fin=None, statut="Validé", equipe=(), tags=("Chrono",), nad=""):
    return {
        "url": "https://www.notion.so/x", "created_time": "2025-03-01T10:00:00.000Z",
        "properties": {
            "Evènement": {"title": [{"plain_text": titre}]},
            "Date": {"date": ({"start": debut, "end": fin} if debut else None)},
            "Statut": {"select": {"name": statut}},
            "Chronométreur": {"people": [{"id": i, "name": n} for i, n in equipe]},
            "Tags": {"multi_select": [{"name": t} for t in tags]},
            "Notion Automation Data": {"rich_text": [{"plain_text": nad}] if nad else []},
        },
    }


class Faux:
    """Remplace A._req : enregistre les requêtes et renvoie des pages Notion."""
    def __init__(self, pages=(), erreurs=()):
        self.pages, self.erreurs, self.appels = list(pages), list(erreurs), []

    def __call__(self, url, data=None, headers=None, method="GET", form=False):
        self.appels.append((url, data))
        if "google" in url:
            raise RuntimeError("google indisponible (test)")
        if self.erreurs:
            raise self.erreurs.pop(0)
        return {"results": self.pages, "has_more": False}


class Serveur:
    def __init__(self, faux):
        self.old, A._req = A._req, faux
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), A.handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_port

    def get(self, qs="", code=None, entete=None):
        h = {"X-Access-Code": entete} if entete else {}
        url = f"http://127.0.0.1:{self.port}/api/agenda?{qs}" + (f"&code={code}" if code else "")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h)) as r:
                return r.status, json.load(r), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.load(e), e.headers

    def close(self):
        self.srv.shutdown(); A._req = self.old


class TestAcces(unittest.TestCase):
    def setUp(self):
        self.s = Serveur(Faux([page("Trail", "2026-12-01", equipe=[(ROMAIN, "Romain D"), (CHRISTOPHE, "Chris M")])]))
        os.environ["ACCESS_CODE"] = "code-christophe"
    def tearDown(self): self.s.close()

    def test_refus(self):
        for c in ("", "faux", "code-christophe%20", "CODE-CHRISTOPHE"):
            self.assertEqual(self.s.get(code=c)[0], 401, repr(c))
        self.assertEqual(self.s.get()[0], 401)

    def test_code_en_entete_ou_adresse(self):
        self.assertEqual(self.s.get(entete="code-christophe")[0], 200)
        self.assertEqual(self.s.get(code="code-christophe")[0], 200)

    def test_pas_de_cache_sur_les_donnees_privees(self):
        _, _, h = self.s.get(code="code-christophe")
        self.assertEqual(h["Cache-Control"], "no-store")

    def test_profils(self):
        self.assertEqual(A._profil("code-christophe"), ("christophe", CHRISTOPHE, True))
        self.assertIsNone(A._profil("é"))
        self.assertIsNone(A._profil(""))

    def test_mine_est_calcule_pour_la_bonne_personne(self):
        # un code d'équipe fabriqué pour le test
        code = "code-test-romain"
        old = A.EQUIPE["romain"]["hash"]
        A.EQUIPE["romain"]["hash"] = hashlib.sha256(code.encode()).hexdigest()
        try:
            s, d, _ = self.s.get("mode=chronos&year=2026", code=code)
        finally:
            A.EQUIPE["romain"]["hash"] = old
        ev = d["events"][0]
        self.assertEqual((s, d["profil"], ev["mine"], ev["autres"]), (200, "romain", True, ["Chris M"]))

    def test_equipe_sans_google(self):
        code = "code-test-paul"
        old = A.EQUIPE["paul"]["hash"]
        A.EQUIPE["paul"]["hash"] = hashlib.sha256(code.encode()).hexdigest()
        try:
            _, d, _ = self.s.get(code=code)
        finally:
            A.EQUIPE["paul"]["hash"] = old
        self.assertEqual(d["errors"], [])                       # Google n'a même pas été tenté

    def test_christophe_tente_bien_google(self):
        _, d, _ = self.s.get(code="code-christophe")
        self.assertTrue(any(e.startswith("google") for e in d["errors"]))   # contraste avec l'équipe

    def test_diagnostic_google_reserve_a_christophe(self):
        code = "code-test-paul"
        old = A.EQUIPE["paul"]["hash"]
        A.EQUIPE["paul"]["hash"] = hashlib.sha256(code.encode()).hexdigest()
        try:
            _, d, _ = self.s.get("cals=1", code=code)
        finally:
            A.EQUIPE["paul"]["hash"] = old
        self.assertNotIn("agendas_google", d)


class TestDonnees(unittest.TestCase):
    def test_taches_et_tests_exclus(self):
        for t in ("Dossards trail X", "Collage des puces Y", "test", "Test", "Médailles Z"):
            self.assertTrue(A._est_tache(t), t)
        for t in ("Trail des Roches", "Marathon de Paris", "Course du Dossard d'or"):
            self.assertFalse(A._est_tache(t), t)

    def test_chronos_filtre_les_taches(self):
        old, A._req = A._req, Faux([page("Trail", "2026-05-01"), page("Dossards Trail", "2026-04-20")])
        try:
            self.assertEqual([e["title"] for e in A._notion_chronos(2026)], ["Trail"])
        finally:
            A._req = old

    def test_date_synchro(self):
        n = "synced;a;b@group.calendar.google.com;id;h1;h2;x.y;z.w;1;x.y;20220925;single"
        self.assertEqual(A._date_synchro(n), "2022-09-25")
        for mauvais in ("", None, "synced;x;20221399;single", "abc", "synced;20220925"):
            self.assertEqual(A._date_synchro(mauvais), "", repr(mauvais))

    def test_perdus_rattaches_a_l_annee_de_l_evenement(self):
        nad = "synced;a;b;c;d;e;f;g;1;h;20220925;single"
        old, A._req = A._req, Faux([page("6h VTT", None, statut="Perdu", nad=nad),
                                    page("Sans synchro", None, statut="Annulé"),
                                    page("Dossards truc", None, statut="Perdu")])
        try:
            r = A._notion_perdus()
        finally:
            A._req = old
        self.assertEqual([(x["title"], x["an"], x["source"]) for x in r],
                         [("6h VTT", 2022, "historique"), ("Sans synchro", 2025, "creation")])

    def test_chrono_multi_jours_en_cours_reste_dans_l_agenda(self):
        auj = A._paris_now().date()
        en_cours = page("UTOI", (auj - timedelta(days=10)).isoformat(), (auj + timedelta(days=3)).isoformat())
        fini = page("Vieux", (auj - timedelta(days=20)).isoformat(), (auj - timedelta(days=15)).isoformat())
        recent = page("Hier", (auj - timedelta(days=2)).isoformat())
        old, A._req = A._req, Faux([en_cours, fini, recent])
        try:
            self.assertEqual([e["title"] for e in A._notion(CHRISTOPHE)], ["UTOI", "Hier"])
        finally:
            A._req = old

    def test_heure_de_paris(self):
        # Hiver = UTC+1, été = UTC+2 : l'ancien code figeait +2 toute l'année
        reel = A.datetime
        class H(datetime):
            @classmethod
            def now(cls, tz=None): return cls(*H.val, tzinfo=timezone.utc)
        A.datetime = H
        try:
            H.val = (2026, 11, 12, 12, 0); self.assertEqual(A._paris_now().hour, 13)
            H.val = (2026, 7, 12, 12, 0);  self.assertEqual(A._paris_now().hour, 14)
            H.val = (2026, 3, 29, 0, 59);  self.assertEqual(A._paris_now().hour, 1)    # avant le passage à l'heure d'été
            H.val = (2026, 3, 29, 1, 0);   self.assertEqual(A._paris_now().hour, 3)
            H.val = (2026, 10, 25, 0, 59); self.assertEqual(A._paris_now().hour, 2)    # encore l'été
            H.val = (2026, 10, 25, 1, 0);  self.assertEqual(A._paris_now().hour, 2)    # heure d'hiver
        finally:
            A.datetime = reel

    def test_nouvel_essai_sur_429(self):
        e429 = urllib.error.HTTPError("u", 429, "Too Many", {"Retry-After": "0"}, None)
        calls = {"n": 0}
        import io
        class Rep:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s): return b'{"ok": true}'
        def faux_open(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3: raise e429
            return Rep()
        old = A.urllib.request.urlopen
        A.urllib.request.urlopen = faux_open
        A._time.sleep = lambda s: None
        try:
            self.assertEqual(A._req("https://x"), {"ok": True}); self.assertEqual(calls["n"], 3)
        finally:
            A.urllib.request.urlopen = old


if __name__ == "__main__":
    unittest.main()
