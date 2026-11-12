# Notre Agenda

Agenda unifié de Christophe, partagé avec Flo.
Agrège deux sources en une seule page :

| Source | Contenu | Couleur |
|---|---|---|
| **Notion** | Les chronos où Christophe est affecté | 🟠 orange |
| **Google Calendar** | Agenda perso (Gmail) | 🟢 vert |

---

## Architecture

```
Notion  ─┐
Google  ─┴──►  /api/agenda  ──►  index.html
               (serverless)      (PWA)
```

- `api/agenda.py` — proxy serverless Python. Porte les tokens,
  interroge les API, renvoie un JSON fusionné.
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

Navigation **année par année** (‹ • ›, de 2022 à l'année en cours + 4) :
chaque année est chargée à la demande (`&year=AAAA`) puis gardée en mémoire.
Les pastilles de statut affichent le **nombre de chronos par statut** pour
l'année affichée. Pour l'année en cours, un sélecteur permet de voir
« À venir » ou « Toute l'année ». Dans le calendrier, passer de décembre à
janvier change d'année.

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

---

## Maintenance

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

---

## Historique

La source **Outlook / Microsoft 365** a été retirée (inutile pour l'usage
actuel). Les variables `MS_*` peuvent être supprimées de Vercel, et l'app
Azure *Notre Agenda* du tenant Oxybol n'a plus d'utilité.

#### Sous-onglet « 📊 Stats » (par défaut)

Toutes les stats respectent les filtres Tous/Mes chronos et statuts :
prochains chronos (J-N), chiffres clés, chronos à relancer / à faire signer,
alertes planning (chronométreur sur 2 chronos le même jour, validés sans
équipe, jours à 3 chronos ou plus), calendrier de charge façon GitHub,
comparatif année après année (avec « à date » vs N-1), pipeline par statut et
taux de conclusion, répartition par chronométreur et binômes, rythme
(jours de semaine, records, plus longue pause), puis répartition par type,
techno, matériel et tâches. Les autres années sont chargées en tâche de fond
pour le comparatif.

### Un code d'accès par personne

`ACCESS_CODE` = Christophe (Notion + agenda Google perso). `CODE_ROMAIN` et
`CODE_PAUL` (variables Vercel) ouvrent la même app côté Romain / Paul : « mes
chronos », « avec qui je fais équipe » et le widget se calculent pour eux, sans
jamais afficher l'agenda Google de Christophe. Pour ajouter quelqu'un : une ligne
dans `EQUIPE` (api/agenda.py, identifiant Notion de la personne) + la variable
`CODE_<PRÉNOM>` sur Vercel, puis Redeploy.
