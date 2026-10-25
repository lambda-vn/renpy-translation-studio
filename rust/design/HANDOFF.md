# Ren'Py Translation Studio — passation design → implémentation

Ce dossier contient les maquettes de la refonte UI (Tauri + Svelte 5) et ce qu'il faut savoir pour les implémenter.

## Comment lire les maquettes

- `maquettes/*.dc.html` : une maquette par écran. Ce sont des **références visuelles**, pas du code à copier tel quel :
  le format `.dc.html` utilise un petit moteur de gabarit (`{{variable}}`, `<sc-for>`, `<sc-if>`, `<x-dc>`, `<dc-import>`)
  propre à l'outil de design. Le CSS (dans `<helmet><style>`) et la structure HTML, eux, sont directement réutilisables.
- `maquettes/canvas.json` : l'index des écrans (titre de chaque artboard).
- Le script `support.js` référencé en tête n'est pas fourni : inutile pour l'implémentation.

| Fichier | Écran |
|---|---|
| `Main.dc.html` | **Révision** (écran principal, à faire en premier). Props : `dark`, `scenario` (`edition`/`vide`), `job` (`replie`/`deplie`/`aucun`) |
| `Revision-sombre.dc.html` | Révision en thème sombre, journal du job déplié |
| `Revision-vide.dc.html` | Révision avec un filtre sans résultat, à 1024 px |
| `Projets.dc.html` | Configuration : projets récents + nouveau projet |
| `Export.dc.html` | Export zip |
| `Premier-lancement.dc.html` | Premier lancement (langue d'interface, SDK facultatif) |
| `Personnages.dc.html` | Tableau des personnages |
| `Univers.dc.html` | Texte libre « univers » |
| `Fournisseurs.dc.html` | DeepL / Ollama / LibreTranslate |
| `Dialogues.dc.html` | Dialogues (job, ré-extraction, effacement, paramètres, F1, confirmation IA) et menu contextuel |
| `Systeme.dc.html` | Statuts, couleurs, boutons, champs, toasts, en clair et en sombre |

> Note : les écrans secondaires contiennent des couches de CSS successives (le bloc final « RenZip v2 » surcharge le premier).
> Pour les valeurs de référence, se fier à `Main.dc.html` et `Projets.dc.html`, réécrits proprement en dernier.

## Direction

Sobre, aéré, un outil de lecture. Inspiré de RenZip v2 : accent violet, Archivo, rayons 6 / 9 / 14 px.
Le violet plein est réservé au **bouton principal** ; les états sélectionnés/actifs utilisent le violet pâle (`--accWeak`) avec texte `--acc7`.
Pas d'ombres sur les cartes, des filets 1 px.

## Typographie

| Usage | Police | Tailles |
|---|---|---|
| Interface | Archivo 400/500/600/700 | 13,5 px courant, 12–13 px secondaire, titres 17–22 px en 700 |
| Texte du jeu (source et traduction) | Literata | 15 px, interligne 1,6 |
| Chemins, compteurs, balises, raccourcis | IBM Plex Mono | 11–13 px |

Embarquer les polices dans l'application (pas de Google Fonts à l'exécution).

## Tokens (CSS custom properties)

```css
.rts {
  --bg:#F6F5F9; --panel:#FFFFFF; --sunken:#EEECF3; --hover:#F9F8FC;
  --line:#E8E6EE; --line2:#D3D0DB;
  --ink:#1E1B26; --ink2:#4A4653; --ink3:#67636F;
  --acc:#7F56E0; --acc7:#6440BD; --accInk:#FFFFFF; --accWeak:#F4F0FE; --accRing:rgba(127,86,224,.18);
  --s-none:#86838F; --s-draft:#A3650E; --s-imp:#3A68B0; --s-ai:#0B7A80; --s-ok:#277A49;
  --flag:#BE3E0B; --flagWeak:#FDF3EC; --err:#B32222; --errWeak:#FCEFEF; --warn:#7F5600;
  --mcp:#0B6E73; --mcpWeak:#EEF8F8;
  --tag:#55525E; --tagBg:#EFEDF3; --var:#6440BD; --varBg:#F2EDFF;
}
.rts.dark {
  --bg:#17151D; --panel:#1E1C25; --sunken:#14121A; --hover:#232029;
  --line:#2C2934; --line2:#423E4D;
  --ink:#ECEAF1; --ink2:#C3BFCC; --ink3:#A09CAB;
  --acc:#A788F6; --acc7:#C2A9FA; --accInk:#160F2B; --accWeak:#241E36; --accRing:rgba(167,136,246,.25);
  --s-none:#85828E; --s-draft:#E2AA4E; --s-imp:#7FA7E8; --s-ai:#4CC3C9; --s-ok:#62C28A;
  --flag:#F2894A; --flagWeak:#2E211B; --err:#F27373; --errWeak:#341D20; --warn:#E5BC5A;
  --mcp:#4CC3C9; --mcpWeak:#182B2C;
  --tag:#B3B0BC; --tagBg:#2C2934; --var:#C9B4FA; --varBg:#2B2442;
}
```

Pourquoi `#7F56E0` et pas `#9b76f4` (le violet RenZip) : du texte blanc sur `#9b76f4` ne fait que ~3:1, insuffisant (4,5:1 requis).
`#7F56E0` (≈ 4,9:1) est le cran 600 de la même rampe. En sombre, c'est l'inverse : violet clair, texte foncé.

