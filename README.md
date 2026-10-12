# SOKUHŌ 速報 — robot d'actus anime, manga & manhua pour Instagram

*速報 (sokuhō) veut dire « flash info » en japonais.*

Le robot tourne gratuitement sur GitHub toutes les 20 minutes et fait tout seul :

| Quoi | Quand | Détail |
|---|---|---|
| **Post actu** | dès qu'une actu sort | vrai visuel officiel en plein cadre, gros titre, nom de l'œuvre sur bandeau jaune, légende avec question pour faire réagir |
| **Story** | juste après chaque post | version 9:16 avec l'étiquette « NOUVEAU POST » |
| **Carrousel récap** | dimanche à 18 h | couverture en mosaïque des visuels de la semaine + jusqu'à 9 actus |
| **Reel récap** | dimanche à 18 h | diaporama vertical d'environ 25 s des actus de la semaine, sans musique |

Il lit les flux RSS de sites d'actu francophones (Adala News, Journal du Japon, modifiables), écarte les critiques, les jeux vidéo et les doublons, et ne publie que les actus qui ont un vrai visuel.

**Coût : 0 €.**
- GitHub Actions est gratuit et illimité pour les dépôts publics avec les machines standard ([doc GitHub, consultée le 10/10/2026](https://docs.github.com/en/billing/concepts/product-billing/github-actions)).
- GitHub Pages, qui sert les images et vidéos à Instagram, est gratuit pour les dépôts publics : 1 Go maximum par site et une limite souple de 100 Go de bande passante par mois ([doc GitHub, consultée le 10/10/2026](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)). Le robot ne garde que 9 jours de médias, soit environ 200 Mo au maximum.
- L'API Instagram de Meta est gratuite.

Les secrets (jetons) restent invisibles, même dans un dépôt public.

---

## Mise en route

### 1. Le compte Instagram (toi)
- Crée le compte. Nom conseillé : **@sokuho.fr** (s'il est pris : `sokuho.news`, `sokuho_fr`). Si tu changes de nom, modifie `handle` dans `config.json`.
- Photo de profil : `assets/brand/photo-de-profil.jpg`.
- Bio proposée : `速報 L'actu anime, manga & manhua en direct 🔴 | Flash dès l'annonce · Récap chaque dimanche`
- Passe en **compte professionnel** (Paramètres → Type de compte → Créateur ou Entreprise). C'est obligatoire pour l'API.

### 2. Le dépôt GitHub
- Crée un dépôt **public** vide nommé `sokuho`. Claude y envoie le code, ou bien glisse ce dossier dans « Add file → Upload files ».
- **Settings → Pages → Build and deployment → Source : GitHub Actions.** Cela sert à mettre les images en ligne.

### 3. L'appli Meta et le jeton (toi, ~10 min)
1. Va sur developers.facebook.com, puis **Créer une app**.
2. Choisis le cas d'usage de gestion du contenu Instagram (« API Instagram », connexion avec Instagram).
3. Dans **Instagram → Configuration de l'API avec connexion Instagram**, ajoute ton compte et clique sur **Générer un jeton**. Accepte les autorisations, dont `instagram_business_content_publish`.
4. Copie le jeton. Il est valable **60 jours** et se prolonge automatiquement (étape 6).

Pour publier sur ton propre compte, l'appli peut rester en mode développement, sans validation par Meta.

### 4. Les secrets GitHub
**Settings → Secrets and variables → Actions → New repository secret**
- `IG_ACCESS_TOKEN` : le jeton (obligatoire)
- `GH_PAT` : conseillé, voir l'étape 6
- `IG_USER_ID` : facultatif

### 5. Premier test
Onglet **Actions** → « Publier les actus » → **Run workflow** → coche *Test à blanc*.
Les visuels sont fabriqués et mis en ligne sur `https://<ton-pseudo-github>.github.io/sokuho/`, mais rien ne part sur Instagram. Vérifie-les, puis relance sans cocher.
Au tout premier passage, le robot ignore l'historique et ne publie que l'actu la plus récente.
Pour voir tout de suite le récap : coche *Fabriquer le récap de la semaine maintenant*. Il faut au moins une actu déjà publiée.

### 6. Prolongation automatique du jeton
Le workflow « Prolonger le jeton Instagram » tourne chaque lundi et prolonge le jeton de 60 jours. Pour qu'il puisse réenregistrer le nouveau jeton, crée un jeton GitHub : Settings → Developer settings → **Fine-grained tokens**, accès au seul dépôt `sokuho`, permission **Secrets : Read and write**. Enregistre-le dans le secret `GH_PAT`.

---

## Réglages (`config.json`)

| Réglage | Rôle | Défaut |
|---|---|---|
| `use_official_visuals` | utiliser le visuel officiel de l'article | `true` |
| `require_visual` | ne publier que les actus avec un vrai visuel | `true` |
| `stories` | une story après chaque post | `true` |
| `reel_per_post` | un reel de 6 s en plus de chaque post | `false` |
| `weekly_recap` | jour (7 = dimanche), heure, reel oui/non | dimanche 18 h, reel oui |
| `max_posts_per_run` / `max_posts_per_day` | posts par passage / sur 24 h (hors stories) | 2 / 20 |
| `max_age_hours` | ignorer les actus plus vieilles | 12 |
| `quiet_hours` | heures sans publication (heure de Paris) | 1 h – 7 h |
| `media_keep_days` | durée de conservation des images en ligne | 9 jours |
| `sources` | flux RSS suivis, avec filtres | Adala News, Journal du Japon |

Limites Meta ([doc, consultée le 10/10/2026](https://developers.facebook.com/docs/instagram-platform/content-publishing)) : 100 publications via l'API par 24 h glissantes, un carrousel comptant pour une seule. Avec les réglages par défaut, le robot reste nettement en dessous. Formats vérifiés dans la [référence Meta](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media) : image de fil entre 4:5 et 1,91:1, story et reel en 9:16, reel en MP4 H.264 avec piste audio AAC. La piste audio est muette : pas de musique.

---

## Ce que tu peux ajouter à la main pour grandir plus vite
Les reels montés avec des extraits de trailers, les montages de personnages, les réponses aux commentaires et les sondages en story restent du travail manuel. Tu peux redessiner les gabarits dans **Claude Design**, et **Claude Code** reportera le nouveau style dans `bot/render.py`.

## Visuels officiels et droits
Les visuels promo restent la propriété des studios et éditeurs. Le robot crédite la source et les ayants droit sur l'image et dans la légende. Il n'utilise que l'image de partage de l'article (affiche, key visual), jamais de pages de scans. Si un ayant droit demande un retrait, retire le post.

## Essayer en local (facultatif)
```bash
pip install -r requirements.txt        # ffmpeg est aussi nécessaire pour les reels
python tests/test_logique.py            # test complet sans réseau
python tests/test_render_with_visual.py --reel   # aperçus dans preview/
```

## Organisation
```
bot/feeds.py      lecture et filtrage des flux RSS
bot/editorial.py  catégorie, titre réécrit, légendes, questions, hashtags
bot/render.py     post 4:5, story 9:16, couverture de récap, reel vidéo
bot/instagram.py  API Instagram : image, story, carrousel, reel, quota, jeton
bot/__main__.py   commandes prepare / publish / recap-now / preview / check / refresh-token
data/state.json   mémoire du robot (actus vues, file d'attente, publications)
media/            images et vidéos des 9 derniers jours (branche « media », servie par GitHub Pages)
```

Polices : Anton, Inter et Noto Sans JP, sous licence SIL Open Font License (`assets/fonts/OFL-*.txt`).

---

## Mise à jour du 12/10/2026

**Ce que fait le robot aujourd'hui**

| Quoi | Quand | Détail |
|---|---|---|
| Post actu | dès qu'une actu sort, jusqu'à 30 par jour | image entière sur fond flouté, titre, description détaillée sans IA (date, studio, plateforme, éditeur…), 5 hashtags maximum |
| Story | après chaque post | image entière, 9:16 |
| Reel motion design | toutes les 2 actus | 12 s, 3 modèles (impact, kinetic, breaking), carte de fin animée |
| Récap | dimanche 18 h | carrousel + reel |

Sources : Adala News et Crunchyroll News FR. Journal du Japon a été retiré (il donnait « Œuvre : Mexique »).

**Reels avec le vrai opening : page à ouvrir sur le téléphone** → https://kumacab.github.io/sokuho/reels/
1. Télécharger la vidéo.
2. Dans Instagram, « Ajouter un son » et chercher le nom indiqué (bouton Copier).
3. Coller la légende (bouton Copier) et publier.

Si ce n'est pas fait au bout de 3 h (`reels.manual_timeout_hours`), le robot le publie lui-même avec un de ses 12 jingles originaux (`assets/music/<ambiance>/`, composés par `tools/make_jingles.py`, donc sans droits à payer). Avant ça, il regarde les 40 derniers reels du compte : si la première ligne de la légende y est déjà, il ne publie pas en double. Pour tout passer en automatique : `"mode": "auto"`.

**Contrôle qualité :** chaque texte des reels est vérifié avant le montage. S'il touche le bord de son calque (texte coupé), le reel est abandonné et l'actu part en post classique.

**À faire de ton côté :** le secret `GH_PAT` (étape 6) avant début décembre, sinon le jeton Instagram expire vers le 9 décembre.

### 30 posts par jour (mise à jour du 12/10, soir)
`posts_per_day` : 30, répartis régulièrement de 7 h à 1 h (environ un toutes les 36 min). Les vraies actus passent toujours en premier (Adala News, Crunchyroll News, Animotaku). Quand elles ne suffisent pas, le robot complète avec, dans l'ordre :
1. **Épisode sorti** : les nouveaux épisodes des séries de la saison, juste après leur diffusion au Japon (studio, nombre d'épisodes, plateforme) ;
2. **Anniversaire** : « Chainsaw Man fête ses 4 ans », pour les œuvres populaires sorties un jour comme aujourd'hui.
Ces deux formats viennent de l'API publique et gratuite d'AniList (`bot/anilist.py`, réglages dans `fillers`).
