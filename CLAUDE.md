# Ren'Py Translation Studio — Instructions pour Claude Code

## Vue d'ensemble

Application desktop de gestion des traductions pour jeux Ren'Py.
Workflow complet : extraction des textes d'un jeu → révision dans une UI
dédiée avec statuts par ligne → traduction automatique via des fournisseurs
MT/LLM → réécriture des fichiers `tl/` → export zip.

Fournisseurs disponibles : **DeepL**, **Ollama** (LLM local),
**LibreTranslate**, **Claude** (Anthropic) et **Mistral**.
Claude et Mistral sont marqués « Bêta » : jamais testés contre l'API réelle.

Stack : **Python 3.12+ / Flet / uv / SQLite**

---

## Stack et outils

| Outil       | Rôle                                              | Commande clé                   |
|-------------|---------------------------------------------------|--------------------------------|
| `uv`        | Gestionnaire de paquets et virtualenv             | `uv run`, `uv add`             |
| `ruff`      | Linter + formatter (remplace black, flake8, isort)| `uv run ruff check`, `ruff format` |
| `mypy`      | Typage statique (strict)                          | `uv run mypy src/`             |
| `pytest`    | Tests unitaires                                   | `uv run pytest`                |
| `flet`      | Framework UI desktop (rendu Flutter)              | `uv run flet run src/main.py`  |
| `pre-commit`| Hooks Git (format, lint, commit-msg)              | `pre-commit install`           |
| `flet build`| Binaire desktop, une cible par système            | `uv run python scripts/build.py`|

Python cible : **3.12 minimum**.
Ne jamais utiliser `pip` directement — toujours passer par `uv`.

`uv` crée automatiquement un `.venv` à la racine du projet au premier `uv run`
ou `uv sync`. Ne jamais l'activer manuellement, ne jamais le committer.

Après chaque modification : `uv run ruff check`, `uv run ruff format --check`,
`uv run mypy src/` et `uv run pytest` doivent passer sans erreur.

---

## Structure du projet

```
renpy-translation-studio/
├── src/
│   ├── main.py                        # Point d'entrée Flet + navigation entre vues
│   ├── app/
│   │   ├── state.py                   # AppState : état global partagé entre vues
│   │   ├── theme.py                   # Couleurs, styles, focusable()
│   │   ├── shortcuts.py               # Table unique des raccourcis clavier
│   │   ├── dialogs.py                 # Boutons et confirmations de dialogue
│   │   ├── toasts.py                  # Retour d'action éphémère
│   │   ├── ui_thread.py               # safe_update() / on_ui_thread()
│   │   ├── live_server.py             # Écoute locale des notifications (voir plus bas)
│   │   ├── components/
│   │   │   ├── app_header.py          # Bandeau supérieur (nom du jeu, langue)
│   │   │   ├── back_link.py           # Retour vers l'écran précédent
│   │   │   ├── help_dialog.py         # Liste des raccourcis (F1)
│   │   │   ├── settings_dialog.py     # Dialogue des paramètres généraux
│   │   │   └── stepper.py             # Indicateur d'étapes (Setup/Review/Export)
│   │   └── views/
│   │       ├── onboarding.py          # Premier lancement (langue UI, SDK)
│   │       ├── project_setup.py       # Dossier du jeu + langues + méthode d'extraction
│   │       ├── review_view.py         # Hub principal : révision, jobs de traduction
│   │       ├── provider_config.py     # Config des 5 fournisseurs (accordéons + badges)
│   │       ├── character_glossary_view.py  # Glossaire des personnages
│   │       ├── universe_summary_view.py    # Résumé d'univers (+ génération IA)
│   │       └── export_view.py         # Export zip
│   ├── core/
│       ├── languages.py               # Liste centrale des langues (voir plus bas)
│       ├── validators.py              # Codes langue, chemins sûrs, dossier projet
│       ├── settings.py                # Settings JSON persistants (str | None uniquement)
│       ├── app_dirs.py                # Emplacement des fichiers de configuration
│       ├── i18n.py                    # Traductions UI (src/locales/en.json, fr.json)
│       ├── logging_config.py          # Journalisation (mode verbeux via settings)
│       ├── exporter.py                # Export zip + GameNameResolver
│       ├── export_sync.py             # Écart entre la base et les fichiers tl/
│       ├── file_reveal.py             # Montrer un fichier dans l'explorateur
│       ├── interchange.py             # Fichiers bilingues CSV / XLIFF 1.2 / JSON
│       ├── live.py                    # Canal de notification (voir plus bas)
│       ├── project_actions.py         # Mémoire et détection, hors des vues
│       ├── renpy/
│       │   ├── parser.py              # TranslateBlockParser (lit les tl/ générés par le SDK)
│       │   ├── cli.py                 # Wrapper subprocess du SDK Ren'Py (extraction)
│       │   ├── writer.py              # Réécriture des traductions dans les .rpy
│       │   └── character_detector.py  # Détection auto des personnages
│       ├── storage/
│       │   ├── database.py            # SQLite par projet (<jeu>/.rts/translations.db)
│       │   ├── repositories.py        # TranslationUnit/Character/ProjectMeta (CRUD)
│       │   ├── recent_projects.py     # Registre des projets récents (résumé/reprise)
│       │   └── translation_memory.py  # Mémoire commune à la machine, hors projet
│       └── translation/
│           ├── job.py                 # Job de fond : chunks, qualité, retries, événements
│           ├── quality.py             # Contrôles qualité ([var], balises {tag}, longueur)
│           ├── context_builder.py     # Prompts LLM + découpage en batchs
│           ├── universe_generator.py  # Résumé d'univers généré par LLM
│           └── providers/
│               ├── base.py            # Protocoles + types partagés
│               ├── registry.py        # Construit les providers depuis les settings
│               ├── deepl.py           # DeepL (+ glossaire serveur)
│               ├── ollama.py          # LLM local (garde-fous petits modèles)
│               ├── libretranslate.py  # Instance LibreTranslate (1 requête / unité)
│               ├── claude_provider.py # API Anthropic (bêta)
│               ├── mistral_provider.py # API Mistral (bêta)
│               └── llm_common.py      # Helpers partagés Claude/Mistral
│   ├── locales/                       # en.json + fr.json (i18n de l'UI)
│   └── mcp_server/
│       ├── __main__.py                # Ligne de commande, transport stdio
│       ├── session.py                 # Projet ouvert + permissions du processus
│       └── server.py                  # Les 17 outils exposés au client
├── tests/                             # ~37 fichiers, fixtures .rpy réelles
├── scripts/build.py                   # Compilation pour le système courant
├── .github/workflows/                 # ci.yml (3 OS) + build.yml (3 binaires)
├── pyproject.toml
├── .pre-commit-config.yaml
└── CLAUDE.md                          # Ce fichier
```

