[← Documentation](README.md)

# Serveur MCP

*[English version](../en/mcp-server.md)*

Un second point d'entrée sur le même cœur, pour qu'un assistant que vous
payez déjà fasse la traduction — sans clé API, sans GPU. C'est un programme
à part, `rts-mcp`, qui parle le Model Context Protocol sur stdio.

## Le mettre en place

Le serveur est lancé par le client, qui a besoin du chemin de
l'exécutable.

### Depuis l'application installée

L'installateur pose `rts-mcp` (`rts-mcp.exe` sous Windows) dans le même
dossier que l'exécutable de l'application, `renpy-translation-studio`.
Pointez le client dessus :

```bash
claude mcp add renpy-studio -- "/chemin/vers/rts-mcp"
```

Tout autre client demande les deux mêmes choses dans sa configuration : la
commande (ce chemin) et ses arguments (les drapeaux ci-dessous, le cas
échéant).

### Depuis les sources

Compilez-le une fois, puis pointez le client sur le résultat :

```bash
cargo build --release --bin rts-mcp --manifest-path rust/src-tauri/Cargo.toml
claude mcp add renpy-studio -- "/chemin/vers/renpy-translation-studio/rust/src-tauri/target/release/rts-mcp"
```

`rts-mcp --help` liste les options. Un argument inconnu arrête le serveur
avec un message sur sa sortie d'erreur.

## Les drapeaux de ligne de commande

| Drapeau | Effet |
|---------|-------|
| `--project <chemin>` | Ne servir que ce dossier de jeu — celui qui contient `game/`. Sans lui, le client choisit parmi les projets configurés dans l'application. |
| `--allow-overwrite-validated` | Permettre à une soumission de remplacer une ligne que vous avez validée. Le remplacement atterrit en brouillon, jamais en validé. |
| `--allow-clear` | Autoriser la suppression de traductions en masse (`clear_translations`). |
| `--allow-edit-glossary` | Autoriser la modification du glossaire des personnages et du résumé d'univers. |

Rien n'est permis par défaut : sans drapeau, l'outil concerné refuse avec
un message qui le nomme.

## Ce qu'il peut atteindre

`list_projects` lit le registre des projets récents, celui-là même que
l'application écrit quand un humain configure un jeu (`projects.json`, dans
le dossier de configuration : voir [Installation](installation.md)), et
`use_project` en ouvre un. Tout ce qui est absent de cette liste est
refusé : **un jeu doit d'abord être configuré dans l'application.**

C'est là tout le modèle de permission sur les chemins : l'ensemble
atteignable est celui que **vous** avez construit en configurant des jeux,
pas celui qu'un modèle peut nommer.

`--project <chemin>` épingle un serveur sur un seul jeu, et le serveur
refuse alors tous les autres. Le jeu doit avoir été extrait au moins une
fois, pour que son dossier `.rts` existe.

## Ce qu'il sait faire

Dix-sept outils, qui reprennent les actions de l'écran de révision.

**Projets**

- `list_projects` — les jeux configurés dans l'application.
- `use_project` — en ouvrir un, par son chemin.

**Lecture**

- `list_files` — les fichiers à traduire avec leur avancement.
- `project_progress` — la part du projet entier qui est traduite.
- `list_units` — une page des lignes d'un fichier, avec les mêmes filtres
  et la même recherche que l'écran de révision.
- `get_unit_context` — les lignes autour d'une ligne, dans l'ordre du
  fichier.
- `list_characters` — le glossaire des personnages.
- `get_universe_summary` — le résumé d'univers.

**Traduction**

- `submit_translations` — renvoyer des traductions, un lot à la fois.
- `set_note` — laisser une note sur une ligne et la marquer à revoir.
- `set_needs_review` — poser ou retirer ce drapeau.
- `fill_from_memory` — remplir les lignes non traduites depuis la mémoire
  de traduction.

**Glossaire** (exige `--allow-edit-glossary`)

- `upsert_character` et `delete_character`.
- `detect_characters` — détecter les personnages du script du jeu.
- `set_universe_summary`.

**Effacement** (exige `--allow-clear`)

- `clear_translations` — retour à *Non traduits*, en masse.

Une soumission repasse par les **mêmes contrôles qualité** que la réponse
de n'importe quel fournisseur et arrive en **suggestion IA**, à relire
comme toute autre suggestion. Une ligne qui perd une `{balise}` ou une
`[interpolation]`, ou en ajoute une que la source n'avait pas, est
refusée. Les lignes déjà validées sont laissées tranquilles.

Les chemins sortent relatifs à la racine du projet, et les deux formes sont
acceptées en entrée. La base stocke des chemins absolus datant de
l'extraction, et les envoyer tels quels répéterait l'arborescence de votre
disque à chaque ligne de chaque page.

## Ce qu'il ne peut pas faire de lui-même

`--allow-overwrite-validated`, `--allow-clear` et `--allow-edit-glossary`
sont des **drapeaux de ligne de commande et rien d'autre** — jamais des
arguments d'outil. La raison est précise : l'assistant lit le texte du jeu,
écrit par un tiers, donc une réplique de dialogue réclamant l'un d'eux ne
doit pas être une demande que le modèle puisse s'accorder.

## Rafraîchissement en direct

Laissez l'écran de révision ouvert pendant que l'assistant travaille et les
lignes se remplissent sous vos yeux.

SQLite n'offre aucune notification entre processus : l'application écoute
donc sur la boucle locale tant que l'écran de révision est ouvert, et
publie son port et un jeton dans `<jeu>/.rts/live.json`. Le serveur y poste
les identifiants de blocs qu'il vient d'écrire.

Les lignes sont mises à jour **sur place**, jamais par un rechargement de
page : sous un filtre *Non traduits*, recharger les ferait disparaître au
lieu de les montrer se remplir. La ligne où se trouve votre curseur, ou
qui porte une modification en attente, n'est jamais écrasée. Les actions
en masse (`fill_from_memory`, `clear_translations`) rechargent la page, car
elles répondent par un compte et n'ont pas d'identifiants à donner.

La notification est un **bonus, jamais une dépendance**. Personne à
l'écoute, pas de fichier, connexion refusée : tout cela est ordinaire.
Fermez l'application et l'assistant continue de traduire.

Le jeton n'arrête qu'une seule chose : une page web, qui peut poster sur un
port local mais ne peut pas lire votre disque. Il n'arrête rien de ce qui
tourne sous votre propre compte.
