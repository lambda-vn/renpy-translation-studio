# Check-list de parité 1.0.0 → 2.0.0 (rc.3)

Chaque ligne vient du README et de `docs/en/` de la 1.0.0 (liste des
fonctionnalités, fournisseurs, serveur MCP, écrans). Audit fait le
2026-10-24 sur le commit `b1189d7`, mis à jour à chaque étape de la rc.2 et pour l'interface de la rc.3, en lisant le code de `rust/`, pas en
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
| F3 | Drapeau « à revoir » et note par ligne | ✅ | Ctrl+M, champ de note sous la ligne signalée ; écrire une note lève le drapeau ; retirer le drapeau d'une ligne annotée demande confirmation. Vérifié dans la vraie fenêtre (rc.3). |
| F4 | Job de fond, contrôles qualité, relances | ✅ | `job.rs` testé (relances 8 puis 1, interpolation refusée). |
| F5 | Progression en bandeau, révision utilisable | ✅ | Bandeau non modal (progression, échecs, journal repliable, annulation), navigation refusée pendant le job. Vérifié dans la vraie fenêtre avec un vrai job Ollama (`gemma3:1b`, 96 lignes) et sur un échec. |
| F6 | Glossaire des personnages | ✅ | Écran CRUD et détection automatique (`core::renpy::character_detector`, aussi exposée au MCP). L'écran reste en anglais (voir S16). |
| F7 | Résumé d'univers | ✅ | Génération exécutée contre un vrai modèle (`gemma3:1b`) dans la vraie fenêtre : confirmation à chaque envoi, texte non enregistré tant qu'on ne clique pas. |
| F8 | Import / export CSV, XLIFF 1.2, JSON | ✅ | `core::interchange` (21 tests portés de la suite Python), commandes et boîte de dialogue dans la barre de révision. Export, aperçu et application exercés dans la vraie fenêtre sur les trois formats ; **les boîtes natives d'enregistrement et d'ouverture n'ont pas été pilotées** (chemins passés directement aux commandes). Un export écrit des chemins relatifs au jeu, là où la 1.x écrivait les absolus. |
| F9 | Mémoire de traduction partagée | ✅ | Moteur compatible (`memory.db`), outil MCP et bouton « Mémoire » (51 lignes remplies sur la démo, puis aucune au second appel). Son volume n'est pas encore affiché dans les paramètres (S14). |
| F10 | Tout au clavier, F1, statuts en glyphe + libellé lecteur d'écran | ✅ | Table unique `src/lib/shortcuts.ts`, aide F1, glyphe + texte `.sr` par statut, liens d'évitement, focus visible. Raccourcis vérifiés avec de vrais événements clavier (Ctrl+Entrée, Ctrl+D, Ctrl+M, Alt+↓, Ctrl+S, F1, Échap, touche Menu). Pas d'audit avec un vrai lecteur d'écran. |
| F11 | Export zip `<jeu>/game/tl/<langue>/` | ✅ | `exporter.rs` testé (exclusion `.rpyc`, refus de `../`, nom du jeu). Écran d'export : saisie à la main du chemin. |

## Fournisseurs

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| P1 | DeepL (+ glossaire serveur) | ✅ | Job réel avec la clé de l'utilisateur (trousseau) dans la vraie fenêtre : 2/2 lignes, `\n` conservés. Glossaire serveur non exercé (aucun personnage noté `Nom -> Traduction`). |
| P2 | LibreTranslate | ✅ | Job réel contre une instance locale : 6/11, les 5 refus justifiés (4 renvois identiques à la source, 1 interpolation perdue). |
| P3 | Ollama (garde-fous petits modèles, `-cloud`) | 🟡 | Jobs réels avec `gemma3:1b` et `gemma3:4b` : tout est traduit, mais `gemma3:4b` **décale des traductions** dans un lot (identifiants justes, textes de la ligne voisine). Régression du portage ou défaut déjà en 1.0.0 : enquête en cours. Un modèle absent est signalé comme tel. |

## Serveur MCP

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| M1 | 17 outils | ✅ | Les 17 sont portés ; handshake à 17 outils vérifié sous Windows (la CI des trois systèmes tournera avec le commit). |
| M2 | Drapeaux destructeurs en ligne de commande seulement | ✅ | Porté tel quel. |
| M3 | Ne rouvre que les projets du registre | ✅ | Porté. |
| M4 | Rafraîchissement en direct (`live.json`) | ✅ | `core::live` : même `.rts/live.json`, jeton obligatoire comparé à temps constant, tailles bornées, notification jamais bloquante. Les écritures du serveur MCP (soumission, note, drapeau, mémoire, effacement) préviennent l'écran de révision, qui met les lignes visibles à jour sur place. Vérifié dans la vraie fenêtre avec un vrai processus `rts-mcp` (voir le README). |
| M5 | Lanceur `rts-mcp` à côté de l'application | 🟡 | Sidecar Tauri empaqueté et handshaké **avant** installation ; pas lancé depuis un installateur. |

