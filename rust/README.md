# Ren'Py Translation Studio — 2.0.0 (Rust)

Réécriture Rust de [Ren'Py Translation Studio](../README.md), sur la
branche `rust`. Voir la feuille de route pour le découpage complet en
sous-versions et les décisions d'architecture (Tauri, Svelte, données
compatibles avec la 1.0.0 Python, MCP sur
[modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk)).

`main` n'est remplacé qu'à la sortie de la 2.0.0 — cette branche coexiste
avec le code Python (`../src/`) le temps du chantier.

## En cours : `2.0.0-rc.2`

La rc.2 est la check-list de parité contre la 1.0.0 : voir
[`PARITY.md`](PARITY.md), qui dit ligne par ligne ce qui est fait, partiel
ou absent. Première étape livrée : **l'extraction**.

`core::extraction` lance Ren'Py et met la base à jour ; il s'appuie sur
`core::renpy::{engine, cli, archive, unpacker}` (moteur du jeu puis SDK,
sous-processus avec délai, désarchivage des `.rpa` dont l'index est lu
par un décodeur de pickle volontairement restreint, sources refusées
écartées) et sur trois opérations de base de données portées pour
l'occasion (`resync_sources`, `transfer_orphan_translations`,
`delete_stale`). L'écran de configuration de projet (dossier par
sélecteur natif, langues, SDK, trois modes si une traduction existe) et
le mécanisme d'i18n (catalogues de la 1.0.0 repris) sont en place. Le
nettoyage des sources dépaquetées suit l'export du zip, comme en 1.x.

**Vérifié** : 224 tests ; contre le vrai SDK 8.5.3 sur une copie de The
Question (qui livre déjà un `tl/french` : 483 unités, 95 traductions
adoptées en `imported`, 7 lignes sans texte validées d'office, les trois
modes) ; sur un jeu packagé Ren'Py 7 avec son propre moteur et un
`scripts.rpa` (3 008 unités, 121 sources désarchivées) dont les
identifiants sont ceux que lit le parseur Python ; et dans la vraie
fenêtre Tauri, pilotée via le port de débogage de WebView2, du
formulaire à l'écran de révision (interface en français).
**Non vérifié** : le sélecteur natif de dossier (la boîte système n'est
pas pilotable de cette façon, le chemin a été saisi) ; macOS et Linux ;
un jeu dont les archives ne contiennent que des `.rpyc` ou dont une
source est refusée par Ren'Py (couverts par des tests, jamais vus sur un
vrai jeu).

## Précédemment : `2.0.0-rc.1`

La rc.1 ne change pas l'interface : elle rend l'application
installable et prouve qu'elle relit les données de la 1.0.0.

