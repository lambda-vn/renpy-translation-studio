[← Documentation](README.md)

# Contexte pour l'IA

*[English version](../en/context-for-the-ai.md)*

Deux écrans donnent aux fournisseurs LLM ce que le texte seul ne peut pas
leur dire. Tous deux s'atteignent depuis les entrées **Personnages** et **Univers** de
l'en-tête, et tous deux valent dix minutes avant de lancer une longue traduction.

## Glossaire des personnages

![Le glossaire des personnages](../images/05-characters-fr.png)

**Détection automatique** parcourt les sources `.rpy` du jeu à la recherche
des définitions `Character()` et remplit la liste ; les nouvelles entrées
portent la mention *Trouvé par la détection automatique — à compléter* tant
que vous ne quittez pas l'écran. C'est une détection heuristique : relisez ce
qu'elle a trouvé. La relancer réécrit les noms affichés avec ce que dit la
source, mais laisse vos notes intactes. **Ajouter manuellement** crée une
entrée à la main, et **Tout supprimer** efface tous les personnages après
confirmation : la détection retrouve les personnages, jamais les notes, qui
sont perdues définitivement.

Chaque entrée a une variable (`s`), un nom affiché (`Sylvie`) et une note
libre, enregistrée dès que vous quittez le champ. Ce sont les notes qui font le vrai travail :

```
Sylvie -> Sylvie (ne pas traduire)
Me -> Moi. Narrateur à la première personne, jamais nommé.
```

Elles servent de trois façons :

- Elles disent au modèle **qui parle**, pour que la ligne tombe avec le bon
  genre et le bon niveau de politesse.
- Elles gardent un nom **traduit de la même façon partout**. Avec DeepL,
  les notes écrites `Nom -> Traduction` (une par ligne) deviennent un
  véritable glossaire côté serveur.
- Elles portent **ce que le texte ne dit jamais** : registre, relations,
  tournures propres au personnage.

## Résumé d'univers

![Le résumé d'univers](../images/06-universe-fr.png)

Texte libre, envoyé au LLM avant chaque lot. Il s'enregistre tout seul pendant que vous écrivez. Trois choses y ont leur place :

- **Le ton et le registre.** Un jeu grave et une comédie ne se traduisent
  pas pareil, et un lot de dix lignes sans lien ne donne au modèle aucun
  moyen de deviner lequel des deux il a sous les yeux.
- **Quels noms propres restent tels quels** et lesquels se traduisent.
- **Le vocabulaire propre au jeu** — lieux, objets, factions — qu'aucun
  modèle ne peut deviner.

**Générer avec l'IA…** envoie un extrait des dialogues du jeu (jusqu'à 200
lignes) au fournisseur LLM configuré et en tire un premier jet. Le texte
remplace le champ ; le texte généré n'est pas enregistré tant que vous n'avez
pas cliqué sur **Enregistrer**. Le bouton reste désactivé tant qu'aucun
fournisseur LLM n'est configuré (Ollama est le seul), la traduction
automatique ne sachant pas le faire, et il faut qu'un texte ait déjà été
extrait.

> La génération envoie du texte du jeu au fournisseur que vous avez
> configuré, et l'application vous demande de le confirmer à chaque fois.
> Avec un modèle Ollama local, le texte reste sur votre machine ; avec un
> modèle `-cloud`, non.

### À propos d'un glossaire de termes

Il n'existe volontairement pas de glossaire de termes distinct, hors
personnages : aucun besoin mesuré ne l'a justifié jusqu'ici. Si vous voulez
faire respecter une terminologie récurrente, écrivez-la dans le résumé
d'univers — il part déjà dans le prompt système du fournisseur LLM (Ollama).