---

## Architecture

### Pipeline de traduction

1. **Extraction** (`project_setup`) : le SDK Ren'Py (`renpy translate` via
   subprocess) génère les fichiers `tl/`, relus par `TranslateBlockParser`.
   Les blocs extraits sont insérés en base SQLite
   (`<jeu>/.rts/translations.db`).
2. **Base de données** : une ligne par bloc, `block_id UNIQUE`. Cinq
   statuts : `not_translated` → `ai_suggested` → `human_validated`, plus
   `draft` pour un texte édité mais non validé (compté, effaçable) et
   `imported` pour ce qui vient d'ailleurs sans avoir été relu ici,
   fichier bilingue ou mémoire de traduction. Une ligne
   `human_validated` n'est jamais écrasée par une suggestion IA.
   Un drapeau `needs_review` et une note vivent à côté du statut, posés
   à la main et jamais réécrits par un job ou un import.
   La base est en WAL : un projet est atteint par plus d'un processus,
   le serveur MCP par construction et deux fenêtres sans que rien ne
   l'empêche.
3. **Jobs de traduction** (`translation/job.py`) : thread de fond, chunks
   de 50, contrôles qualité par ligne, retries automatiques des échecs en
   chunks réduits, événements UI. Seules les unités `not_translated` sont
   envoyées ; tout est apparié par `block_id`, jamais par position.
4. **Écriture** (`writer.py`) : blocs dialogue appariés par `block_id`,
   blocs `strings` par texte `old` — jamais par position. Backup avant
   modification.
5. **Export** (`exporter.py`) : zip `<nom-du-jeu>/game/tl/<langue>/`,
   exclusion `.rpyc`, refus des traversées `../`.

### Fournisseurs de traduction (`core/providers/`)

Interface commune `TranslationProvider` (protocole structurel) :
`translate_batch(TranslateBatchRequest) -> TranslateBatchResult` +
`test_connection()`. Capacités optionnelles :

- `SupportsGlossary` (DeepL) : les notes de personnage `Nom -> Traduction`
  deviennent un glossaire serveur, synchronisé paresseusement au premier batch.
