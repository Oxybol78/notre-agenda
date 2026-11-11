# Notre Agenda

Agenda unifié de Christophe, partagé avec Flo.
Agrège trois sources en une seule page :

| Source | Contenu | Couleur |
|---|---|---|
| **Notion** | Les chronos où Christophe est affecté | 🟠 orange |
| **Google Calendar** | Agenda perso (Gmail) | 🟢 vert |
| **Outlook / M365** | Agenda pro Oxybol | 🔵 bleu |

---

## Architecture

```
Notion  ─┐
Google  ─┼──►  /api/agenda  ──►  index.html
Outlook ─┘     (serverless)      (PWA)
```

- `api/agenda.py` — proxy serverless Python. Porte les tokens,
  interroge les trois API, renvoie un JSON fusionné.
- `index.html` — l'app. Vue liste + vue calendrier, filtres par source.

### Onglet « Tableau de bord »

Vue d'ensemble des chronos Oxybol, alimentée **directement par la base
Notion** (`/api/agenda?code=XXXX&mode=chronos`) :

- bascule **Tous les chronos / Mes chronos** (« mes » = Christophe dans la
  propriété *Chronométreur*)
- filtre par **statut** (Validé et Option par défaut ; Reporté, Annulé, Perdu
  à activer à la demande)
- indicateurs : à venir, ce mois-ci, total de l'année, à venir pour moi,
  **à affecter** (Validé/Option sans chronométreur)
- histogramme mensuel (moi / autres chronométreurs), liste et calendrier
  colorés par statut

Fenêtre : du 1er janvier de l'année en cours à +365 jours.

Les tokens ne sont **jamais** dans le code : uniquement dans les
variables d'environnement Vercel.

---

## Variables d'environnement (Vercel)

À définir dans *Settings → Environment Variables* :

| Variable | Où la retrouver |
|---|---|
| `ACCESS_CODE` | Le code partagé avec Flo. À choisir. |
| `NOTION_TOKEN` | notion.so/profile/integrations |
| `GOOGLE_CLIENT_ID` | console.cloud.google.com → projet *API Calendar* → Clients |
| `GOOGLE_CLIENT_SECRET` | idem (visible une seule fois à la création) |
| `GOOGLE_REFRESH_TOKEN` | script `get_token.py` |
| `MS_CLIENT_ID` | portal.azure.com → app *Notre Agenda* → Vue d'ensemble |
| `MS_TENANT_ID` | idem |
| `MS_REFRESH_TOKEN` | script `get_token_ms2.py` |

⚠️ Après toute modification de variable : **redéployer** (Deployments →
… → Redeploy). Vercel ne recharge pas les variables à chaud.

---

## Configuration des accès

### Notion
L'intégration doit avoir accès à la base des chronos
(`5d07a861-e0a1-4362-8a10-d4ce61acad0c`).
Dans Notion : ouvrir la base → ••• → Connexions → ajouter l'intégration.

### Google
Projet **API Calendar** (`api-calendar-368207`) sur console.cloud.google.com.
- Google Calendar API activée
- Écran de consentement **publié en production** (sinon le refresh token
  expire tous les 7 jours)
- Client OAuth de type **Application de bureau**

### Microsoft
App **Notre Agenda** sur le tenant Oxybol (portal.azure.com → Entra ID).
- Autorisations déléguées : `Calendars.Read`, `offline_access`
- Authentification → **Autoriser les flux clients publics : Activé**
  (nécessaire pour le device code flow)
- Le secret client Azure n'est **pas** utilisé : le refresh token suffit.

---

## Maintenance

**Le refresh token Microsoft peut expirer** (inactivité prolongée,
changement de mot de passe, révocation). Symptôme : la source Oxybol
disparaît, un bandeau jaune s'affiche.
Correctif : relancer `get_token_ms2.py`, mettre à jour `MS_REFRESH_TOKEN`
dans Vercel, redéployer.

**Le refresh token Google** est permanent tant que l'app reste publiée
et que l'accès n'est pas révoqué depuis myaccount.google.com/permissions.

**Fenêtre affichée** : 7 jours dans le passé, 365 jours dans le futur.
Modifiable en haut de `api/agenda.py` (`JOURS_PASSE`, `JOURS_FUTUR`).

---

## Sécurité — ce que vaut le code d'accès

Le code est vérifié **côté serveur** : il n'est pas dans le HTML, et
sans lui l'API ne renvoie rien. Il est retenu dans le navigateur pour
éviter de le retaper.

C'est une protection **légère**, adaptée à un usage familial : elle
arrête quelqu'un qui tomberait sur l'URL, pas un attaquant déterminé.
Pas de compte utilisateur, pas de chiffrement de bout en bout.

Le dépôt peut rester public : il ne contient aucun secret.
En revanche, **ne jamais commiter de token** — ils vont dans Vercel,
nulle part ailleurs.
