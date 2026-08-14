[← Ren'Py Translation Studio](../../README_FR.md)

# Ren'Py Translation Studio

*[English version](../en/README.md)*

Application de bureau pour traduire les jeux Ren'Py. Elle couvre tout le
trajet : extraire le texte d'un jeu, le réviser ligne par ligne, faire
rédiger le reste par un service de traduction automatique ou un LLM,
réécrire les fichiers `tl/`, et livrer un zip.

![L'écran de révision](../images/03-review-fr.png)

## Pour commencer

| Page | Contenu |
|---|---|
| [Installation](installation.md) | Faire tourner l'application, et ce qu'elle demande |
| [Configuration du projet](project-setup.md) | Désigner un jeu et en extraire le texte |
| [Écran de révision](review-screen.md) | L'écran où vous passerez votre temps |
| [Statuts de traduction](translation-statuses.md) | Ce que veulent dire les cinq statuts, et qui peut les changer |

## Traduire

| Page | Contenu |
|---|---|
| [Fournisseurs de traduction](translation-providers.md) | DeepL, Ollama, LibreTranslate, Claude, Mistral |
| [Serveur MCP](mcp-server.md) | Faire traduire par un assistant que vous payez déjà |
| [Contexte pour l'IA](context-for-the-ai.md) | Glossaire des personnages et résumé d'univers |
| [Fichiers bilingues](bilingual-files.md) | Allers-retours CSV, XLIFF, JSON, et mémoire de traduction |

## Terminer

| Page | Contenu |
|---|---|
| [Export](export.md) | Écrire les fichiers `.rpy` et fabriquer le zip |
| [Raccourcis clavier](keyboard-shortcuts.md) | Tous les raccourcis, et ce qui s'atteint sans souris |
| [Dépannage](troubleshooting.md) | Échecs d'extraction, erreurs de fournisseur, traductions suspectes |

## Ce que montrent les captures

Toutes les captures de ces pages ont été prises sur **The Question**, le
visual novel d'exemple livré avec le SDK Ren'Py, traduit en français.
C'est une vraie extraction d'un vrai jeu, pas une maquette.

## Licence et périmètre

L'application est publiée sous la licence libre
[CeCILL v2.1](../../LICENSE.md).
Elle n'est ni affiliée à Ren'Py, ni approuvée ou sponsorisée par Ren'Py ;
le nom désigne seulement le moteur dont elle lit et écrit les fichiers.