- `SupportsCompletion` (Ollama, Claude, Mistral) : `complete(prompt)` pour
  la génération du résumé d'univers.

Le `registry` construit les providers depuis les settings et leur passe le
contexte (résumé d'univers + glossaire personnages).

**Ajouter un provider** : créer le module dans `core/providers/`, l'ajouter
au `registry` (get + available), déclarer ses clés dans `settings.DEFAULTS`,
ajouter sa section dans `provider_config.py`, son label dans
`review_view._PROVIDER_LABELS`, les clés i18n (en + fr) et un fichier de
tests mocké.

**Garde-fous Ollama** : les docstrings de `ollama.py` et le schéma de sortie
structurée encodent des contournements durement acquis de bugs de petits
modèles quantifiés (arrêt prématuré, padding par duplication, mauvais noms
de clés, confusion de libellés courts). Ne pas les simplifier.

### Serveur MCP (`src/mcp_server/`)

Un second point d'entrée sur le même coeur, pour qu'un assistant déjà
payé par l'utilisateur fasse la traduction sans clé API ni GPU. Lancé
par le client, en stdio :

```bash
uv run --directory <depot> python -m mcp_server
```

**Pas de script console.** Un `rts-mcp.exe` installé serait verrouillé
par Windows tant qu'un client tient le serveur ouvert, ce qui empêche
`uv run` de réinstaller le projet et donc de lancer l'application. Ne
pas réintroduire `[project.scripts]`.

Un serveur sert tous les projets de la machine : `list_projects` lit le
registre des projets récents, `use_project` en ouvre un. Il **refuse
tout dossier absent de ce registre**, écrit par l'application quand un
humain configure un jeu : l'ensemble atteignable est celui que
l'utilisateur a construit, pas celui qu'un modèle nomme. `--project`
épingle un serveur sur un seul jeu.

Les dix-sept outils sont les actions de l'écran de révision. Une
soumission repasse par `quality.check()` et arrive en `ai_suggested`.
Les deux permissions destructrices, `--allow-overwrite-validated` et
`--allow-clear`, sont **des drapeaux de ligne de commande et rien
d'autre** : le client lit le texte du jeu, écrit par un tiers, donc une
réplique réclamant l'effacement ne doit pas être une demande que le
modèle puisse s'accorder. Ne pas les transformer en arguments d'outil.

Les chemins sortent relatifs à la racine du projet, les deux formes
étant acceptées en entrée. La base stocke des chemins absolus datant de
l'extraction : les envoyer tels quels répéterait l'arborescence du
disque à chaque ligne de chaque page.

### Rafraîchissement en direct (`core/live.py`, `app/live_server.py`)

L'écran de révision se remplit pendant qu'un autre processus écrit.
SQLite n'offre aucune notification entre processus, et le module
`sqlite3` n'expose même pas de hook de connexion, donc le canal est à
nous.

L'application écoute sur la boucle locale tant que l'écran de révision
est ouvert, et publie son port et un jeton dans
`<jeu>/.rts/live.json`. Le serveur MCP y poste les `block_id` écrits,
ou un signal de rechargement pour les actions en masse, qui répondent
par un compte et n'ont pas d'identifiants à donner.

**La notification est un bonus, jamais une dépendance** : personne à
l'écoute, fichier absent ou connexion refusée sont le cas ordinaire et
`notify()` ne lève pas. C'est ce qui fait qu'une application fermée
n'est pas un cas à traiter.

Les lignes visibles sont mises à jour **sur place**, jamais par un
rechargement de page : sous un filtre `not_translated`, recharger les
ferait disparaître au lieu de les remplir. La ligne portant le curseur
est sautée quoi qu'il arrive.

Le jeton n'arrête qu'une chose, une page web, qui peut poster sur un
port local mais ne peut pas lire le disque. Il n'arrête rien tournant
sous le compte de l'utilisateur.

### Langues (`core/languages.py`)

Liste centrale unique : chaque entrée déclare le nom du dossier `tl/`,
le libellé affiché, le code ISO court (LibreTranslate), un tag BCP-47
régional optionnel et un override DeepL éventuel. Elle alimente les
dropdowns du setup, `is_recognized_language()` et les resolvers des
providers MT. **Ajouter une langue = ajouter une entrée ici, rien d'autre.**

`localized_label(code)` donne le nom de la langue dans la langue de
l'interface : c'est ce que doit afficher tout écran nommant une langue,
le code brut restant réservé à ce qui est écrit sur le disque, dossier
`tl/` et nom du zip exporté. Il lit la clé `languages.<code>` des locales
et retombe sur le `label` anglais de l'entrée quand elle est absente : une nouvelle
langue reste donc bien une seule entrée, son nom s'affichant en anglais
tant que les deux locales ne la traduisent pas.

### Settings et i18n

- `settings.py` ne stocke que des `str | None`. Un entier se stocke en
  chaîne et se parse à la lecture avec un fallback sur le défaut.
- Toute chaîne visible par l'utilisateur passe par `i18n.t()` avec une clé
  dans `src/locales/en.json` **et** `src/locales/fr.json`. Les nouvelles chaînes
  françaises prennent des accents corrects.

### UI Flet et threads

- Flet 0.85 : vérifier les propriétés dans la source installée avant de
  s'en servir (ex. `Dropdown` expose `on_select`, pas `on_change`).
- Toute mutation de l'arbre de contrôles déclenchée par un thread de fond
  doit être planifiée sur la boucle d'événements (voir `_on_ui_thread()` et
  `_safe_update()` dans `review_view.py`) — sinon le diff de `page.update()`
  plante en `IndexError`.
