[← Documentation](README.md)

# Serveur MCP

*[English version](../en/mcp-server.md)*

Un second point d'entrée sur le même cœur, pour qu'un assistant que vous
payez déjà fasse la traduction — sans clé API, sans GPU.

## Le mettre en place

Le serveur est lancé par le client, en stdio :

```bash
claude mcp add renpy-studio -- uv run --directory /chemin/vers/renpy-translation-studio python -m mcp_server
```

Il n'y a volontairement **aucun script console installé**. Sous Windows, un
`rts-mcp.exe` serait verrouillé tant qu'un client tient le serveur ouvert,
ce qui empêcherait `uv run` de réinstaller le projet et donc de lancer
l'application.

## Ce qu'il peut atteindre

`list_projects` lit le registre des projets récents, celui-là même que
l'application écrit quand un humain configure un jeu, et `use_project` en
ouvre un. Tout ce qui est absent de cette liste est refusé.

C'est là tout le modèle de permission sur les chemins : l'ensemble
atteignable est celui que **vous** avez construit en configurant des jeux,
pas celui qu'un modèle peut nommer. `--project <chemin>` épingle un serveur
sur un seul jeu.

## Ce qu'il sait faire

Dix-sept outils, qui reprennent les actions de l'écran de révision : lister
les fichiers, lister les unités avec les mêmes filtres et la même
recherche, demander le contexte autour d'une ligne, soumettre des
traductions, lire et écrire le glossaire des personnages et le résumé
d'univers, remplir depuis la mémoire de traduction, poser des notes et des
drapeaux de relecture, rendre compte de l'avancement.

Une soumission repasse par les **mêmes contrôles qualité** que la réponse
de n'importe quel fournisseur et arrive en **suggestion IA**, à relire
comme toute autre suggestion. Les lignes déjà validées sont laissées
tranquilles.

Les chemins sortent relatifs à la racine du projet, et les deux formes sont
acceptées en entrée. La base stocke des chemins absolus datant de
l'extraction, et les envoyer tels quels répéterait l'arborescence de votre
disque à chaque ligne de chaque page.

## Les deux choses qu'il ne peut pas faire

`--allow-overwrite-validated` permet à une soumission de remplacer une
ligne que vous avez validée, en la faisant atterrir en brouillon.
`--allow-clear` autorise la suppression de traductions en masse.

Les deux sont des **drapeaux de ligne de commande et rien d'autre** —
jamais des arguments d'outil. La raison est précise : l'assistant lit le
texte du jeu, écrit par un tiers, donc une réplique de dialogue réclamant
l'un ou l'autre ne doit pas être une demande que le modèle puisse
s'accorder.

## Rafraîchissement en direct

Laissez l'écran de révision ouvert pendant que l'assistant travaille et les
lignes se remplissent sous vos yeux.

SQLite n'offre aucune notification entre processus : l'application écoute
donc sur la boucle locale tant que l'écran de révision est ouvert, et
publie son port et un jeton dans `<jeu>/.rts/live.json`. Le serveur y poste
les identifiants de blocs qu'il vient d'écrire.

Les lignes sont mises à jour **sur place**, jamais par un rechargement de
page : sous un filtre *Non traduits*, recharger les ferait disparaître au
lieu de les montrer se remplir. La ligne où se trouve votre curseur est
toujours sautée.

La notification est un **bonus, jamais une dépendance**. Personne à
l'écoute, pas de fichier, connexion refusée : tout cela est ordinaire.
Fermez l'application et l'assistant continue de traduire.

Le jeton n'arrête qu'une seule chose : une page web, qui peut poster sur un
port local mais ne peut pas lire votre disque. Il n'arrête rien de ce qui
tourne sous votre propre compte.
