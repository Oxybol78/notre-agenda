// Variables: icon-color: orange; icon-glyph: stopwatch;
// ─────────────────────────────────────────────────────────────
//  Oxybol — Mes prochains chronos  (widget Scriptable pour iPhone)
//
//  Lit l'API de « Notre Agenda » et affiche tes prochains chronos.
//  Au premier lancement, le script te demande l'adresse de l'app
//  et le code d'accès, puis les range dans le trousseau de l'iPhone.
// ─────────────────────────────────────────────────────────────

// ═══ À régler si besoin ══════════════════════════════════════
const SEULEMENT_MOI = true;   // true = mes chronos / false = tous les chronos
const STATUTS = ["Validé", "Validé non signé", "Option"];   // retire "Option" pour ne voir que le ferme
const NB_MAX = { small: 2, medium: 3, large: 6 };           // nombre de chronos affichés
const AFFICHER_EQUIPE = true;     // moyen et grand : avec qui tu chronomètres (noms des autres chronométreurs)
const AFFICHER_MATERIEL = true;   // grand uniquement : techno + matériel à prévoir (Urtime, Arche, Tablette…)
const JOURS_ALERTE = 30;          // « à affecter » : chronos sans chronométreur dans les N prochains jours
const RESET = false;          // passe à true, lance une fois, puis remets false : redemande l'adresse et le code
// ═════════════════════════════════════════════════════════════

