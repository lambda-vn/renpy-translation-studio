# Ren'Py Translation Studio — 2.0.0 (Rust)

Réécriture Rust de [Ren'Py Translation Studio](../README.md), sur la
branche `rust`. Voir la feuille de route pour le découpage complet en
sous-versions et les décisions d'architecture (Tauri, Svelte, données
compatibles avec la 1.0.0 Python, MCP sur
[modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk)).

`main` n'est remplacé qu'à la sortie de la 2.0.0 — cette branche coexiste
avec le code Python (`../src/`) le temps du chantier.

## État actuel : `2.0.0-alpha.2`

Le noyau et les trois fournisseurs retenus tournent sans interface,
testés en ligne de commande (`cargo test`), sur le schéma et le contrat
de données exacts gelés par la politique de compatibilité de
[`../CLAUDE.md`](../CLAUDE.md#compatibilité-post-100). Tout vit sous
`src-tauri/src/core/`, module par module en regard de `../src/core/` :

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
  sont copiés du Python, pas simplifiés — CLAUDE.md l'interdit.

97 tests, `cargo clippy` propre. Rien n'écrit encore sur une vraie base
depuis une interface : `src-tauri/src/db.rs` reste la seule commande
Tauri, en lecture seule, héritée de l'alpha.1.

Non porté ici, volontairement : le moteur de jobs (chunks, retries,
annulation, événements de progression — c'était `on_batch_start` /
`is_cancelled` / `on_event` côté Python), le pipeline d'extraction
(`renpy/cli.py`, `renpy/engine.py`), l'écriture dans les `.rpy`, et le
canal de rafraîchissement en direct.

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

`2.0.0-alpha.3` : le moteur de jobs — `tokio` à la place du thread de
fond Python, chunks de 50 comme granularité de reprise/annulation,
retries automatiques en chunks réduits, événements poussés vers
l'appelant. C'est ce qui donnera enfin un sens à `on_batch_start` /
`is_cancelled` / `on_event`, volontairement absents des fournisseurs
ci-dessus.
