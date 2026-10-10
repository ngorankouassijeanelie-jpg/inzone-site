# Revue juridique — inZONE

Document préparé pour transmission à un avocat (droit ivoirien : foncier,
droit de la consommation, protection des données). Rassemble tous les
textes engageants et les règles de rémunération en vigueur dans le code
au 2026-10-10, avec leur contexte d'usage exact. Aucun avis juridique
n'est donné ici — c'est un état des lieux factuel du système pour
accélérer la relecture.

## 1. Modèle économique en une phrase

Accès visiteur limité au catalogue et aux fiches d'exemple ; l'abonnement
Veille / Veille Pro / Sur mesure conditionne l'accès complet et la mise
en relation avec le propriétaire (gratuite pour l'abonné, soumise à un
engagement de non-contournement) ; la vérification sur site est incluse
selon la formule ou facturée en supplément.

## 2. Engagement de non-contournement

**Où il s'affiche :** case à cocher dans l'espace client (« Mon compte »),
avant que le bouton « Être mis en relation avec le propriétaire » ne soit
actif sur une fiche terrain. Stocké côté serveur (`ncc_accepted_at`),
horodaté, non modifiable par le client une fois accepté.

**Texte actuel** (`content-legal.js`) :

> En demandant une mise en relation avec le propriétaire par
> l'intermédiaire d'inZONE, vous vous engagez à ne pas contourner inZONE
> pour finaliser une transaction sur ce terrain, directement ou par un
> tiers, pendant 24 mois à compter de la date de cette mise en relation.
> Cet engagement reste valable même si votre abonnement prend fin avant
> l'échéance des 24 mois. Tout contournement constaté peut donner lieu au
> versement à inZONE de la commission qui aurait été due.

**Mécanique technique** (`backend/app.py`, `demander_mise_en_relation`) :
- Bloqué si l'abonnement n'est pas actif, ou si l'engagement n'a pas été
  accepté au préalable.
- La date d'expiration (`ncc_expire_at`) est calculée à `+24 mois` depuis
  la date de la mise en relation, stockée sur chaque mise en relation.
- Rien dans le code n'applique de pénalité automatiquement : la clause
  prévoit un versement « peut donner lieu à », mais son exécution reste
  manuelle (aucune détection automatisée d'un contournement).

**Questions pour l'avocat :**
- Durée de 24 mois : usuelle/opposable en droit ivoirien pour ce type
  d'engagement unilatéral (sans contrepartie signée des deux côtés — le
  client coche une case, il n'y a pas de contrat contresigné) ?
- La clause pénale (« versement de la commission qui aurait été due »)
  est-elle valable sans montant déterminé à l'avance ?
- Un simple engagement par case à cocher a-t-il la même force qu'une
  signature manuscrite/électronique qualifiée en cas de litige ?

## 3. Conditions d'abonnement

**Où il s'affiche :** actuellement présent dans `content-legal.js`
(`CONDITIONS_ABONNEMENT`) mais **pas encore affiché dans l'interface** —
à vérifier s'il doit apparaître avant la souscription (page « Mon
abonnement »).

**Texte actuel :**

> L'abonnement est souscrit pour une durée minimale de 6 ou 12 mois,
> payable d'avance et non remboursable, sauf disposition contraire
> indiquée au moment de la souscription. Il donne accès au contenu et
> aux services décrits dans la formule choisie pour sa durée. Il n'est
> pas reconduit automatiquement : à l'échéance, l'abonné repasse en
> accès visiteur et peut souscrire un nouvel abonnement à tout moment,
> sans perdre l'historique de son compte. Le tarif fondateur (1 800 € la
> première année en formule Veille 12 mois) est réservé aux dix premiers
> abonnés et ne s'applique qu'une fois.

**Questions pour l'avocat :**
- Non-remboursable pour un abonnement payé d'avance : conforme au droit
  de la consommation ivoirien si le client est un particulier (vs
  professionnel/investisseur) ? Un délai de rétractation est-il requis ?
- Le texte n'est pas encore affiché avant paiement — à intégrer dans le
  parcours de souscription si l'avocat le juge nécessaire.

## 4. Tarifs en vigueur (`backend/app.py`, constantes `PLANS`)