- Appels réseau dans un handler UI : toujours en thread de fond
  (`page.run_thread`) avec un statut immédiat, jamais bloquant.

---

## Standards de code

### Conventions Python générales

- **PEP 8** est la référence. Ruff tranche les cas non couverts.
- Longueur de ligne : 100 caractères (souple), Ruff fait autorité.
- Fichiers encodés en UTF-8, sans déclaration `# -*- coding: utf-8 -*-`.
- Fonctionnalités Python 3.10+ encouragées : `X | Y` pour les unions de types,
  `match ... case` au-delà de 3 cas sur une valeur unique, opérateur walrus `:=`
  si la lisibilité y gagne.

### Imports

- Toujours en tête de fichier, après le docstring du module.
- Toujours en trois blocs séparés par une ligne vide :
  bibliothèque standard → dépendances tierces → modules internes.
- Toujours des **imports absolus** (`from core.renpy.parser import X`,
  jamais `from ..parser import X`).
- Jamais `from module import *`.
- Trier alphabétiquement au sein de chaque bloc (délégué à Ruff).

### Typage

- Toutes les signatures de fonctions/méthodes et attributs de classe sont annotés.
  `-> None` est obligatoire si aucune valeur n'est retournée.
- Syntaxe native : `X | Y`, `list[str]`, `dict[str, int]` — jamais
  `Optional[X]`, `Union[X, Y]`, `List[str]`, `Dict[str, int]` du module `typing`.
- `Any` est interdit sans commentaire de justification et sans avoir envisagé
  un type plus précis (`TypedDict`, `Protocol`, générique).
- `mypy` en mode strict doit passer sans erreur avant tout commit.

### Nommage

| Élément             | Convention          |
|---------------------|---------------------|
| Variables, fonctions, méthodes | `snake_case` |
| Classes, exceptions | `PascalCase`        |
| Constantes de module ou de classe | `UPPER_SNAKE_CASE` |
| Attributs/méthodes internes | `_prefixe` (simple underscore) |

- Noms à l'impératif pour les fonctions : `send_email`, pas `email_sender`.
- Pas d'abréviations peu courantes. Pas d'articles ni de possessifs (`car`, pas `my_car`).
- Les exceptions se terminent par `Error` (`TranslationProviderError`).

### Chaînes de caractères

- Guillemet **simple** (`'`) par défaut, sauf si l'apostrophe ou le guillemet
  doit apparaître dans la chaîne.
- **f-strings** pour toute interpolation — jamais `%` ni `.format()`.
- Triple guillemets doubles (`"""`) pour les docstrings (PEP 257).

### Docstrings

Format Google, obligatoire pour tout module, classe, fonction et méthode publique :

```python
def find_block(block_id: str) -> TranslationBlock | None:
    """Return the translation block with the given identifier.

    Args:
        block_id: Unique Ren'Py block identifier (e.g. "start_636ae3f5").

    Returns:
        The matching block, or None if not found.

    Raises:
        DatabaseError: If the SQLite connection is unavailable.
    """
```

Sections `Args`, `Returns`, `Raises` obligatoires dès que le nom seul
ne suffit pas à comprendre le rôle d'un paramètre ou la nature du retour.

### Commentaires

