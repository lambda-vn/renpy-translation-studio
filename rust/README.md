# Ren'Py Translation Studio — 2.0.0 (Rust)

Réécriture Rust de [Ren'Py Translation Studio](../README.md), sur la
branche `rust`. Voir la feuille de route pour le découpage complet en
sous-versions et les décisions d'architecture (Tauri, Svelte, données
compatibles avec la 1.0.0 Python, MCP sur
[modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk)).

`main` n'est remplacé qu'à la sortie de la 2.0.0 — cette branche coexiste
avec le code Python (`../src/`) le temps du chantier.

## État actuel : `2.0.0-beta.2`

L'application a maintenant une interface : SvelteKit (`src/routes/`)
au-dessus de commandes Tauri (`src-tauri/src/commands/`) qui ne font que
déléguer au noyau. Écrans : ouverture d'un projet déjà extrait
(`/`), révision (`/review` : fichiers, filtres, recherche, pagination,
édition avec brouillon automatique, validation refusée sur une erreur
bloquante, job de traduction avec progression et annulation, Ctrl+S /
Ctrl+F / Ctrl+Entrée), fournisseurs (`/provider-config`, test de
connexion pour les trois), personnages (`/characters`), résumé d'univers
(`/universe`) et export (`/export` : sauvegarde dans `tl/` puis zip).

Pour que Save et Export écrivent réellement, `core::renpy::writer`
(réécriture des `.rpy`, échappement des guillemets et retours à la ligne,
sauvegarde avant modification) et `core::exporter` (zip, nom du jeu) sont
portés, ainsi que `providers::registry`. Les tests passent à 144.