## Les statuts (ne jamais coder un statut par la couleur seule)

| Statut | Glyphe | Couleur |
|---|---|---|
| Non traduit | cercle vide | `--s-none` |
| Brouillon | cercle à moitié plein | `--s-draft` |
| Importé | losange plein | `--s-imp` |
| Suggestion IA | étoile à 4 branches | `--s-ai` (bleu-vert, pas violet, pour ne pas se confondre avec l'accent) |
| Validé | cercle plein coché | `--s-ok` |
| Signalée (drapeau) | drapeau | `--flag` |
| En erreur | triangle avec ! | `--err` |
| Avertissement | cercle avec ! (contour) | `--warn`, texte seul |

Les SVG exacts sont dans `Main.dc.html`. Chaque glyphe est `aria-hidden="true"` et accompagné d'un texte masqué (`.sr`) :
« Ligne 22, statut : Suggestion IA, signalée ».

## Composants à créer (Svelte 5)

- `AppHeader` : logo, nom du jeu, langues (`<abbr>`), `StepNav` (étapes en `<ol>`, `aria-current="step"`), navigation outils.
- `FileList` (aside) : progression projet (`<progress>`), liste de fichiers (`<button aria-current>`), nom + dossier + compteur.
- `ReviewToolbar` : titre du fichier, Traduction automatique, menu « Plus d'actions » (Mémoire, Import / export, Effacer…), compteur « N lignes non écrites » relié au bouton Écrire par `aria-describedby`.
- `FilterBar` : `<form role="search">`, recherche, filtres de statut (boutons `aria-pressed`), sélecteur de locuteur.
- `JobBanner` : bandeau non modal, `<progress>`, échecs, journal repliable (`aria-expanded` / `aria-controls`), Annuler.
- `LineRow` : en-tête (glyphe, locuteur, n° de ligne, 5 actions au survol/focus), source (`lang="en"`) | traduction (champ en édition ou texte), messages (avertissement, erreur `role="alert"`, note, mise à jour MCP).
- `TokenText` : rend `{balises}` et `[variables]` en puces mono.
- `Pagination` : `<nav aria-label="Pagination">`, `aria-current="page"`.
- `EmptyState`, `Toast` (`role="status"`, erreur en `role="alert"`), `Dialog` (élément natif `<dialog>`, `showModal()`), `ContextMenu` (`role="menu"`).

## Comportements à respecter

- Une ligne mise à jour par un autre processus (MCP) : fond `--mcpWeak` bref + mention « Modifiée par l'assistant », annonce dans une zone `aria-live="polite"`, **jamais** sur la ligne en cours d'édition.
- Le bandeau de job n'est pas modal ; quitter la révision (étape Export) est désactivé pendant un job.
- Les actions de ligne sont masquées (`opacity:0`) sauf au survol, au focus (`:focus-within`) et sur la ligne active : elles restent atteignables au clavier.
- Champ de traduction : `textarea` qui grandit avec le texte, relié à son avertissement par `aria-describedby`.

## Raccourcis (doivent marcher même dans un champ)

| Touche | Action |
|---|---|
| F1 | Liste des raccourcis |
| Échap | Fermer le dialogue, sinon vider la recherche |
| Ctrl+F | Aller à la recherche |
| Ctrl+S | Écrire les .rpy |
| Ctrl+Entrée | Valider et passer à la ligne suivante |
| Ctrl+Maj+Entrée | Valider et appliquer aux sources identiques |
| Ctrl+D | Copier la source dans la traduction |
| Ctrl+M | Signaler la ligne |
| Alt+↑ / Alt+↓ | Ligne précédente / suivante |
| Maj+Alt+↑ / ↓ | Fichier précédent / suivant |
| Alt+← / Alt+→ | Page précédente / suivante |

Afficher les raccourcis avec `<kbd>`.

## RGAA — check-list appliquée dans les maquettes

- `lang="fr"` (ou `en` selon l'interface) sur `<html>` ; **`lang="en"` sur chaque texte source** (changement de langue, critère 8.7).
- Un `<title>` par écran ; structure `header` / `nav` / `main` / `aside` ; un seul `h1`, hiérarchie de titres cohérente.
- Liens d'évitement « Aller aux lignes », « Aller aux fichiers » / « Aller au contenu », visibles au focus.
- Focus toujours visible : `outline: 2px solid var(--acc); outline-offset: 2px`.
- Contraste texte ≥ 4,5:1 (y compris `--ink3`), composants et glyphes ≥ 3:1.
- Chaque champ a un `<label>` ; champ obligatoire signalé dans le libellé.
- Boutons-icônes avec `aria-label` explicite et contextualisé (« Valider la ligne 22 »).
- Messages de statut : `aria-live="polite"` ; erreurs bloquantes : `role="alert"`.
- Aucune information portée par la couleur seule (statuts = forme + texte).
- Éléments natifs HTML5 : `<progress>`, `<dialog>`, `<kbd>`, `<abbr>`, `<time>`, `<details>/<summary>`.

## Hors maquettes / à trancher

- La sémantique exacte des trois modes de ré-extraction (garder / mettre à jour / réinitialiser) a été rédigée par hypothèse.
- Le choix « Thème » (système / clair / sombre) dans Paramètres a été ajouté, il n'était pas dans le brief.
- Les données des maquettes (jeu « Les Lanternes de Kerhaven », fichiers, répliques) sont fictives.