| Formule | Durée | Prix | Vérifications incluses |
|---|---|---|---|
| Veille | 6 mois | 1 400 € HT | 0 |
| Veille | 12 mois | 2 400 € HT (1 800 € tarif fondateur, 10 premiers) | 0 |
| Veille Pro | 6 mois | 3 100 € HT | 1 |
| Veille Pro | 12 mois | 5 400 € HT | 2 |
| Sur mesure | — | à partir de 10 000 € HT/an, sur devis | — |

Vérification hors formule ou au-delà de l'incluse : 2 000 € HT
(`PRIX_VERIF_SUP`). Conversion FCFA au taux fixe 1 € = 655,957 FCFA
(parité EUR/XOF réglementaire, non un taux de marché).

## 5. Commissions terrain (propriétaire/mandataire)

**Où c'est fixé :** par terrain, dans l'admin (« accord de commission »),
taux borné entre 1 % et 3 %, payeur déclaré comme « Propriétaire » ou
« Mandataire » uniquement. Une mise en relation est **techniquement
bloquée** tant que cet accord n'est pas signé pour le terrain concerné.

**Question pour l'avocat :** le taux (1-3 %) et les deux statuts de
payeur possibles sont-ils conformes aux usages/encadrements de la
courtage immobilier/foncier en Côte d'Ivoire ?

## 6. Barème interne — agents de terrain et apporteurs d'affaires

Ces montants ne sont **jamais affichés aux clients** ; ils régissent les
reversements internes aux agents et apporteurs, modifiables par l'admin
(page « Offres et tarifs »).

| Clé | Valeur actuelle | Déclenchement |
|---|---|---|
| `agent_terrain_signale` | 20 000 FCFA | Agent signale un nouveau terrain |
| `agent_visite_constat` | 40 000 FCFA | Agent réalise une visite de constat |
| `agent_mise_a_jour` | 5 000 FCFA | Agent met à jour une fiche |
| `agent_prime_vente_pct` | 5 % | Prime sur commission encaissée à la vente |
| `apporteur_terrain_pct` | 15 % | Apporteur ayant apporté le terrain, sur commission encaissée |
| `apporteur_client_commission_pct` | 10 % | Apporteur ayant apporté le client, sur commission encaissée |
| `apporteur_client_premier_pct` | 12 % | **Défini mais non appliqué dans le calcul actuel** — voir ci-dessous |

**⚠️ Écart constaté dans le code (pas une question juridique, mais à
signaler) :** le taux « premier abonnement » (12 %) existe dans la
configuration et dans le libellé affiché à l'admin, mais la fonction qui
calcule la commission d'un apporteur de client (`commission_apporteur`)
n'utilise que le taux fixe de 10 %, quel que soit le rang de
l'abonnement. Le bonus « premier abonnement » n'est donc jamais
appliqué en pratique. À corriger côté développement si la règle doit
réellement s'appliquer — mentionné ici pour que l'avocat sache que la
règle écrite (barème) et la règle appliquée (code) divergent sur ce
point.

Chaque apport (terrain ou client) exige une **« convention signée »**
avant tout versement — sans cette signature enregistrée, le calcul
renvoie explicitement `0` avec la raison « convention non signée ».

**Questions pour l'avocat :**
- Ces barèmes (reversements à des agents/apporteurs indépendants) :
  relèvent-ils d'un contrat de mandat, de commission, ou d'un statut
  d'auto-entrepreneur/indépendant à formaliser par écrit avant tout
  versement réel (au-delà du flag applicatif « convention signée ») ?
- Faut-il un contrat-type signé (pas seulement une case cochée en base
  de données) pour que ces reversements soient juridiquement opposables ?

## 7. Données personnelles collectées

Pour mémoire (pas de texte de politique de confidentialité repéré dans
le code à ce jour) : email, mot de passe (haché, salé), nom, société,
pays, critères de recherche, préférences d'alertes, photo de profil,
documents déposés (PDF, images), et pour les apporteurs/agents : nom,
secteur, contact. Aucune mention de durée de conservation ni de base
légale de traitement trouvée dans le code ou les pages publiques.

**Question pour l'avocat :** une politique de confidentialité /
mentions RGPD-like (loi ivoirienne sur la protection des données
personnelles, régime de la ARTCI) est-elle requise avant mise en
production réelle, vu la collecte de données d'identification et de
documents ?

---
*Document généré à partir du code source le 2026-10-10. À régénérer si
les textes (`content-legal.js`) ou les barèmes (`app.py`) changent avant
la relecture par l'avocat.*