const COULEURS = {
  "Validé": "#22c55e",
  "Validé non signé": "#fb923c",
  "Option": "#f59e0b",
};
const ORANGE = new Color("#f97316");
const MUTED  = new Color("#8892a4");
// Un cache par code d'accès : un iPhone partagé ou un changement de code ne mélange jamais deux personnes
function nomCache(code) {
  let h = 0;
  for (const c of String(code)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return "oxybol-chronos-cache-" + h.toString(16) + ".json";
}

// ─── Réglages (trousseau) ───────────────────────────────────
const URL_PAR_DEFAUT = "https://notre-agenda.vercel.app";

function oublier() {
  if (Keychain.contains("oxybol_url"))  Keychain.remove("oxybol_url");
  if (Keychain.contains("oxybol_code")) Keychain.remove("oxybol_code");
}

// Demande l'adresse et le code, vérifie l'adresse, puis range le tout dans le trousseau.
async function demander() {
  let erreur = "";
  for (let essai = 0; essai < 3; essai++) {
    const a = new Alert();
    a.title = "Configuration";
    a.message = (erreur ? erreur + "\n\n" : "") +
      "1) Adresse de l'app (déjà remplie)\n2) Code d'accès : celui de l'écran d'entrée de Notre Agenda";
    a.addTextField("Adresse", URL_PAR_DEFAUT);
    a.addSecureTextField("Code d'accès", "");
    a.addAction("Enregistrer");
    a.addCancelAction("Annuler");
    if ((await a.present()) !== 0) return null;

    const brut = a.textFieldValue(0).replace(/\s+/g, "");
    const code = a.textFieldValue(1).trim();
    const m = (/^https?:\/\//i.test(brut) ? brut : "https://" + brut).match(/^(https?:\/\/[a-z0-9-]+(\.[a-z0-9-]+)+)/i);

    if (!m)    { erreur = "L'adresse n'est pas valide. Exemple : " + URL_PAR_DEFAUT; continue; }
    if (!code) { erreur = "Le code d'accès est vide."; continue; }

    Keychain.set("oxybol_url", m[1]);
    Keychain.set("oxybol_code", code);
    return { base: m[1], code };
  }
  return null;
}

async function reglages() {
  if (RESET) oublier();
  if (Keychain.contains("oxybol_url") && Keychain.contains("oxybol_code")) {
    return { base: Keychain.get("oxybol_url"), code: Keychain.get("oxybol_code") };
  }
  if (config.runsInWidget) return null; // impossible de poser une question depuis le widget
  return await demander();
}

// ─── Données ────────────────────────────────────────────────
async function charge(r, an) {
  // Le code part dans un en-tête (il n'apparaît pas dans les journaux d'adresses)
  const req = new Request(`${r.base}/api/agenda?mode=chronos&year=${an}`);
  req.headers = { "X-Access-Code": r.code };
  req.timeoutInterval = 20;
  const data = await req.loadJSON();
  const statut = req.response ? req.response.statusCode : 200;
  if (statut === 401) throw new Error("Code d'accès refusé");
  if (statut >= 400) throw new Error("Erreur " + statut);
  return data.events || [];
}

function lireCache(code) {
  try {
    const fm = FileManager.local();
    const p = fm.joinPath(fm.documentsDirectory(), nomCache(code));
    return fm.fileExists(p) ? JSON.parse(fm.readString(p)) : null;
  } catch (e) { return null; }
}
function ecrireCache(code, evs) {
  try {
    const fm = FileManager.local();
    fm.writeString(fm.joinPath(fm.documentsDirectory(), nomCache(code)), JSON.stringify(evs));
  } catch (e) {}
}

function parseJour(s) {
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

async function prochains(r) {
  const an = new Date().getFullYear();
  let evs, horsLigne = false;
  try {
    const [a, b] = await Promise.all([charge(r, an), charge(r, an + 1)]);
    evs = a.concat(b);
    ecrireCache(r.code, evs);
  } catch (e) {
    if (/Code d'accès/.test(e.message)) throw e; // mauvais code : on le signale, pas de cache
    evs = lireCache(r.code);
    if (!evs) throw e;
    horsLigne = true;
  }

  const auj = new Date(); auj.setHours(0, 0, 0, 0);
  const liste = evs
    .filter(e => (!SEULEMENT_MOI || e.mine) && STATUTS.includes(e.statut) && e.start)
    .map(e => {
      const jour = parseJour(e.start);
      return { ...e, jour, fin: e.end ? parseJour(e.end) : jour };
    })
    .filter(e => e.fin >= auj) // un chrono sur plusieurs jours reste affiché jusqu'au dernier jour
    .sort((x, y) => x.jour - y.jour);

  // Chronos (toute l'équipe) sans personne dessus, dans les prochains jours : le point qui demande une action
  const limite = new Date(auj.getTime() + JOURS_ALERTE * 86400000);
  const aAffecter = evs.filter(e => {
    if (!e.start || !STATUTS.includes(e.statut) || e.nb_chrono) return false;
    const j = parseJour(e.start);
    return j >= auj && j <= limite;
  }).length;

  return { liste, horsLigne, auj, aAffecter };
}

// ─── Affichage ──────────────────────────────────────────────
function quand(jour, auj) {
  const diff = Math.round((jour - auj) / 86400000);
  if (diff <= 0) return "aujourd'hui";
  if (diff === 1) return "demain";
  return `dans ${diff} j`;
}

// « sam. 14 nov. · dans 2 j »  ou, si c'est déjà commencé, « en cours · jusqu'au dim. 15 nov. »
function libelle(e, auj, df) {
  if (e.jour < auj) return `en cours · jusqu'au ${df.string(e.fin)}`;
  return `${df.string(e.jour)} · ${quand(e.jour, auj)}`;
}

function equipeTexte(e) {
  const noms = e.chronometreurs || [];
  if (!e.mine) return noms.join(", ");
  // « moi » n'a pas besoin d'être répété : l'API fournit déjà la liste des autres, quelle que soit la personne
  const autres = Array.isArray(e.autres) ? e.autres : noms;
  return autres.length ? autres.join(", ") : "seul";
}

function construire({ liste, horsLigne, auj, aAffecter }, famille, base, code) {
  const w = new ListWidget();
  w.url = `${base}/?code=${encodeURIComponent(code)}`; // ouvre l'app déjà connectée, même depuis Safari
  w.refreshAfterDate = new Date(Date.now() + 30 * 60 * 1000);

  const df = new DateFormatter();
  df.locale = "fr_FR";
  df.dateFormat = "EEE d MMM";

  // Écran verrouillé (iOS 16+) : une ligne de texte, sans fond
  if (famille === "accessoryRectangular" || famille === "accessoryInline") {
    const e = liste[0];
    if (famille === "accessoryInline") {
      w.addText(e ? `${e.jour < auj ? "en cours" : df.string(e.jour)} · ${e.title}` : "Aucun chrono");
      return w;
    }
    const t = w.addText("CHRONO");
    t.font = Font.boldSystemFont(10);
    if (!e) { w.addText("Aucun chrono à venir").font = Font.systemFont(12); return w; }
    const titre = w.addText(e.title); titre.font = Font.boldSystemFont(13); titre.lineLimit = 2;
    w.addText(libelle(e, auj, df)).font = Font.systemFont(11);
    return w;
  }

  w.backgroundColor = new Color("#0f1117");
  w.setPadding(12, 14, 10, 14);

  const nb = NB_MAX[famille] || NB_MAX.medium;

  const tete = w.addStack();
  tete.centerAlignContent();
  const t = tete.addText(SEULEMENT_MOI ? "MES CHRONOS" : "CHRONOS");
  t.font = Font.boldSystemFont(10); t.textColor = ORANGE;
  tete.addSpacer();
  if (aAffecter > 0 && famille !== "small") {
    const al = tete.addText(`⚠ ${aAffecter} à affecter`);
    al.font = Font.boldSystemFont(9); al.textColor = new Color("#fbbf24");
  }
  if (horsLigne) {
    tete.addSpacer(6);
    const h = tete.addText("hors ligne");
    h.font = Font.systemFont(9); h.textColor = MUTED;
  }
  w.addSpacer(6);

  if (!liste.length) {
    w.addSpacer();
    const v = w.addText("Aucun chrono à venir");
    v.font = Font.systemFont(13); v.textColor = MUTED;
    w.addSpacer();
    return w;
  }

  liste.slice(0, nb).forEach((e, i) => {
    if (i > 0) w.addSpacer(famille === "large" ? 9 : 6);

    const ligne = w.addStack();
    ligne.layoutHorizontally();
    ligne.centerAlignContent();

    const barre = ligne.addStack();
    barre.size = new Size(3, famille === "large" && AFFICHER_MATERIEL ? 40 : 30);
    barre.cornerRadius = 1.5;
    barre.backgroundColor = new Color(COULEURS[e.statut] || "#8892a4");
    ligne.addSpacer(8);

    const col = ligne.addStack();
    col.layoutVertically();
    const titre = col.addText(e.title);
    titre.font = Font.semiboldSystemFont(famille === "small" ? 12 : 13);
    titre.textColor = Color.white();
    titre.lineLimit = 1;
    let detail = libelle(e, auj, df) + (e.statut === "Option" ? " · option" : "");
    if (famille !== "small" && AFFICHER_EQUIPE) {
      const q = equipeTexte(e);
      if (q) detail += " · 👤 " + q;
    }
    const sous = col.addText(detail);
    sous.font = Font.systemFont(10);
    sous.textColor = MUTED;
    sous.lineLimit = 1;

    if (famille === "large" && AFFICHER_MATERIEL) {
      const mat = [...(e.techno || []), ...(e.materiel || [])].join(" · ");
      if (mat) {
        const m = col.addText(mat);
        m.font = Font.systemFont(9);
        m.textColor = new Color("#5f6b82");
        m.lineLimit = 1;
      }
    }
    ligne.addSpacer();
  });

  w.addSpacer();
  return w;
}

function widgetMessage(texte) {
  const w = new ListWidget();
  w.backgroundColor = new Color("#0f1117");
  const t = w.addText(texte);
  t.font = Font.systemFont(12); t.textColor = MUTED;
  return w;
}

// ─── Lancement ──────────────────────────────────────────────
async function afficher(r) {
  const data = await prochains(r);
  return construire(data, config.widgetFamily || "medium", r.base, r.code);
}

async function main() {
  let r = await reglages();
  let w;

  if (!r) {
    w = widgetMessage("Ouvre le script « Oxybol chronos » dans Scriptable pour le configurer.");
  } else {
    try {
      w = await afficher(r);
    } catch (e) {
      w = widgetMessage("Chronos indisponibles : " + e.message);

      // Lancé à la main dans Scriptable : on propose de corriger l'adresse ou le code
      if (!config.runsInWidget) {
        const q = new Alert();
        q.title = "Chronos indisponibles";
        q.message = e.message + "\n\nVeux-tu ressaisir l'adresse et le code d'accès ?";
        q.addAction("Reconfigurer");
        q.addCancelAction("Fermer");
        if ((await q.present()) === 0) {
          oublier();
          r = await demander();
          if (r) {
            try { w = await afficher(r); }
            catch (e2) { w = widgetMessage("Chronos indisponibles : " + e2.message); }
          }
        }
      }
    }
  }

  if (config.runsInWidget) {
    Script.setWidget(w);
  } else {
    await w.presentMedium(); // aperçu quand tu lances le script dans l'app
  }
  Script.complete();
}

await main();
