# Suivi juridique — inZONE

État des lieux pour la validation par un professionnel du droit ivoirien.
Produit par une IA : ne constitue pas un avis juridique. Distingue ce qui
est vérifié de ce qui reste une hypothèse ou une information manquante.

Complète `docs/revue-juridique.md` (qui détaille les clauses de commission
et le barème interne) avec une vue d'ensemble de tous les documents
juridiques du site.

## Faits vérifiés

- Forme juridique d'Africand Consulting : **SARL** (confirmé par le client, 2026-10-10).
- Déclaration préalable auprès de l'ARTCI pour le traitement des données
  personnelles : **non effectuée** à ce jour (confirmé par le client,
  2026-10-10). Voir § Références juridiques ci-dessous pour la base légale.
- L'inscription publique (`/api/signup`) est réellement fonctionnelle, pas
  seulement une démo — tout visiteur peut créer un compte abonné sans
  intervention de l'équipe. Donnée pertinente pour la politique de
  confidentialité et les CGU (création de compte).
- Aucun outil de mesure d'audience ni cookie publicitaire n'est intégré au
  site à ce jour (vérifié par inspection du code, pas seulement déclaré).
- Le site n'est pas encore déployé sur un hébergeur de production
  identifié ; les clés CinetPay et Stripe ne sont pas configurées.

## Hypothèses retenues dans les documents

- Le contact juridique du site est l'adresse déjà publiée dans le code :
  `jeaneliengoran@africandconsulting.com`. À confirmer que c'est la bonne
  adresse pour les demandes RGPD/ARTCI, ou si une adresse dédiée doit être
  créée.
- Les CGU/CGV supposent que les abonnés sont majoritairement des
  professionnels (investisseurs, promoteurs). Si des particuliers
  s'abonnent à titre non professionnel, certaines clauses (non-
  remboursement, non-rétractation) doivent être revues avec un
  professionnel du droit de la consommation ivoirien.

## Informations manquantes (marquées `[À CONFIRMER PAR AFRICAND CONSULTING]` dans les pages)

| Information | Où elle apparaît |
|---|---|
| Adresse du siège social | Mentions légales, politique de confidentialité |
| Numéro RCCM | Mentions légales |
| Numéro de compte contribuable (NCC) | Mentions légales |
| Capital social | Mentions légales |
| Nom et qualité du directeur de publication | Mentions légales |
| Identité de l'hébergeur de production | Mentions légales, politique de confidentialité |
| Régime de TVA/taxes locales applicable | Conditions générales de vente |
| Durées de conservation précises (demandes de démo, comptes résiliés, factures) | Politique de confidentialité |
| Juridiction compétente en cas de litige | CGU, CGV |
| Délai de réponse aux réclamations, s'il doit être garanti | Réclamations |
| Conditions précises d'annulation d'une vérification déjà commandée | CGV |

## Références juridiques utilisées, avec leur source

- **Loi ivoirienne n° 2013-450 du 19 juin 2013** relative à la protection
  des données à caractère personnel — citée dans la politique de
  confidentialité existante du site (déjà présente avant cette session) et
  reprise dans les nouvelles pages. Vérifiée par recherche web le
  2026-10-10 : son existence et son objet sont confirmés par plusieurs
  sources de presse spécialisée (CIO Mag, Osiris, Abidjan.net), qui
  indiquent notamment que son article 5 soumet le traitement de données
  personnelles à une déclaration préalable auprès de l'autorité
  compétente, et que son article 46 désigne l'**ARTCI** (Autorité de
  Régulation des Télécommunications de Côte d'Ivoire) comme autorité de
  protection des données. Je n'ai pas eu accès au texte intégral officiel
  de la loi (Journal officiel) pour vérifier l'article exact numéro par
  numéro — **à confirmer auprès d'une source officielle avant publication**.
- Articles mentionnés par les sources consultées mais non vérifiés
  directement dans le texte officiel : article 5 (déclaration préalable),
  article 46 alinéa 1 (désignation de l'ARTCI), article 53 (délai de mise
  en conformité), décision ARTCI n° 2017-0354 du 26 octobre 2017
  (procédure de mise en conformité). À vérifier avant de les citer comme
  base d'une obligation contractuelle ferme.

## Questions nécessitant l'avis d'un professionnel du droit ivoirien

1. La déclaration préalable à l'ARTCI doit-elle être faite avant toute
   collecte réelle de données de prospects (formulaire de démo), ou
   seulement avant l'ouverture effective de comptes payants ?
2. La clause de non-remboursement des abonnements (6/12 mois payables
   d'avance) est-elle opposable à un client particulier, ou seulement à un
   client professionnel ?
3. Quelle est la juridiction compétente par défaut en cas de litige avec
   un client basé hors de Côte d'Ivoire ?
4. L'engagement de non-contournement (24 mois, pénalité égale à la
   commission qui aurait été due) est-il valable sous la seule forme d'une
   case cochée en ligne, ou faut-il une signature plus formelle ?
5. Régime fiscal (TVA, autres taxes) applicable aux prestations facturées
   par Africand Consulting pour les formules Veille/Veille Pro/Sur mesure
   et les vérifications sur site.

## Documents créés dans le cadre de cette session

| Document | Fichier | Statut |
|---|---|---|
| Mentions légales | `mentions-legales.html` | Rédigé, champs factuels à compléter |
| Politique de confidentialité | `politique-confidentialite.html` | Rédigée, remplace/complète la modale existante |
| Politique des cookies | `politique-cookies.html` | Rédigée à partir d'une inspection réelle du code |
| Conditions générales d'utilisation | `conditions-utilisation.html` | Rédigées |
| Conditions générales de vente | `conditions-vente.html` | Rédigées, clause de non-remboursement à faire valider |
| Réclamations | `reclamations.html` | Rédigée |
| Revue des clauses de commission et du barème interne | `docs/revue-juridique.md` | Déjà existante (session précédente) |

Ces documents sont rédigés avec soin à partir du fonctionnement réel du
site, mais leur production par une IA ne constitue pas une validation
juridique professionnelle. Aucun ne doit être considéré comme définitif
avant la relecture d'un avocat ivoirien, en particulier sur les points de
la section « Questions nécessitant l'avis d'un professionnel » ci-dessus.
