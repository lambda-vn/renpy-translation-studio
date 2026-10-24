# Check-list de parité 1.0.0 → 2.0.0 (rc.2)

Chaque ligne vient du README et de `docs/en/` de la 1.0.0 (liste des
fonctionnalités, fournisseurs, serveur MCP, écrans). Audit fait le
2026-10-24 sur le commit `b1189d7`, mis à jour après l'extraction en lisant le code de `rust/`, pas en
l'exécutant : une ligne n'est « ✅ » que si du code **et** un test ou une
vérification réelle la couvrent.

- ✅ porté et vérifié (test automatique ou vérification réelle)
- 🟡 porté en partie, ou porté sans avoir été exercé dans la vraie fenêtre
- ❌ absent

La roadmap dit « correctifs uniquement à partir de la rc.2 ». Les ❌
ci-dessous ne sont pas des correctifs : ce sont des fonctionnalités que
la beta.2 a différées. Les traiter, les repousser après la 2.0.0 ou les
retirer du périmètre est une décision à prendre ligne par ligne.

## Fonctionnalités (README)

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| F1 | Extraction par le moteur du jeu, repli sur le SDK | ✅ | `core::extraction` : moteur du jeu puis SDK, désarchivage des `.rpa` (lecteur sans pickle exécutable), sources refusées écartées et listées, modes garder / mettre à jour / réinitialiser, réextraction qui préserve le travail validé. Vérifié contre le vrai SDK 8.5.3 (The Question, qui livre un `tl/french`) et sur un jeu packagé Ren'Py 7 (CampusLyfe, 3 008 unités, 121 sources désarchivées) dont les identifiants sont identiques à ceux du parseur Python. |
| F2 | Cinq statuts, `human_validated` jamais écrasé | ✅ | Schéma, déclencheurs et contrat portés ; `compat_tests`. |
| F3 | Drapeau « à revoir » et note par ligne | 🟡 | Commandes `set_needs_review` / `set_note` et saisie de note dans la ligne. L'écriture d'une note ne lève pas le drapeau côté UI (à vérifier). |
| F4 | Job de fond, contrôles qualité, relances | ✅ | `job.rs` testé (relances 8 puis 1, interpolation refusée). |
| F5 | Progression en bandeau, révision utilisable | 🟡 | Barre de progression et annulation présentes ; jamais vu dans la vraie fenêtre. |
| F6 | Glossaire des personnages | 🟡 | Écran CRUD. Pas de détection automatique (`character_detector`). |
| F7 | Résumé d'univers | 🟡 | Édition et sauvegarde. Pas de génération IA, donc pas non plus la confirmation d'envoi à un tiers. |
| F8 | Import / export CSV, XLIFF 1.2, JSON | ❌ | `interchange` non porté. |
| F9 | Mémoire de traduction partagée | 🟡 | Moteur porté et compatible (`memory.db`), outil MCP `fill_from_memory`. **Pas de bouton dans l'interface**, et son volume n'est pas affiché dans les paramètres. |
| F10 | Tout au clavier, F1, statuts en glyphe + libellé lecteur d'écran | ❌ | Seuls Ctrl+S, Ctrl+F et Ctrl+Entrée existent. Aucune aide F1, aucun `aria-*` dans `src/`, statuts sans glyphe. |
| F11 | Export zip `<jeu>/game/tl/<langue>/` | ✅ | `exporter.rs` testé (exclusion `.rpyc`, refus de `../`, nom du jeu). Écran d'export : saisie à la main du chemin. |

## Fournisseurs

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| P1 | DeepL (+ glossaire serveur) | 🟡 | Porté et testé sur HTTP simulé. Jamais appelé contre la vraie API depuis la réécriture. |
| P2 | LibreTranslate | 🟡 | Idem. |
| P3 | Ollama (garde-fous petits modèles, `-cloud`) | 🟡 | Garde-fous copiés, plafond 8192 hors `-cloud`. Prompts non rejoués contre un vrai modèle ici. |

## Serveur MCP

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| M1 | 17 outils | 🟡 | 16 portés (handshake vérifié sur Windows, macOS, Linux en CI). Manque `detect_characters`. |
| M2 | Drapeaux destructeurs en ligne de commande seulement | ✅ | Porté tel quel. |
| M3 | Ne rouvre que les projets du registre | ✅ | Porté. |
| M4 | Rafraîchissement en direct (`live.json`) | ❌ | `core::live` et le serveur loopback absents : l'écran de révision ne se remplit pas pendant qu'un assistant écrit. |
| M5 | Lanceur `rts-mcp` à côté de l'application | 🟡 | Sidecar Tauri empaqueté et handshaké **avant** installation ; pas lancé depuis un installateur. |

