[← Documentation](README.md)

# Dépannage

*[English version](../en/troubleshooting.md)*

## Extraction

**Ren'Py refuse certains fichiers source.** Les lignes de chaque fichier
refusé sont absentes de l'extraction. Un dialogue intitulé *Certains
fichiers n'ont pas pu être lus* les nomme ; le jeu lui-même continue de
fonctionner, puisqu'il retombe sur la version compilée de chacun. C'est
presque toujours un écart de version : Ren'Py 8 exige une valeur pour des
propriétés d'écran que Ren'Py 7 acceptait sans. Utilisez le moteur
embarqué dans le jeu plutôt que votre SDK — c'est déjà le comportement par
défaut quand ce système peut l'exécuter. Voir [Installation](installation.md).

**« Ce jeu n'embarque aucun moteur exécutable ici, et aucun SDK Ren'Py
n'est sélectionné. »** Le jeu ne porte aucun moteur que ce système puisse
lancer, et aucun SDK n'est configuré. Renseignez un chemin de SDK dans le
dialogue des paramètres.

**« Ce jeu n'embarque qu'un moteur …, qui ne peut pas s'exécuter sur ce
système. »** Même situation, avec la cause en toutes lettres : un build
`-win` ouvert depuis Linux ne contient que des runtimes Windows, par
exemple. Sélectionnez un SDK Ren'Py pour l'extraire.

**« Échec de Ren'Py (code …) ».** Ren'Py a tourné et s'est arrêté sur une
erreur ; sa sortie suit le message.

**« Ren'Py n'a pas terminé dans le temps imparti et a été arrêté. »**
Relancez l'extraction : les fichiers déjà écrits sont conservés.

**« Impossible de lancer l'exécutable de Ren'Py. »** Le chemin du SDK, ou
le lanceur du jeu, n'est pas exécutable sur ce système. Vérifiez le chemin
dans le dialogue des paramètres.

**« Une extraction est déjà en cours. »** Attendez qu'elle se termine.

**« Seules les chaînes intégrées au moteur (common.rpy) ont été
extraites. »** Aucun dialogue n'est sorti. Vérifiez que le dossier choisi
est bien celui du projet du jeu — celui qui contient `game/`, pas `game/`
lui-même — et que `game/` contient des `.rpy` une fois les sources
archivées dépaquetées.

**« Les archives de ce jeu ne contiennent que des scripts compilés
(.rpyc) ».** Il n'y a aucune source à traduire. Un décompilateur est
nécessaire avant de pouvoir extraire ce projet.

**« Impossible d'archiver le dossier de traduction existant ».** Un autre
programme utilise `game/tl/`. Fermez le jeu, votre éditeur, et tout
gestionnaire de fichiers ou terminal ouvert dedans, puis réessayez.

**Le nombre d'unités a changé après avoir changé de moteur.** Attendu, et
faible. Le `common.rpy` du SDK embarque des chaînes du launcher que le jeu
n'a pas.

## Contrôles qualité

Deux sortes, et la différence compte.

**Les avertissements** sont indicatifs et affichés sous le champ —
*Traduction 32% plus longue que le texte source*, par exemple. Rien n'est
bloqué ; les traductions longues débordent des cadres de texte Ren'Py assez
souvent pour mériter un coup d'œil.

**Les refus** rejettent la traduction (*Validation refusée.*) : une
`{balise}` absente ou en trop, une `[variable]` absente, une balise HTML
inattendue, et le plus important :

> Interpolation absente du texte source, que Ren'Py exécuterait comme du
> code Python.

Ren'Py évalue le contenu des crochets comme une **expression Python**. Une
traduction qui invente `[quelquechose]` livre donc du code exécutable à
tous les joueurs du jeu. Les entrées non fiables sont bien réelles ici — un
fichier bilingue renvoyé par un relecteur, une réponse de fournisseur ou
d'un client MCP — et le dossier `tl/` que vous produisez part chez les
joueurs. Ce contrôle n'est pas assouplissable.

Filtrez sur *En erreur* pour retrouver les lignes refusées. Une
traduction vide est refusée aussi (*La traduction ne peut pas être
vide.*).

## Fournisseurs

**Un test de connexion échoue.** Activez la **Journalisation détaillée**
dans le dialogue des paramètres, réessayez, puis utilisez **Ouvrir le
journal** : chaque requête et chaque réponse y est journalisée en niveau
DEBUG, jamais avec la clé API. C'est la première chose à regarder sur
n'importe quel problème de fournisseur.

**« Configurez un fournisseur de traduction dans les paramètres » ou
« Configurez … dans les paramètres ».** Le fournisseur choisi n'a pas
encore de clé ou d'URL. Les messages *Clé API DeepL non configurée*,
*Modèle Ollama non configuré* et *URL LibreTranslate non configurée*
disent lequel.