## Écrans (docs/en)

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| S1 | Onboarding (langue de l'UI, SDK facultatif) | 🟡 | Écran porté (`Onboarding.svelte`, `isFirstLaunch`), **jamais affiché dans la vraie fenêtre** (la config réelle existe déjà). |
| S2 | Liste des projets récents, reprise (fichier, page, filtre, recherche) | ✅ | Cartes avec avancement, ouverture directe en révision, × qui supprime `.rts/` après confirmation (comportement du code 1.0.0, sa doc disait le contraire). État de navigation gardé en mémoire comme en 1.0.0. |
| S3 | Nouveau projet : dossier, langues, SDK, bouton Extraire | ✅ | Sélecteur natif (ou chemin collé), langues source et cible, SDK demandé seulement si le jeu n'embarque pas de moteur utilisable, avis d'exécution de code tiers, dialogue des trois modes, liste des sources écartées. Exercé dans la vraie fenêtre. Visuellement provisoire (refonte prévue). |
| S4 | Panneau de fichiers : compteurs par statut, barre globale | ✅ | Barre projet, compteurs validés/total + brouillons/IA/importés, fichiers grisés selon le filtre. |
| S5 | Menu contextuel d'un fichier (ouvrir, copier le chemin, montrer, traduire, exporter, effacer) | ✅ | Clic droit, touche Menu, Maj+F10 ; vérifié dans la vraie fenêtre. |
| S6 | Filtres : statut, *Flagged*, *In error*, locuteur, recherche `%`/`_` littéraux | ✅ | Puces de statut + Signalées + En erreur, menu des locuteurs (vérifié : 18 lignes de `s`), recherche. La puce *En erreur* n'a pas de compteur. |
| S7 | Actions de ligne : traduire, copier la source (Ctrl+D), effacer, drapeau (Ctrl+M), valider | ✅ | Les cinq, au survol / focus / ligne active. |
| S8 | Ctrl+Maj+Entrée : valider et propager aux doublons | 🟡 | Porté (`validate_and_propagate`, testé), toast après une validation simple ; pas exercé dans la vraie fenêtre. |
| S9 | Navigation clavier entre lignes, fichiers, pages | ✅ | Alt+↑/↓, Maj+Alt+↑/↓, Alt+←/→ ; Alt+↓ vérifié dans la vraie fenêtre. |
| S10 | Avertissements qualité consultatifs sous la ligne | ✅ | Erreurs bloquantes (`role=alert`) et avertissements sous le champ. |
| S11 | Compteur « N lignes non écrites dans les .rpy » | ✅ | `unwritten_count` ; `save_project` enregistre désormais la date d'écriture (`tl_saved_at`), le compteur revient à zéro après Ctrl+S (vérifié). |
| S12 | Effacement en masse avec confirmation | ✅ | Dialogue fichier / projet × trois portées, compte affiché. Ouvert dans la vraie fenêtre, pas exécuté. |
| S13 | Barre d'étapes (Setup / Review / Export), confirmation avant de revenir en arrière, navigation refusée pendant un job | ✅ | Vérifié pendant un vrai job. |
| S14 | Dialogue de paramètres (langue de l'UI, journal détaillé, volume de la mémoire) | ✅ | Langue, thème (`system`/`light`/`dark`, déjà en 1.0.0), journal (format 1.0.0, sans effet en Rust : aucune journalisation), SDK, mémoire par paire de langues. |
| S15 | Export zip : nom proposé affiché, avertissement d'écart avec `tl/` | ✅ | `export_sync` porté ; les trois avertissements (non écrit, non traduit, qualité) ; zip vérifié. |
| S16 | i18n anglais + français | ✅ | Tous les écrans passent par `$t`, pluriels via `Intl.PluralRules` ; journal du job et messages qualité localisés (`JobMessage` structuré). Restent en anglais : les erreurs des fournisseurs. |
| S17 | Boîtes de dialogue de confirmation, toasts | ✅ | `confirmDialog` (plus aucun `window.confirm`), toasts `role=status`/`alert`. |

## Données (contrat gelé)

| # | 1.0.0 | État | Détail |
|---|---|---|---|
| D1 | `translations.db` ouvrable sans migration destructive | ✅ | Fixtures produites par le tag `v1.0.0`, 8 tests + lecture de la vraie base d'Inanna (36 981 lignes). |
| D2 | `settings.json` : clés conservées au rechargement | ✅ | |
| D3 | `memory.db`, `projects.json` | ✅ | |
| D4 | Clés API dans le trousseau OS | ✅ | Clé DeepL saisie par l'utilisateur dans l'écran des fournisseurs, relue par le job depuis le trousseau Windows. |

## Bilan

- ✅ 36 · 🟡 4 · ❌ 0 sur 40 lignes (rc.3, étape 4 : l'interface refaite dans
  le design de `design/`).
- Plus aucune ligne absente. Les 🟡 restants : le décalage Ollama (P3, enquête en
  cours), le lanceur `rts-mcp` installé (M5), l'onboarding jamais affiché (S1)
  et Ctrl+Maj+Entrée dans la vraie fenêtre (S8).
- L'étape 4 a été exercée dans la vraie fenêtre Tauri sous Windows, sur une
  copie de *The Question* : extraction, révision au clavier, menus, job Ollama
  réel, rafraîchissement par un vrai `rts-mcp`, personnages, univers,
  fournisseurs, export, paramètres, thème sombre. Pas de macOS ni de Linux.