## Écrans (docs/en)

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| S1 | Onboarding (langue de l'UI, SDK facultatif) | ❌ | |
| S2 | Liste des projets récents, reprise (fichier, page, filtre, recherche) | 🟡 | Liste présente ; la reprise de l'état de navigation et la croix de retrait de l'entrée sont à confirmer. |
| S3 | Nouveau projet : dossier, langues, SDK, bouton Extraire | ✅ | Sélecteur natif (ou chemin collé), langues source et cible, SDK demandé seulement si le jeu n'embarque pas de moteur utilisable, avis d'exécution de code tiers, dialogue des trois modes, liste des sources écartées. Exercé dans la vraie fenêtre. Visuellement provisoire (refonte prévue). |
| S4 | Panneau de fichiers : compteurs par statut, barre globale | 🟡 | Liste plate, sans arbre. À confirmer : compteurs complets (suggestions, importés, brouillons). |
| S5 | Menu contextuel d'un fichier (ouvrir, copier le chemin, montrer, traduire, exporter, effacer) | ❌ | |
| S6 | Filtres : statut, *Flagged*, *In error*, locuteur, recherche `%`/`_` littéraux | 🟡 | Statut, « Needs review » et recherche. Le filtre par locuteur existe côté Rust (`speaker`) mais pas dans l'UI ; *In error* absent. |
| S7 | Actions de ligne : traduire, copier la source (Ctrl+D), effacer, drapeau (Ctrl+M), valider | 🟡 | Valider et note seulement. |
| S8 | Ctrl+Maj+Entrée : valider et propager aux doublons | ❌ | |
| S9 | Navigation clavier entre lignes, fichiers, pages | ❌ | |
| S10 | Avertissements qualité consultatifs sous la ligne | 🟡 | Validation refusée sur erreur bloquante (vérifié sur un faux pont) ; affichage des avertissements non bloquants à confirmer. |
| S11 | Compteur « N lignes non écrites dans les .rpy » | ❌ | `count_modified_since` existe mais n'est branché à rien. |
| S12 | Effacement en masse avec confirmation | ❌ | Seul le MCP (`--allow-clear`) sait le faire. |
| S13 | Barre d'étapes (Setup / Review / Export), confirmation avant de revenir en arrière, navigation refusée pendant un job | ❌ | |
| S14 | Dialogue de paramètres (langue de l'UI, journal détaillé, volume de la mémoire) | ❌ | Seuls les fournisseurs sont configurables. |
| S15 | Export zip : nom proposé affiché, avertissement d'écart avec `tl/` | 🟡 | Zip oui ; `export_sync` non porté. |
| S16 | i18n anglais + français | 🟡 | Mécanisme en place (`src/lib/i18n.ts`, catalogues de la 1.0.0 repris et étendus, langue lue dans les paramètres, repli sur l'anglais). Appliqué à la barre de navigation et à l'écran de configuration ; les autres écrans sont encore en anglais. |
| S17 | Boîtes de dialogue de confirmation, toasts | ❌ | |

## Données (contrat gelé)

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| D1 | `translations.db` ouvrable sans migration destructive | ✅ | Fixtures produites par le tag `v1.0.0`, 8 tests + lecture de la vraie base d'Inanna (36 981 lignes). |
| D2 | `settings.json` : clés conservées au rechargement | ✅ | |
| D3 | `memory.db`, `projects.json` | ✅ | |
| D4 | Clés API dans le trousseau OS | 🟡 | Porté ; jamais exercé de bout en bout avec une vraie clé. |

## Bilan

- ✅ 10 · 🟡 18 · ❌ 12 sur 40 lignes.
- Le noyau, les données et l'extraction sont à parité. Ce qui manque est
  presque tout de l'**interface** (S4 à S17, F10) et de deux fonctions :
  échange CSV/XLIFF/JSON (F8) et rafraîchissement en direct (M4).
- L'extraction (F1, S3) est faite : la 2.0.0 peut créer un projet sans la
  1.x, ce qui était le blocage le plus lourd pour remplacer `main`.
- Rien ici n'a été vu dans la vraie fenêtre Tauri.
