# Mémoire Documentaire — Script de démo (cabinet juridique)
*Réunion ≈ 26 avril 2026 — durée cible : 5 minutes*

---

## Avant de commencer

Ouvrir un terminal à la racine du dépôt. Lancer la démo en une commande :

```bash
bash scripts/demo.sh
```

Ou exécuter les trois commandes section par section pour commenter entre chaque.
Le système tourne entièrement en local ; aucune donnée ne quitte la machine pendant la démo.

Corpus utilisé : **32 documents personnels** (compromis de vente notarial, bulletins de paie,
relevés fiscaux, documents d'identité, factures, courriers) servant de banc d'essai.

---

## 0:00 – 0:30 — Accroche

> La plupart des outils de recherche documentaire IA répondent avec fluidité, mais pas avec
> redevabilité. Si deux documents se contredisent sur un fait — une adresse, une date, une
> clause — le système choisit silencieusement l'un ou construit un compromis plausible.
> Le lecteur ne sait pas qu'un conflit existe.
>
> Ce prototype répond différemment. Chaque fait exposé résout vers un document précis, une
> date, une source. Les contradictions sont conservées, pas écrasées. L'historique est préservé.
>
> Trois requêtes, trois questions qu'un cabinet se pose sur ses archives.

---

## 0:30 – 1:30 — Pilier 1 : Provenance

### Commande

```bash
python -m extraction query "Qui sont les parties au compromis de vente et quelle est la date de signature ?"
```

### Sortie attendue

```
Les parties au compromis de vente sont Monsieur Laurent Jacques Antoine UROZ et Madame
Julie PLAMONDON en tant que vendeurs, et Monsieur Sébastien Jean Christophe BOUTET et
Madame Mylène Myriam EL-KAIM, son épouse, en tant qu'acquéreurs. La date de signature
de l'acte authentique de vente est prévue pour le 22 août 2016. Le document mentionne
également une signature du contrat le 26 octobre 2012 par Sébastien Boutet.

### References

- [1] /store/bf5873e8-5935-4461-b852-cab3fd0c0794/content.md
- [2] /store/4c6ac394-4c65-4f3e-8da8-ea5eaf7be7d0/content.md
- [3] /store/ebd79513-eaae-4cba-a915-1989fb367f12/content.md
- [4] /store/87a57859-97cf-468b-b3fc-9b72fcaa78fc/content.md
- [6] /store/fa35762b-1c30-46a2-84c1-2e84d65190f9/content.md
- [7] /store/0d3f6088-4414-40c7-8605-65ce760bd968/content.md
- [8] /store/e41c577b-92fb-48eb-8323-d3354f3c38f6/content.md
- [9] /store/b35e7fcd-1185-4d80-bc3e-835da38253f9/content.md
- [10] /store/ce8cdd75-dbc4-4048-99bd-f5f94928a73b/content.md
- [11] /store/72d09919-1270-4304-8db2-ae1c993a566c/content.md
- [12] /store/3482b279-245e-4eb9-9f8d-23158b16f216/content.md
- [13] /store/7fbb5633-0d41-46c6-98f1-ad8b1934422b/content.md
- [16] /store/eec9507c-1d09-4bfa-b8e5-8792fdf9eaf3/content.md
- [17] /store/9d99a215-5bb6-443a-82a8-e4aa79cf10bc/content.md
- [18] /store/3aa2c3f8-411b-4bcf-bddd-571218002ce7/content.md
- [19] /store/fb392da3-ebc0-4a76-ab99-57f8e23fab23/content.md
- [20] /store/ecbef566-bbe8-482a-b8bf-34573d0559fb/content.md
- [21] /store/4faa7ed1-7727-49b7-83aa-98c123a72350/content.md
- [22] /store/93a12513-f2b1-49fc-88af-29363c86ec7c/content.md
- [23] /store/9bf50ed5-d18c-4fbf-a4a0-861f44b015a3/content.md
- [24] /store/a6d69bea-ae72-4ce5-9e3e-7fcb9c608164/content.md
- [25] /store/407a7fd8-e3ef-473c-b358-544e550f3514/content.md
- [26] /store/5e7f1e02-26b5-4860-a6f8-9982fce963cd/content.md
```

### Commentaire oral

> Le système a identifié les quatre parties et les deux dates dans le document notarial,
> en croisant plusieurs fragments du corpus. Chaque référence pointe vers un document
> source précis — vérifiable, auditable.
>
> **Ce que V0 ne fait pas encore :** le pointeur va au document, pas au passage exact.
> La prochaine étape (mi-mai 2026) : chaque affirmation sera résolue en
> `(document, passage, version d'ingestion, extracteur, horodatage)`, accessible via
> une API `/facts/{id}`. La chaîne de preuve devient interrogeable par un outil tiers.

---

## 1:30 – 2:30 — Pilier 2 : Cohérence

### Commande

```bash
python -m extraction query "Quelles adresses apparaissent pour Sébastien Boutet dans les documents ?"
```

### Sortie attendue

```
D'après les documents fournis, plusieurs adresses sont associées à Sébastien Boutet :

*   **Lotissement Le Val Des Cedres, Chemin de l'Affama 83440 Montauroux** : Cette
    adresse est mentionnée comme son domicile dans un contrat de travail daté du
    26 octobre 2012 [1]. Elle apparaît également comme son adresse au 1er janvier 2011
    dans une déclaration de revenus [3].
*   **1096 Chemin du Trastour, 06330 Roquefort Les Pins** : Cette adresse est indiquée
    comme son adresse de facturation le 13 juin 2017 [6]. Elle est également mentionnée
    dans une lettre du 1er juin 2017 [2] et du 15 mars 2017 [4].
*   **Rue Cherche Midi, 06250 Mougins** : Cette adresse est associée à Sébastien Boutet
    dans un document daté du 17 septembre 2002 [KG].
*   **LOTISSEMENT LE VAL DES CEUNE** : Cette adresse est mentionnée comme son domicile
    sur son passeport, délivré le 28 octobre 2015 [10].
*   **16 A Impasse des Maubert, Cagnes-sur-Mer** : Sébastien Jean Christophe Boutet
    réside à cette adresse avec Mylène Myriam El-Kaim, selon un document du 13 mai 2016 [KG].

### References

- [1] /store/ebd79513-eaae-4cba-a915-1989fb367f12/content.md
- [2] /store/eec9507c-1d09-4bfa-b8e5-8792fdf9eaf3/content.md
- [3] /store/5626d1dd-1587-4c9e-904b-5d0ebaa86995/content.md
- [4] /store/3aa2c3f8-411b-4bcf-bddd-571218002ce7/content.md
- [5] /store/b35e7fcd-1185-4d80-bc3e-835da38253f9/content.md
- [6] /store/9f116783-301d-4fb9-b13e-5fb51547c365/content.md
- [7] /store/e41c577b-92fb-48eb-8323-d3354f3c38f6/content.md
- [8] /store/7fbb5633-0d41-46c6-98f1-ad8b1934422b/content.md
- [9] /store/4faa7ed1-7727-49b7-83aa-98c123a72350/content.md
- [10] /store/f7e9707d-ed9b-4c5d-802e-85d0fb29a9f9/content.md
- [11] /store/a6d69bea-ae72-4ce5-9e3e-7fcb9c608164/content.md
- [12] /store/35e2926a-5cf0-432b-a05f-ab55111c37cd/content.md
- [13] /store/0d3f6088-4414-40c7-8605-65ce760bd968/content.md
- [16] /store/5e7f1e02-26b5-4860-a6f8-9982fce963cd/content.md
- [17] /store/bf5873e8-5935-4461-b852-cab3fd0c0794/content.md
- [22] /store/93a12513-f2b1-49fc-88af-29363c86ec7c/content.md
- [23] /store/9bf50ed5-d18c-4fbf-a4a0-861f44b015a3/content.md
- [24] /store/9d99a215-5bb6-443a-82a8-e4aa79cf10bc/content.md
- [28] /store/e2294430-c9fe-4972-852b-34f30d2a7b2a/content.md
- [30] /store/3482b279-245e-4eb9-9f8d-23158b16f216/content.md
```

### Commentaire oral

> Le graphe conserve cinq adresses différentes pour le même sujet, chacune sourcée dans
> un document distinct avec sa date. C'est exactement le matériau brut d'un conflit
> potentiel : même sujet, même prédicat (adresse), valeurs différentes. Le système les
> liste, mais ne dit pas encore qu'elles sont contradictoires.
>
> *(Note sur les marqueurs `[KG]` : deux adresses pointent vers le graphe de connaissances
> plutôt qu'un passage précis dans un document — c'est exactement ce que la prochaine
> étape résoudra : chaque affirmation résolue en document + localisation exacte.)*
>
> **Ce que V0 ne fait pas encore :** signaler explicitement le conflit, ni proposer une
> résolution. Début juin 2026 (Phase 7) : deux faits incompatibles sur le même
> `(sujet, prédicat)` déclencheront un objet `Conflit` listé par une API `/conflicts`.
> La résolution restera humaine — un fichier versionné, toute intervention tracée —
> mais le signal sera automatique.

---

## 2:30 – 3:30 — Pilier 3 : Temporalité

### Commande

```bash
python -m extraction query "Quelle est l'adresse la plus récente mentionnée dans les documents ?"
```

### Sortie attendue

```
L'adresse la plus récente mentionnée dans les documents est **55 Chemin Des Batistons,
06330 Roquefort Les Pins**, associée à Monsieur Boutet Sebastien et Mme Mylene El Kaim.
Cette information est datée du 26 mars 2026. [7]

### References

- [1] /store/4c6ac394-4c65-4f3e-8da8-ea5eaf7be7d0/content.md
- [2] /store/bf5873e8-5935-4461-b852-cab3fd0c0794/content.md
- [3] /store/eec9507c-1d09-4bfa-b8e5-8792fdf9eaf3/content.md
- [4] /store/3aa2c3f8-411b-4bcf-bddd-571218002ce7/content.md
- [5] /store/fb392da3-ebc0-4a76-ab99-57f8e23fab23/content.md
- [6] /store/5626d1dd-1587-4c9e-904b-5d0ebaa86995/content.md
- [7] /store/87a57859-97cf-468b-b3fc-9b72fcaa78fc/content.md
- [8] /store/ebd79513-eaae-4cba-a915-1989fb367f12/content.md
- [9] /store/ce8cdd75-dbc4-4048-99bd-f5f94928a73b/content.md
```

### Commentaire oral

> Le système a résolu la requête par date : chaque nœud du graphe porte une annotation
> temporelle (`[sourced: 2026-03-26]`) qui permet de classer les adresses
> chronologiquement et de renvoyer la plus récente avec sa source.
>
> **Ce que V0 ne fait pas encore :** requête point-in-time. On ne peut pas encore demander
> « quelle était l'adresse au 1er janvier 2015 ? ». Mi-juin 2026 (Phase 8) : chaque
> fait portera des champs `valid_from` / `valid_to` explicites. Une requête
> `/entities/{id}?as_of=2015-01-01` renverra l'état juridique à cette date. Les mises à
> jour s'ajoutent ; elles n'effacent pas l'historique.

---

## 3:30 – 4:30 — Feuille de route et souveraineté

| Échéance | Livrable |
|---|---|
| **Aujourd'hui (V0)** | Extraction multi-format, graphe de connaissances, réponses avec citations au niveau du document. 32 documents hétérogènes, couverture de récupération 92 %. |
| **Mi-mai 2026** | Modèle Fait / Assertion / Conflit. API `/facts/{id}` exposant la chaîne de preuve complète. |
| **Début juin 2026** | Conflits de première classe. Résolution humaine via fichiers versionnés dans Git — chaque intervention est tracée et réversible. |
| **Mi-juin 2026** | Requêtes temporelles point-in-time (`as_of`). Versionnement à la ré-ingestion sans perte d'historique. |
| **Mi-juillet 2026 (V1)** | API complète. Évaluation étendue (25–30 cas dont cas adversariaux : contradictions connues, doublons, mises à jour). |
| **Début août 2026** | Serveur MCP pour consommation par agents LLM tiers — intégration dans des outils métier existants. |

**Souveraineté des données**

- Documents, graphe de connaissances, index vectoriels et modèles : sur la machine du
  cabinet ou un serveur interne.
- Modèles sélectionnés par étape du pipeline : basculement possible vers des modèles
  ouverts sans connexion internet, ou vers un cloud souverain européen, selon le niveau
  de sensibilité du corpus.
- Formats ouverts, portables, exportables. Aucun verrouillage propriétaire. Réversibilité
  totale.
- Conformité RGPD par architecture : aucune donnée ne quitte le périmètre sans décision
  explicite de l'opérateur.

---

## 4:30 – 5:00 — Questions de découverte

> Trois questions pour évaluer si votre pratique peut bénéficier d'un pilote :
>
> 1. **Quels types d'actes ou de clauses méritent une traçabilité au niveau du fait dans
>    votre pratique courante ?**
>    Mandats, procurations, clauses suspensives, renouvellements, parties à un acte ?
>
> 2. **Comment gérez-vous aujourd'hui les contradictions entre documents ?**
>    Entre avenant et contrat initial, entre deux versions d'une même pièce, entre
>    une déclaration et un justificatif ?
>
> 3. **Quelles contraintes structurent votre choix d'outil ?**
>    Secret professionnel, RGPD, archivage probant, réversibilité, hébergement souverain ?

**Proposition :** un pilote sur un sous-corpus représentatif de votre pratique — 20 à 50
actes, avec des contradictions connues et des requêtes dont vous connaissez la réponse
exacte — pour mesurer la valeur réelle avant tout engagement.