- **Pas de commentaires inline** : les `# commentaire` sur la même ligne
  que du code sont interdits en code de production.
- Pas de reformulation du code en prose dans les commentaires.
- Pas de commentaire sur une fonction dont le nom est déjà explicite.
- Les justifications non évidentes vont dans les docstrings, pas en inline.

### Classes

- `@dataclass` pour les objets porteurs de données sans comportement complexe.
- Toujours **composition** plutôt qu'héritage si possible.
- Attributs et méthodes internes préfixés par `_`. Double underscore (`__`)
  réservé au name mangling volontaire.

### Fonctions et méthodes

- Arguments par défaut mutables interdits (`list`, `dict`, `set`).
  Utiliser `None` avec une initialisation dans le corps.
- Au-delà de deux ou trois paramètres, utiliser des arguments keyword-only (`*`).
- Lambda uniquement pour les callbacks triviaux tenant sur une ligne.

### Collections

- Notation littérale (`[]`, `{}`, `()`) plutôt que constructeurs (`list()`, `dict()`).
- Virgule après le dernier élément d'une collection multiligne.
- Compréhension de liste/dict/set préférée à une boucle `for` + `.append()`
  si l'expression reste lisible sur une ligne.
- Pas plus de deux niveaux de compréhension imbriqués.

### Gestion des erreurs

- Toujours cibler une exception **spécifique** — jamais `except:` nu,
  jamais `except Exception` sauf au point d'entrée de l'application.
- `raise ... from ...` (ou `from None`) plutôt que relancer sans contexte.
- `with` pour toute ressource à libérer (fichier, connexion, verrou).
- Les erreurs prévisibles d'un provider lèvent `TranslationProviderError`
  avec un message utilisateur propre.

### Boucles et conditions

- `enumerate()` pour accéder à l'index et à la valeur, jamais `range(len(...))`.
- Si un `if` se termine par `return`/`raise`/`continue`/`break`, pas de `else`.
- Ternaire pour les affectations simples à deux issues, jamais imbriqué.
- `match ... case` au-delà de trois cas sur une valeur unique (Python 3.10+).

### Opérateurs

- `if x` / `if not x` plutôt que `if x == True` / `if x == False`.
- `is` / `is not` pour comparer à `None`, `True`, `False` ou l'identité d'objet.
- `==` / `!=` pour les valeurs.

---

## Sécurité

- `subprocess.run()` : **toujours une liste d'arguments, jamais `shell=True`**.
- Chemins utilisateur : toujours `Path.resolve()` + vérification de borne.
- Noms de fichiers dans le zip : vérifier l'absence de `../` avant ajout.
- Clés API : ne jamais les logger (même partiellement), ne jamais les
  inclure dans un message d'erreur. Elles vivent dans les settings locaux.
- Envoi de contenu du jeu à un service tiers (génération IA du résumé) :
  confirmation explicite de l'utilisateur à chaque fois.

---

## Tests

Tests unitaires uniquement — pas de tests Flet / end-to-end. Les vues UI
sont validées par un smoke-import et un test manuel de l'application.

- Les providers sont testés avec des clients/HTTP mockés (`monkeypatch`),
  jamais contre les vraies APIs.
- Les fixtures `.rpy` dans `tests/fixtures/` sont de vrais extraits Ren'Py.
- Tout nouveau comportement de `core/` arrive avec ses tests.

```bash
uv run pytest
uv run pytest tests/test_parser.py -v   # un fichier spécifique
```

---

## Commits

Format Conventional Commits, validé par pre-commit.
Voir `COMMIT_CONVENTION.md` pour les types, scopes et exemples détaillés.

Scopes courants : `archive`, `parser`, `exporter`, `validators`,
`providers`, `deepl`, `ollama`, `libretranslate`, `ui`, `project-setup`,
`translation-review`, `export-view`, `deps`, `ci`, `tests`.

Ne jamais lancer `git commit` sans validation explicite de l'utilisateur,
même en pleine implémentation d'une roadmap qui décrit un commit par
phase — cela décrit l'état final souhaité, pas une autorisation à
committer seul. Attendre un "ok", "vas-y", "commit" ou équivalent avant
chaque commit, y compris entre deux phases d'une même roadmap.

---

## Points d'attention connus

