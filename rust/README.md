# Ren'Py Translation Studio — 2.0.0 (Rust)

Réécriture Rust de [Ren'Py Translation Studio](../README.md), sur la
branche `rust`. Voir la feuille de route pour le découpage complet en
sous-versions et les décisions d'architecture (Tauri, Svelte, données
compatibles avec la 1.0.0 Python, MCP sur
[modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk)).

`main` n'est remplacé qu'à la sortie de la 2.0.0 — cette branche coexiste
avec le code Python (`../src/`) le temps du chantier.

## État actuel : `2.0.0-alpha.1`

Preuve de pile. `src-tauri/src/db.rs` ouvre en lecture un
`translations.db` produit par la 1.0.0 Python (`rusqlite`, SQLite
embarqué, aucune dépendance système) sur le schéma exact gelé par la
politique de compatibilité de [`../CLAUDE.md`](../CLAUDE.md#compatibilité-post-100).
Un écran Svelte minimal appelle cette commande via `invoke()` et affiche
le compte d'unités et la liste des premières lignes.

Rien n'écrit encore sur la base.

## Développement

```bash
npm install
npm run tauri dev
```

Vérifications avant commit :

```bash
cargo fmt --check --manifest-path src-tauri/Cargo.toml
cargo clippy --all-targets --manifest-path src-tauri/Cargo.toml
cargo check --manifest-path src-tauri/Cargo.toml
npm run check
```

## Prochaine étape

`2.0.0-alpha.2` : portage du noyau (parseur `tl/`, stockage, settings,
contrôle qualité) sans interface, testé en ligne de commande.
