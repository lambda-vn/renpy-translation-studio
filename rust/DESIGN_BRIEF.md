# Ren'Py Translation Studio : description pour la refonte de l'interface

## En une phrase

Une application de bureau qui sert à traduire un visual novel Ren'Py : elle extrait
tous les textes du jeu, les présente ligne par ligne pour la relecture, les fait
traduire par une machine si on le veut, puis réécrit les fichiers de traduction du
jeu et les emballe dans un zip à distribuer.

## Qui s'en sert

- **Des traducteurs amateurs ou semi-pros de visual novels**, souvent seuls, parfois
  en petite équipe. Un jeu compte de quelques centaines à plus de 40 000 lignes, et
  une traduction s'étale sur des semaines ou des mois : l'application est ouverte
  longtemps, tous les jours, et on y revient là où on s'était arrêté.
- Le travail réel est **de la relecture en masse** : lire une ligne source, lire ou
  corriger la proposition, valider, passer à la suivante, des centaines de fois par
  séance. L'écran de révision, c'est 90 % du temps passé dans l'application.
- Ces utilisateurs tapent beaucoup et aiment le clavier. **Tout doit se faire sans
  souris.**

## Plateforme et contraintes techniques

- Application de bureau **Windows, macOS et Linux** (Tauri : une fenêtre native
  qui affiche une page web). Interface en **Svelte 5**, aucune bibliothèque de
  composants imposée.
- Fenêtre redimensionnable ; viser confortable dès **1280 × 800**, utilisable vers
  1024 de large. Pas de version mobile.
- Interface en **anglais et en français** (le français est environ 20 % plus
  long : prévoir de la place dans les boutons et les libellés).
- Clair et sombre souhaités.
- Accessibilité : chaque statut doit avoir **une forme distincte et un libellé pour
  lecteur d'écran**, jamais la couleur seule. Focus clavier toujours visible.

## Le vocabulaire

- **Projet** : un jeu en cours de traduction vers une langue cible.
- **Fichier** : un fichier `.rpy` du jeu. Un projet en compte de quelques-uns à
  plusieurs centaines, avec parfois des chemins longs (`chapitre3/scenes/route_b.rpy`).
- **Ligne** (ou unité) : un texte à traduire. Elle a un texte source, souvent un
  **locuteur** (le personnage qui parle), une traduction, un statut, un drapeau et
  une note facultative. La longueur va d'un mot (`"..."`, `"Oui."`) à un paragraphe.
  Les textes contiennent des balises à conserver telles quelles : `{i}…{/i}`,
  `{color=#f00}`, et des variables entre crochets : `[player_name]`.

### Les cinq statuts (le cœur du modèle)

| Statut | Sens |
|---|---|
| Non traduit | Rien encore |
| Brouillon | Tapé à la main, pas validé |
| Importé | Venu d'un fichier externe ou de la mémoire, pas relu ici |
| Suggestion IA | Proposé par un fournisseur de traduction automatique ou un assistant |
| Validé | Un humain l'a lu et approuvé : plus rien d'automatique n'y touche |

À côté du statut, indépendants de lui : un **drapeau** « à revoir » et une **note**
libre (écrire une note lève le drapeau). Deux vues de filtre en plus des statuts :
*Signalées* (drapeau levé) et *En erreur* (refusées par un contrôle qualité).

## Le parcours

Trois étapes, affichées comme une **barre d'étapes** en haut :
**Configuration → Révision → Export**. On passe l'essentiel du temps dans la
deuxième. Les écrans secondaires (personnages, univers, fournisseurs, paramètres)
se rejoignent depuis la révision.

## Les écrans

### 1. Premier lancement (une seule fois)

Choisir la langue de l'interface. Indiquer un SDK Ren'Py est **facultatif** : la
plupart des jeux embarquent leur propre moteur, le SDK ne sert qu'en secours.

### 2. Configuration : liste des projets et nouveau projet

- **Liste des projets récents** : nom du jeu, chemin, langue cible, avancement
  (barre ou pourcentage). Un clic rouvre le projet **exactement où on l'avait
  laissé** (fichier, page, filtre, recherche). Une croix retire l'entrée de la liste
  sans rien supprimer sur le disque.
- **Nouveau projet** : dossier du jeu (sélecteur ou chemin collé), langue source,
  langue cible (liste déroulante), SDK facultatif qui n'apparaît que si le jeu n'a
  pas de moteur utilisable.
- Un **avis** à afficher avant l'extraction : lancer le moteur du jeu, c'est exécuter
  le code d'un tiers.
- **Extraire les textes** : peut durer de quelques secondes à plusieurs minutes.
  Une ré-extraction propose **trois modes** (garder, mettre à jour, réinitialiser)
  dans un dialogue. Après coup : le nombre de lignes trouvées, et la liste des
  fichiers que Ren'Py a refusés le cas échéant.

### 3. Révision (l'écran principal, à soigner en priorité)

**Panneau de fichiers à gauche**, largeur fixe :
- une barre de progression globale du projet en haut ;
- un élément par fichier, avec ses compteurs : validés / total, plus suggestions,
  importés et brouillons. Noms longs tronqués, infobulle pour le nom complet ;
- **menu contextuel** sur un fichier (clic droit ou touche Menu) : ouvrir, copier le
  chemin, montrer dans l'explorateur, traduire ce fichier, l'exporter en fichier
  bilingue, effacer ses traductions.

**Barre d'outils** au-dessus des lignes :
- filtres : statut (5 statuts + *Signalées* + *En erreur* + *Tous*), locuteur
  (liste des personnages), recherche plein texte sur la source et la traduction ;
