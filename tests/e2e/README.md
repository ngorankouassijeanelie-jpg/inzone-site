# Tests de bout en bout (Playwright)

Parcours client et admin exécutés dans un vrai navigateur contre le vrai
backend FastAPI, sur une base SQLite jetable (effacée à chaque run).
Formalise les vérifications faites manuellement pendant le développement
(fail-closed du login, parcours d'abonnement, mise en relation).

## Lancer les tests

```bash
cd tests/e2e
npm install
npx playwright install chromium   # une fois, pas nécessaire dans ce sandbox
npx playwright test
```

Les serveurs backend (port 8001) et frontend statique (port 8080) sont
démarrés et arrêtés automatiquement par Playwright (`webServer` dans
`playwright.config.js`). Aucune installation manuelle requise au-delà de
`npm install`.

## Ce qui est couvert

- `login.spec.js` — le login admin et client échoue fermé (pas d'accès
  au tableau de bord) sur mot de passe incorrect et sur API injoignable ;
  un login valide fonctionne ; appeler `enter()` deux fois ne duplique
  pas les écouteurs d'événements ni les requêtes réseau.
- `subscription.spec.js` — un client s'abonne à Veille Pro, l'admin
  marque la facture payée, l'abonnement s'active et le contenu Veille se
  déverrouille, puis une demande de mise en relation aboutit.

## CI

`.github/workflows/tests.yml` lance cette suite (et les tests backend)
sur chaque push et pull request.