- **Générateur builtin supprimé** : `core/renpy/generator.py`
  (`TranslateBlockGenerator`) a été retiré. Le SDK Ren'Py (`renpy translate`
  via subprocess) est la seule méthode d'extraction. Ne pas réimplémenter un
  générateur maison : le SDK est la source de vérité pour les formats Ren'Py.
  `TranslateBlockParser` (`parser.py`) est conservé, mais uniquement pour lire
  les fichiers `tl/` **générés par le SDK**, pas pour parser les sources.
- **Les interpolations `[...]` sont du code Python** : Ren'Py évalue le
  contenu des crochets comme une expression (`config.interpolate_exprs`).
  `quality.check()` refuse donc toute interpolation présente dans la
  traduction et absente de la source (`extra_var`), en erreur bloquante et
  non en avertissement. Ne pas assouplir ce contrôle : l'échappement de
  `writer.py` ne protège de rien ici, la charge ne sortant jamais de la
  chaîne. Les entrées non fiables sont l'import de fichier bilingue et la
  réponse d'un fournisseur, et le dossier `tl/` produit part chez les
  joueurs du jeu.
- **Panneau de fichiers non redimensionnable** : Flet n'expose aucun
  contrôle de panneaux redimensionnables et `VerticalDivider` est purement
  décoratif. La seule voie est une poignée faite main, un `GestureDetector`
  dont `on_pan_update` réécrit la largeur, soit un aller-retour
  Python/Flutter par frame de glissement ; essayé, rend mal. `_PANEL_WIDTH`
  reste fixe, les noms longs restant couverts par l'infobulle. Si le besoin
  revient, basculer entre deux largeurs fixes persistées plutôt que de
  refaire une poignée.
- **Glossaire de termes écarté** (1er août 2026) : hors personnages, aucun
  besoin mesuré ne le justifie pour l'instant. Pour le vérifier sans rien
  coder, écrire les termes dans le résumé d'univers, qui part déjà dans le
  prompt système des trois LLM. S'il faut le faire un jour, n'injecter que
  les termes présents dans les sources du batch, dans `build_batch_prompt()`
  et jamais dans `build_system_prompt()` : coût constant quelle que soit la
  taille du glossaire, cache de prompt intact. Un tool ne convient pas, un
  modèle n'appelant un outil que s'il se sait ignorant, ce qui n'arrive
  justement pas sur un terme qu'il croit savoir traduire.
- **`flet build` ne compile pas en croisé** : chaque cible se construit
  sur son propre système, d'où la matrice à trois runners de
  `build.yml`. macOS est limité à `--arch arm64` : la tranche x86_64
  doit recompiler `cryptography` depuis les sources, donc du Rust en
  croisé sur un runner Apple Silicon, et son outillage casse. Rien dans
  ce dépôt ne peut corriger ça.
- **Les locales vivent dans `src/`** parce que `[tool.flet.app] path`
  vaut `src` et que le binaire n'embarque que ça. Les remonter à la
  racine produirait une application sans une seule chaîne d'interface.
- **Compilation Windows en local** : elle échoue si le seul CMake de la
  machine est celui de Visual Studio, qui est 32 bits. Le plugin
  `serious_python_windows` lit `$ENV{WINDIR}/System32`, redirigé vers
  `SysWOW64` pour un processus 32 bits, et y prend des DLL 32 bits pour
  une application 64 bits avant d'échouer sur `vcruntime140_1.dll`, qui
  n'existe qu'en 64 bits. C'est un bug amont ; les runners GitHub n'y
  sont pas exposés, la CI passe.
- **Ne pas modifier les prompts LLM** (`build_system_prompt`,
  `build_batch_prompt`) ni le schéma de sortie structurée sans test réel
  sur un petit modèle : ils encodent des contournements de bugs.
- **Ne pas dépasser `MAX_NUM_CTX` (8192)** côté Ollama : au-delà, le cache
  KV déborde de la VRAM et la génération s'effondre. Le plafond ne
  s'applique **pas** aux modèles cloud, reconnus au suffixe `-cloud` :
  rien n'est chargé sur la machine, donc il ne protège de rien et coûte
  des batchs réduits dès que le prompt système est gros.
- **`_CHUNK_SIZE` (50) dans `translation/job.py`** est la granularité de
  persistance/annulation, pas la taille des requêtes provider.
- Les suggestions IA erronées d'anciens jobs persistent tant qu'elles ne
  sont pas corrigées ou effacées : un nouveau job ne retraduit que les
  unités `not_translated`.
- Journalisation détaillée (settings) : les providers loggent chaque
  requête/réponse en DEBUG — premier réflexe pour diagnostiquer une
  traduction suspecte.