**« Impossible d'enregistrer la clé API : aucun trousseau système n'est
disponible sur cette machine. »** Les clés sont gardées dans le trousseau
du système d'exploitation, jamais dans un fichier en clair. Sans service
de trousseau (sous Linux, un Secret Service comme GNOME Keyring ou
KWallet), la clé ne peut pas être enregistrée.

**« Connexion échouée — vérifiez votre clé API ».** La clé a été refusée.
Collez-la de nouveau ; le champ affiche *Clé enregistrée — saisissez pour
la remplacer* quand une clé est stockée, et **Retirer la clé** la
supprime.

**Un travail s'arrête sur une erreur du fournisseur.** Quand le
fournisseur répond par un refus que réessayer ne réglera pas (401, 403,
429, 456 : clé invalide, quota, limite de débit), le travail s'arrête au
lieu de rejouer chaque ligne, et les traductions déjà reçues sont
conservées. Corrigez la cause, puis relancez le travail : il n'envoie que
les lignes encore *Non traduits*.

**« Impossible de contacter le serveur Ollama ».** Vérifiez qu'Ollama est
démarré et que l'**URL du serveur** est la bonne.

**« Le modèle Ollama … n'est pas installé ».** Lancez la commande
`ollama pull` indiquée par le message, puis testez de nouveau la
connexion : la liste **Modèle** est remplie depuis le serveur.

**Ollama renvoie n'importe quoi sur les chaînes courtes.** Les petits
modèles quantifiés confondent des libellés courts et similaires — entrées
de menu, textes de boutons — au sein d'un même lot. Baissez **Unités par
requête**, ou prenez un modèle plus gros. C'est ce que dit l'avertissement
du panneau Ollama.

**Un modèle s'arrête trop tôt ou duplique des lignes.** Même famille de
problème, même réponse : des lots plus petits.

**Ollama est lent et le bandeau évoque le processeur.** Le modèle ne tient
pas dans la mémoire vidéo et tourne en partie sur le processeur. Réduisez
**Unités par requête** ou prenez un modèle plus petit.

**Ollama est lent en petits lots sur un modèle cloud.** Le plafond de
contexte de 8192 jetons qui protège les modèles locaux ne s'applique pas
aux modèles cloud, reconnus à leur suffixe `-cloud` : rien n'est chargé sur
votre machine, il n'y protège donc de rien.

**LibreTranslate est lent ou refuse des requêtes.** Les instances
publiques ont des limites de débit imprévisibles ; l'auto-hébergement est
recommandé. Le panneau prévient aussi quand l'URL est en `http://` vers un
hôte non local, la clé API circulant alors en clair.

## Traductions

**Une mauvaise suggestion IA revient sans cesse.** Elle ne revient pas :
elle n'est jamais partie. Un travail de traduction n'envoie que les lignes
*Non traduits*, une suggestion existante n'est donc ni retentée ni
écrasée. Corrigez-la, ou effacez-la pour que le prochain travail la
reprenne. Les brouillons sont la seule exception : quand il en existe,
l'application demande s'il faut les retraduire (*Avec les brouillons*) ou
non (*Sans les brouillons*).

**Un travail semble sauter des lignes.** Même raison : tout ce qui porte
déjà du texte est sauté par construction. Le bandeau signale aussi les
messages sans texte à traduire, copiés tels quels, et les messages
répétés, qui reprennent la traduction de leur première occurrence.

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
vous copiez un projet à la main. Les paramètres, la liste des projets
récents et le journal se trouvent dans le dossier de configuration décrit
dans [Installation](installation.md).

**Le journal dit qu'il n'a pas pu passer en WAL.** La base est sur un
système de fichiers sans mémoire partagée, typiquement un partage réseau.
Tout fonctionne quand même ; deux processus atteignant le projet en même
temps (l'application et le serveur MCP, par exemple) peuvent se bloquer
l'un l'autre.

**Rien n'a changé dans le jeu.** Enregistrer dans les `.rpy` est une étape
distincte de l'édition. Surveillez le compteur à côté de **Enregistrer dans
.rpy** : *N lignes non écrites dans les .rpy*.

**L'export annonce des traductions manquantes.** L'écran d'export prévient
quand des traductions n'ont pas été écrites dans les fichiers, ou quand les
fichiers `tl/` ont été modifiés en dehors de l'application depuis le
dernier enregistrement — ces retouches seraient écrasées au prochain
enregistrement. Enregistrez d'abord dans les `.rpy`. *Aucun dossier de
traduction trouvé. Lancez d'abord l'extraction.* signifie que le jeu n'a
jamais été extrait pour cette langue.
