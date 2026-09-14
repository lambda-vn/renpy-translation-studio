# Ren'Py Translation Studio — 2.0.0 (Rust)

Réécriture Rust de [Ren'Py Translation Studio](../README.md), sur la
branche `rust`. Voir la feuille de route pour le découpage complet en
sous-versions et les décisions d'architecture (Tauri, Svelte, données
compatibles avec la 1.0.0 Python, MCP sur
[modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk)).

`main` n'est remplacé qu'à la sortie de la 2.0.0 — cette branche coexiste
avec le code Python (`../src/`) le temps du chantier.

## État actuel : `2.0.0-alpha.3`

Le noyau, les trois fournisseurs retenus et le moteur de jobs tournent
sans interface, testés en ligne de commande (`cargo test`), sur le
schéma et le contrat de données exacts gelés par la politique de
compatibilité de [`../CLAUDE.md`](../CLAUDE.md#compatibilité-post-100).
Tout vit sous `src-tauri/src/core/`, module par module en regard de
`../src/core/` :

- `core::languages` — la liste des 19 langues et `get_language()`.
- `core::settings` — `settings.json` + trousseau OS pour les deux clés
  API, même répertoire de config que l'app Python
  (`dirs::config_local_dir()`, équivalent de `appauthor=False`).
- `core::storage` — schéma SQLite (WAL, déclencheurs, le même contrat
  `human_validated` jamais écrasé) et un sous-ensemble volontairement
  partiel des dépôts : lecture/écriture des unités, personnages,
  métadonnées de projet. Ni le pipeline d'extraction ni les outils MCP
  destructeurs n'existent encore.
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

110 tests, `cargo clippy` propre. Rien n'écrit encore sur une vraie base
depuis une interface : `src-tauri/src/db.rs` reste la seule commande
Tauri, en lecture seule, héritée de l'alpha.1.

Non porté, volontairement : `on_batch_start` et l'annulation fine que
Python propage jusque dans le sous-découpage interne de chaque
fournisseur (chaque requête HTTP d'Ollama, chaque chunk DeepL) — ici
l'annulation n'est vérifiée qu'aux limites des chunks du moteur de jobs
(50, puis 8, puis 1), plus grossier mais borné. Toujours absents : le
pipeline d'extraction (`renpy/cli.py`, `renpy/engine.py`), l'écriture
dans les `.rpy`, et le canal de rafraîchissement en direct.

## Développement

```bash
npm install
npm run tauri dev
```

Vérifications avant commit :

```bash
cargo fmt --check --manifest-path src-tauri/Cargo.toml
cargo clippy --all-targets --manifest-path src-tauri/Cargo.toml
cargo test --manifest-path src-tauri/Cargo.toml
npm run check
```

## Prochaine étape

`2.0.0-beta.1` : le serveur MCP, sur
[modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk)
— une assistante pourra déjà traduire un projet avant qu'aucune fenêtre
n'existe.