**Mémoire de traduction portée** : `core::storage::translation_memory`
ouvre le même `memory.db` que Python (clé normalisée identique, colonne
`normalized_text` migrée à l'ouverture) et `core::project_actions`
porte `fill_from_memory`. Valider une ligne dans l'interface la
mémorise (sans jamais faire échouer la validation) et rogne désormais
le texte / refuse le vide, comme Python. Le serveur MCP gagne l'outil
`fill_from_memory` : **16 des 17 outils**, il ne manque que
`detect_characters`.

**Tests de compatibilité** (`src-tauri/src/compat_tests.rs`) : les
fixtures de `src-tauri/tests/fixtures/compat/` ne sont pas écrites à la
main, elles sont produites par le code du tag `v1.0.0` lui-même
(`scripts/make_compat_fixtures.py`, commande en tête du script). Huit
tests les rouvrent avec le code Rust : base de projet, `settings.json`,
mémoire de traduction, registre des projets récents. Un neuvième,
`#[ignore]`, lit les vraies données de la machine après les avoir
copiées (`cargo test --lib real_machine -- --ignored --nocapture`) :
mémoire de 171 entrées, `settings.json`, base de 36 981 lignes.

**Empaquetage** : `npm run bundle` compile `rts-mcp` en release, le pose
en sidecar Tauri (`src-tauri/binaries/rts-mcp-<triple>`) et lance
`tauri build` avec `tauri.bundle.conf.json` — le sidecar n'est pas
déclaré dans `tauri.conf.json`, sinon `tauri dev` ne compile plus.
Formats : NSIS sous Windows (**pas de MSI** : WiX n'accepte qu'un
identifiant de pré-version numérique, `rc.1` n'en est pas un), `.app` +
`.dmg` sous macOS, `.deb` + AppImage sous Linux. Le binaire principal
s'appelle `renpy-translation-studio` ; `rust.yml` construit les trois
systèmes, rejoue `fmt`/`clippy`/`test`/`npm run check` et refuse un tag
`v2.*` qui ne correspond pas à la version de `Cargo.toml`,
`tauri.conf.json` et `package.json`. `build.yml` (Python) ignore
désormais les tags `v2.*`.

**Barrière de handshake** : `scripts/mcp_handshake.py <exécutable>`
tient une vraie conversation (`initialize`, `tools/list`, appel de
`list_projects`) et échoue si la liste n'est pas exactement celle des
16 outils attendus. Vérifiée dans les deux sens : 0 contre `rts-mcp`,
1 contre un processus qui ne parle pas.

**Vérifié** : `cargo fmt --check`, `cargo clippy --all-targets` (rien
que du code mort, voir ci-dessous), `cargo test` (164 passent, 1
ignoré), `npm run check` (0 erreur), la syntaxe YAML des workflows et la
logique de comparaison des versions. Sous Windows, `npm run bundle`
produit l'installateur NSIS (4,61 Mio), le handshake passe contre le
sidecar release, et l'exécutable release se lance, garde sa fenêtre
(titre « Ren'Py Translation Studio ») et WebView2 tourne.

**Piège de nom** : `productName` ne doit pas contenir d'apostrophe. Le
gabarit NSIS de Tauri met le chemin du raccourci entre apostrophes dans
un appel `System::Call` ; avec « Ren'Py Translation Studio », `makensis`
échoue sur `NSISCOMCALL requires 4 parameter(s), passed 8`, quelle que
soit la version de NSIS (3.11 et 3.13 essayées). Le produit s'appelle
donc « Renpy Translation Studio » pour l'installateur, les raccourcis
et le dossier d'installation ; seul le titre de la fenêtre garde
l'apostrophe. La CLI Tauri est passée de 2.11.4 à 2.12.4 pendant
l'enquête et le lockfile le reflète ; la 2.11.4 n'a pas été réessayée
avec le nouveau nom.

**Non vérifié** :

- `rust.yml` n'a jamais tourné : aucune exécution sur un runner GitHub.
  Les paquets Linux (`libayatana-appindicator3-dev`, `libdbus-1-dev`),
  `NO_STRIP` pour l'AppImage et les chemins d'artefacts sont écrits
  d'après la documentation de Tauri, pas d'après un run.
- L'installateur n'a pas été exécuté (ni installation, ni désinstallation) ;
  seul l'exécutable qu'il embarque a été lancé, depuis `target/release`.
- macOS et Linux n'ont jamais compilé cette branche.
- Le sidecar tel qu'installé (à côté de l'exécutable principal) n'a
  pas été lancé ; le handshake porte sur le fichier avant empaquetage.
- Toujours aucun clic dans la vraie fenêtre Tauri.

**Avertissements restants** : `cargo clippy` signale du code porté mais
pas encore appelé (le parseur, quelques accesseurs) — attendu tant que
l'extraction n'est pas portée, c'est pourquoi la CI ne refuse pas les
avertissements. `writer.rs` a un `replace` consécutif signalé par
clippy, antérieur à la rc.1.

**Signature des binaires — décision en attente.** Les installateurs ne
sont pas signés : SmartScreen (Windows) et Gatekeeper (macOS)
avertiront, ce que `build.yml` accepte déjà pour la 1.x. Signer
demande des identifiants qu'aucun fichier de ce dépôt ne peut fournir :
un certificat Authenticode (ou un service de signature) pour Windows,
un compte Apple Developer et la notarisation pour macOS, rien d'utile
sous Linux au-delà de sommes de contrôle signées. Tauri sait lire ces
secrets depuis l'environnement du runner ; rien n'est branché tant que
la question n'est pas tranchée.

### Rappel beta.2

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
lançait plus rien. `default-run = "renpy-translation-studio"` dans
`Cargo.toml` le corrige.

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

Non porté, volontairement : `detect_characters` a besoin de
`core::renpy::character_detector`, pas construit sur cette branche
(`fill_from_memory` l'est depuis la rc.1). Le canal de rafraîchissement en direct (`core::live`)
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

Installateur (long : build release avec LTO) et barrière MCP :

```bash
npm run bundle
python scripts/mcp_handshake.py src-tauri/binaries/rts-mcp-<triple>
```

## Prochaine étape

La rc.2 : une check-list de parité contre le tableau de fonctionnalités
du README 1.0.0, qui dira ce que la beta.2 a différé (extraction,
interchange, i18n, génération du résumé d'univers, sélecteurs natifs,
`detect_characters`) et doit encore être porté avant la 2.0.0.