Non porté pour cette version, par choix : l'**extraction** (lancer le
SDK ou le moteur du jeu) — l'application n'ouvre que des projets déjà
extraits ; la **propagation aux doublons**, l'**interchange**
CSV/XLIFF/JSON, la **traduction ligne par ligne** et le **menu
contextuel** des fichiers dans l'écran de révision ; la **génération IA**
du résumé d'univers et la **détection** des personnages ; l'**i18n**
(l'interface est en anglais seulement) ; les **sélecteurs natifs** de
dossier/fichier (chemins saisis à la main) ; l'avertissement de
synchronisation avant export. Le job ne traduit que les lignes
`not_translated`, portée « ce fichier » ou « tout le projet » ; ses
résultats arrivent en `ai_suggested`, y compris les lignes sans rien à
traduire que Python passe directement en `human_validated`. Le panneau de
fichiers est une liste plate, pas un arbre.

**Vérifié** : `npm run check` (0 erreur), `npm run build`, `cargo test`,
`cargo clippy` et l'application qui démarre vraiment (`npm run tauri
dev`). L'écran de révision a aussi été exercé dans un navigateur avec un
faux pont `invoke` : ouverture → fichiers → lignes, trois frappes rapides
→ une seule sauvegarde de brouillon, validation refusée avec
« Missing [name] » puis acceptée. **Non vérifié** : aucun clic dans la
vraie fenêtre Tauri ni sur un vrai projet depuis l'interface — ce
poste n'offre pas de moyen de piloter une fenêtre native.

Cette vérification a aussi révélé un défaut de la beta.1 : le second
binaire `rts-mcp` rendait `cargo run` ambigu, donc `tauri dev` ne
lançait plus rien. `default-run = "rust"` dans `Cargo.toml` le corrige.

### Rappel beta.1

Une assistante peut déjà traduire un projet avant qu'aucune fenêtre
n'existe : `src-tauri/src/bin/rts_mcp.rs` sert 15 des 17
outils du serveur MCP Python, sur
[`rmcp`](https://github.com/modelcontextprotocol/rust-sdk) (le SDK Rust
officiel), en stdio comme `rts-mcp` en 1.x. Tout vit sous
`src-tauri/src/core/`, module par module en regard de `../src/core/` :

- `core::languages` — la liste des 19 langues et `get_language()`.
- `core::settings` — `settings.json` + trousseau OS pour les deux clés
  API, même répertoire de config que l'app Python
  (`dirs::config_local_dir()`, équivalent de `appauthor=False`).
- `core::storage` — schéma SQLite (WAL, déclencheurs, le même contrat
  `human_validated` jamais écrasé), le registre machine des projets
  récents (`recent_projects`, `projects.json` à côté de `settings.json`)
  et les dépôts, étendus pour le serveur MCP : pagination filtrée
  (`get_page`), fenêtre de voisinage (`get_neighbours`), mise à jour par
  lot (`update_translations`), effacement en masse
  (`clear_translations`). Le pipeline d'extraction reste hors périmètre.
- `core::renpy::{parser, say_line}` — lecture des `tl/*.rpy` générés
  par Ren'Py, y compris les blocs `strings:` du SDK. Travaille sur des
  `Vec<char>` plutôt que des tranches d'octets : les index Python sont
  des points de code, pas des octets.
- `core::translation::quality` — contrôles tag/interpolation/HTML/
  longueur. Le refus bloquant d'une interpolation `[...]` absente de la
  source reste non négociable.
- `core::translation::{context_builder, providers::{deepl,
  libretranslate, ollama}}` — DeepL et LibreTranslate parlent HTTP
  directement (`reqwest`), sans SDK officiel à envelopper côté Rust.
  Les garde-fous d'Ollama (schéma de sortie à longueur fixée,
  récupération de forme lâche, détection du bourrage par duplication)
  sont copiés du Python, pas simplifiés — CLAUDE.md l'interdit. Les
  trois implémentent maintenant `providers::base::TranslationProvider`,
  le trait partagé délibérément absent avant l'alpha.3, faute d'un
  moteur de jobs pour s'en servir.
- `core::translation::job` — `run_job()` : dédoublonnage par texte
  source (`group_by_source`/`spread_to_followers`), chunks de 50,
  vérification qualité (une interpolation manquante ou du HTML
  inattendu rejette la suggestion ; un tag manquant ou une longueur
  inhabituelle ne fait qu'avertir), relances en chunks de 8 puis 1.
  `async`, pas de thread de fond : un canal `JobEvent` (Chunk / Progress
  / Complete / Event) remplace les quatre callbacks Python, à charge de
  l'appelant de les relayer vers une interface plus tard.
- `mcp_server::{session, server}` — port de `mcp_server/session.py` et
  `server.py`. `ServerState`/`ProjectSession` portent les mêmes règles :
  les deux permissions destructrices (`--allow-overwrite-validated`,
  `--allow-clear`) sont des drapeaux de ligne de commande et rien
  d'autre, `use_project` ne rouvre qu'un projet que le registre connaît
  déjà (ou le seul projet épinglé par `--project`). Les 15 outils
  read/write de la révision sont exposés via `#[tool_router]`/`#[tool]`
  de `rmcp` ; chaque tool renvoie `Result<Json<T>, String>`, l'erreur
  atterrissant côté client comme contenu `isError: true` plutôt que
  comme erreur de protocole, à l'image des `ValueError` Python.

126 tests, `cargo clippy` propre. Vérifié en conditions réelles plutôt
que par la seule compilation : un vrai aller-retour JSON-RPC stdio
(`initialize` → `tools/list` → `tools/call`) contre un projet 1.0.0 de
40 820 lignes déjà extrait par l'application Python, lu tel quel. Ce
test a débusqué et corrigé deux pièges Windows purs — `std::fs::
canonicalize` préfixe `\\?\`, que `dunce::canonicalize` évite, et
`PathBuf::join` n'insère qu'un séparateur sans reparser son argument,
laissant un `/` de travers dans un chemin autrement à antislashs — ni
l'un ni l'autre ne se serait vu sur une machine Unix ou dans des tests
unitaires comparant des `Path` plutôt que la chaîne SQL exacte.
Toujours en lecture seule côté Tauri : `src-tauri/src/db.rs` reste la
seule commande de l'app desktop, héritée de l'alpha.1.

Non porté, volontairement : `fill_from_memory` et `detect_characters`
ont besoin de `core::storage::translation_memory` et
`core::renpy::character_detector`, ni l'un ni l'autre construits sur
cette branche. Le canal de rafraîchissement en direct (`core::live`)
reste absent aussi — Python le documente déjà comme « un bonus, jamais
une dépendance », et rien ici ne fait encore tourner l'écran de révision
pour l'écouter. `on_batch_start` et l'annulation fine que Python propage
jusque dans le sous-découpage interne de chaque fournisseur restent
également hors périmètre, comme décrit pour l'alpha.3. Toujours absents
aussi : le pipeline d'extraction (`renpy/cli.py`, `renpy/engine.py`) et
l'écriture dans les `.rpy`.

## Développement

```bash
npm install
npm run tauri dev
```

Serveur MCP, en stdio, un projet déjà extrait par l'application :

```bash
cargo run --manifest-path src-tauri/Cargo.toml --bin rts-mcp -- --project <dossier-du-jeu>
```

Vérifications avant commit :

```bash
cargo fmt --check --manifest-path src-tauri/Cargo.toml
cargo clippy --all-targets --manifest-path src-tauri/Cargo.toml
cargo test --manifest-path src-tauri/Cargo.toml
npm run check
```

## Prochaine étape

À décider avec la feuille de route : ce que la beta.2 a différé
(extraction, interchange, i18n, génération du résumé d'univers,
sélecteurs natifs) avant de passer aux versions suivantes.
