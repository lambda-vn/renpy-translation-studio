# Ren'Py Translation Studio — 2.0.0 (Rust)

Réécriture Rust de [Ren'Py Translation Studio](../README.md), sur la
branche `rust`. Voir la feuille de route pour le découpage complet en
sous-versions et les décisions d'architecture (Tauri, Svelte, données
compatibles avec la 1.0.0 Python, MCP sur
[modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk)).

`main` n'est remplacé qu'à la sortie de la 2.0.0 — cette branche coexiste
avec le code Python (`../src/`) le temps du chantier.

## État actuel : `2.0.0-beta.1`

Le noyau, les trois fournisseurs retenus et le moteur de jobs tournent
sans interface, testés en ligne de commande (`cargo test`), sur le
schéma et le contrat de données exacts gelés par la politique de
compatibilité de [`../CLAUDE.md`](../CLAUDE.md#compatibilité-post-100).
Une assistante peut déjà traduire un projet avant qu'aucune fenêtre
n'existe : `src-tauri/src/bin/rts_mcp.rs` sert désormais 15 des 17
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

`2.0.0-beta.2` : l'interface complète, Svelte au-dessus de tout ce qui
précède — l'écran de révision, la configuration des fournisseurs, le
glossaire de personnages, l'export.
