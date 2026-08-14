[← Documentation](README.md)

# Dépannage

*[English version](../en/troubleshooting.md)*

## Extraction

**Ren'Py refuse certains fichiers source.** Les lignes de chaque fichier
refusé sont absentes de l'extraction, et l'application les nomme. C'est
presque toujours un écart de version : Ren'Py 8 exige une valeur pour des
propriétés d'écran que Ren'Py 7 acceptait sans. Utilisez le moteur embarqué
dans le jeu plutôt que votre SDK — c'est déjà le comportement par défaut
quand ce système peut l'exécuter. Voir [Installation](installation.md).

**Aucun moteur trouvé.** Soit le jeu n'en embarque aucun qui puisse tourner
ici — un build `-win` ouvert depuis Linux ne contient que des runtimes
Windows — soit aucun SDK n'est configuré. Le message dit lequel.
Renseignez un chemin de SDK dans le dialogue des paramètres.

**Le nombre d'unités a changé après avoir changé d'extracteur.** Attendu,
et faible. Le `common.rpy` du SDK embarque des chaînes du launcher que le
jeu n'a pas.

## Contrôles qualité

Deux sortes, et la différence compte.

**Les avertissements** sont indicatifs et affichés sous le champ —
*Traduction 32% plus longue que le texte source*, par exemple. Rien n'est
bloqué ; les traductions longues débordent des cadres de texte Ren'Py assez
souvent pour mériter un coup d'œil.

**Les refus** rejettent la traduction. Le plus important :

> Une traduction ne peut pas introduire une `[interpolation]` absente du
> texte source.

Ren'Py évalue le contenu des crochets comme une **expression Python**. Une
traduction qui invente `[quelquechose]` livre donc du code exécutable à
tous les joueurs du jeu. Les entrées non fiables sont bien réelles ici — un
fichier bilingue renvoyé par un relecteur, une réponse de fournisseur — et
le dossier `tl/` que vous produisez part chez les joueurs. Ce contrôle
n'est pas assouplissable.

Filtrez sur *En erreur* pour retrouver les lignes refusées.

## Fournisseurs

**Un test de connexion échoue.** Activez la **Journalisation détaillée** en
bas de l'écran des fournisseurs ; chaque requête et chaque réponse est
alors journalisée en niveau DEBUG. C'est la première chose à regarder sur
n'importe quel problème de fournisseur.

**Ollama renvoie n'importe quoi sur les chaînes courtes.** Les petits
modèles quantifiés confondent des libellés courts et similaires — entrées
de menu, textes de boutons — au sein d'un même lot. Baissez **Unités par
requête**, ou prenez un modèle plus gros. C'est ce que dit l'avertissement
du panneau Ollama.

**Un modèle s'arrête trop tôt ou duplique des lignes.** Même famille de
problème, même réponse : des lots plus petits.

**Ollama est lent en petits lots sur un modèle cloud.** Le plafond de
contexte de 8192 jetons qui protège les modèles locaux ne s'applique pas
aux modèles cloud, reconnus à leur suffixe `-cloud` : rien n'est chargé sur
votre machine, il n'y protège donc de rien.

## Traductions

**Une mauvaise suggestion IA revient sans cesse.** Elle ne revient pas :
elle n'est jamais partie. Un travail de traduction n'envoie que les lignes
`non traduites`, une suggestion existante n'est donc ni retentée ni
écrasée. Corrigez-la, ou effacez-la pour que le prochain travail la
reprenne.

**Un travail semble sauter des lignes.** Même raison : tout ce qui porte
déjà du texte est sauté par construction.

**Une ligne validée a été remplacée.** Cela devrait être impossible depuis
un travail, un import, la mémoire ou le serveur MCP. Cela arrive quand
quelqu'un tape dans le champ, ce qui passe la ligne en brouillon. Le
serveur MCP ne peut le faire que s'il a été lancé avec
`--allow-overwrite-validated`, et le résultat atterrit alors en brouillon
aussi.

## Fichiers et stockage

**Où sont mes traductions ?** Dans `<jeu>/.rts/translations.db`. Déplacer
le dossier du jeu les emporte. Deux fichiers annexes,
`translations.db-wal` et `-shm`, lui appartiennent : copiez-les aussi si
vous copiez un projet à la main.

**L'application prévient qu'elle n'a pas pu passer en WAL.** La base est
sur un système de fichiers sans mémoire partagée, typiquement un partage
réseau. Tout fonctionne quand même ; deux processus atteignant le projet en
même temps peuvent se bloquer l'un l'autre.

**Rien n'a changé dans le jeu.** Enregistrer dans les `.rpy` est une étape
distincte de l'édition. Surveillez le compteur orange à côté de
**Enregistrer dans les .rpy**.

## Interface

**Le panneau des fichiers est trop étroit pour les noms longs.** Il est
fixe. Flet n'expose aucun contrôle de panneaux redimensionnables, et une
poignée faite main coûte un aller-retour Python/Flutter par frame — cela a
été essayé et cela rend mal. Les noms longs sont couverts par l'infobulle.

**L'icône de la fenêtre est le logo Flet en développement.** `flet run`
lance le client préconstruit de Flet, et Windows dessine l'icône de la
barre des tâches à partir de l'exécutable qu'il a lancé. Seul un build
packagé porte la vraie icône.