- compteur du fichier courant (« 26 / 77 validées ») ;
- actions : **Personnages**, **Univers**, **Mémoire** (remplir depuis la mémoire de
  traduction), **Import / export** (fichiers bilingues CSV, XLIFF, JSON),
  **Effacer** (en masse, avec confirmation), **Traduction automatique** ;
- **Écrire dans les .rpy** (Ctrl+S) avec, à côté, un compteur bien visible :
  « 72 lignes non écrites dans les .rpy ».

**Les lignes**, 50 par page, avec pagination :
- glyphe de statut, locuteur, texte source, champ de traduction (multiligne, grandit
  avec le texte) ;
- cinq actions par ligne : traduire cette ligne seule, copier la source dans la
  traduction (Ctrl+D), effacer, drapeau (Ctrl+M), valider (Ctrl+Entrée) ;
- sous la traduction : la **note** (bandeau discret quand la ligne est signalée),
  les **erreurs bloquantes** (la validation est refusée, par exemple une variable
  `[…]` perdue) et les **avertissements** non bloquants (« traduction 32 % plus
  longue que la source ») ;
- une ligne peut être **mise à jour sous les yeux de l'utilisateur** par un autre
  processus (un assistant IA branché par MCP) : il faut que ce soit perceptible sans
  être agaçant, et jamais sur la ligne en cours d'édition.

**Job de traduction automatique** :
- un dialogue de lancement : fournisseur (DeepL, Ollama, LibreTranslate), portée
  (fichier courant ou projet entier) ;
- pendant le job, un **bandeau, pas une fenêtre modale** : la révision reste
  utilisable. Progression (faites / total / échecs), bouton annuler, journal court
  des événements. Un job peut durer des heures sur un gros jeu ;
- quitter la révision est refusé tant qu'un job tourne.

### 4. Personnages

Tableau éditable : variable Ren'Py du personnage, nom affiché, notes libres (genre,
registre, tutoiement, et la traduction du nom sous la forme `Nom -> Traduction`). Bouton **Détection automatique** qui trouve les
personnages dans les scripts. Ces informations partent dans le contexte envoyé aux
traducteurs automatiques.

### 5. Univers

Un grand champ de texte libre : résumé de l'histoire, ton, lexique propre au jeu.
Bouton **Générer avec l'IA**, qui demande une confirmation à chaque fois (on envoie
du texte du jeu à un service).

### 6. Fournisseurs de traduction

Trois fournisseurs, chacun dans une section repliable avec un **badge d'état**
(configuré / non configuré / connexion OK / erreur) : clé API (DeepL), URL et modèle
(Ollama), URL et clé facultative (LibreTranslate). Un bouton « Tester la
connexion » par fournisseur. Choix du fournisseur par défaut.

### 7. Paramètres (dialogue)

Langue de l'interface, journal détaillé (pour le diagnostic), taille de la mémoire
de traduction partagée entre projets.

### 8. Export

Nom du jeu (proposé, modifiable), nom du fichier zip qui en résulte, destination,
bouton **Exporter**. Un **avertissement** si la base contient des lignes pas encore
écrites dans les `.rpy` (l'export emballerait une version périmée).

### 9. Transversal

- **F1** ouvre la liste des raccourcis, sur n'importe quel écran.
- Dialogues de confirmation pour tout ce qui détruit du travail.
- **Toasts** pour les retours d'action brefs (« 51 lignes remplies depuis la
  mémoire »).
- Un en-tête discret : nom du jeu, langue source → cible.

## Raccourcis clavier (à faire apparaître dans l'interface)

| Touche | Action |
|---|---|
| F1 | Liste des raccourcis |
| Échap | Fermer le dialogue, sinon vider la recherche |
| Ctrl+F | Aller à la recherche |
| Ctrl+S | Écrire les .rpy |
| Ctrl+Entrée | Valider et passer à la ligne suivante |
| Ctrl+Maj+Entrée | Valider et appliquer à toutes les lignes de source identique |
| Ctrl+D | Copier la source dans la traduction |
| Ctrl+M | Signaler la ligne |
| Alt+↑ / Alt+↓ | Ligne précédente / suivante |
| Maj+Alt+↑ / ↓ | Fichier précédent / suivant |
| Alt+← / Alt+→ | Page précédente / suivante |

Les raccourcis fonctionnent même quand le curseur est dans un champ.

## Ce qui ne va pas aujourd'hui

L'interface actuelle est un échafaudage fonctionnel : des boutons gris par défaut,
une barre de liens en haut, des listes déroulantes brutes, une bordure de couleur à
gauche des lignes comme seul indicateur de statut, aucune hiérarchie visuelle. Elle
a été écrite pour vérifier que le moteur marche, pas pour être utilisée des heures.

## Ce qu'on attend du design

1. **L'écran de révision d'abord**, dans ses états réels : page pleine de lignes de
   longueurs variées, ligne en cours d'édition, ligne signalée avec note, ligne avec
   erreur bloquante, job en cours dans le bandeau, filtre qui ne renvoie rien.
2. Ensuite la liste des projets / nouveau projet, puis l'export, les personnages,
   l'univers, les fournisseurs et les paramètres.
3. Un petit système cohérent : couleurs et glyphes des cinq statuts, boutons,
   champs, dialogues, toasts, en clair et en sombre.

Priorités, dans l'ordre : **lisibilité du texte** (c'est un outil de lecture),
**densité** (voir beaucoup de lignes sans défiler), **rapidité au clavier**, puis
seulement l'esthétique. Ton visé : un outil de travail sobre et soigné, pas une
application grand public.
