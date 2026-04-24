# Mémoire Documentaire
*Fiabilité au niveau du fait — preuve, cohérence, temporalité*

---

## Le problème

Les outils de recherche documentaire assistés par IA (RAG générique, assistants conversationnels grand public) sont optimisés pour la **fluidité** de la réponse, non pour sa **redevabilité**. Trois défaillances récurrentes, disqualifiantes dans un contexte juridique :

- **Synthèse implicite des contradictions** — face à deux documents incompatibles, le système choisit silencieusement l'un ou construit un compromis plausible. Le lecteur ignore qu'un conflit existe.
- **Effondrement temporel** — une clause modifiée, un mandat renouvelé, un état historié sont aplatis en une vue unique ; la chronologie se perd.
- **Provenance faible** — les citations pointent vers un document, rarement vers la phrase exacte qui fonde la réponse.

---

## Trois questions qu'un cabinet se pose sur ses archives

| Question | Outils génériques (ChatGPT, Copilot, …) | Prototype actuel | V1 — été 2026 |
|---|---|---|---|
| **1. Provenance** — « D'où vient cette clause ? Quelle version, quelle date de signature ? » | Citation au niveau du document, sans pointeur vers le passage exact. Pas d'historique des versions. | Ingestion PDF / DOCX / images + OCR (Apple Vision pour les pièces d'identité). Citation au niveau du document, vérifiable. **32 documents hétérogènes indexés comme banc d'essai (factures, contrats, identité, fiscal) ; couverture de récupération 92 %.** | **Provenance fait-niveau** : chaque affirmation résolue en `(document, passage, version d'ingestion, extracteur, horodatage)`. API `/facts/{id}` exposant la chaîne de preuve complète, auditable. |
| **2. Cohérence** — « Nos pièces se contredisent-elles ? L'avenant 2018 est-il compatible avec le renouvellement 2020 ? » | Réponse unique, souvent plausible, **silencieusement moyennée**. Les conflits restent invisibles. | Graphe de connaissances local, désambiguïsation d'entités (variantes orthographiques, accents), annotations temporelles exploitées par le moteur de recherche. Conflits non encore surfacés. | **Objets Conflit de première classe** : deux faits incompatibles sur le même `(sujet, prédicat)` déclenchent un `Conflict` listé par l'API `/conflicts`. Résolution humaine par fichier YAML versionné dans Git (choix du gagnant, coexistence, supersession temporelle) — toute intervention est tracée. |
| **3. Temporalité** — « Quel était l'état du contrat au 1ᵉʳ juin 2020 ? » | Aucune notion de temps valide. Réponse fondée sur le document le plus « similaire », sans ancrage chronologique. | Annotations `[source : AAAA-MM-JJ]` au niveau des nœuds du graphe, utilisées pour la récupération. Pas encore de requête point-in-time. | **Validité bitemporelle par fait** : `valid_from` et `valid_to` explicites. Requête `/entities/{id}?as_of=2020-06-01` renvoyant l'état juridique à cette date. Prédicats déclarés variables dans le temps (adresse, mandat, tarif) vs invariants (date de naissance, identifiant unique). |

---

## Souveraineté des données

- Documents, graphe de connaissances, index vectoriels et embeddings : **sur la machine du cabinet ou serveur interne**.
- Modèles d'IA sélectionnés par étape du pipeline : possibilité de bascule entièrement locale (modèles ouverts, sans connexion internet) ou vers un cloud souverain européen, selon le niveau de sensibilité.
- Formats ouverts, portables, exportables. Pas de verrouillage propriétaire. Réversibilité totale.

---

## Calendrier indicatif

| Échéance | Livrable |
|---|---|
| **Aujourd'hui (V0)** | Ingestion multi-format + extraction d'entités + réponses avec citations au niveau du document sur 32 documents réels servant de banc d'essai. |
| **Mi-mai 2026** (Phase 6) | Modèle `Fait / Assertion / Conflit` de première classe ; API `/facts/{id}`. |
| **Début juin 2026** (Phase 7) | Détection automatique des contradictions ; workflow humain de résolution via fichiers versionnés. |
| **Mi-juin 2026** (Phase 8) | Requêtes temporelles point-in-time (`as_of`) ; versionnement à la ré-ingestion, sans effacement de l'historique. |
| **Mi-juillet 2026** (V1) | API FastAPI complète ; jeu d'évaluation étendu (25–30 cas, dont cas adversariaux : contradictions connues, doublons, mises à jour). |
| **Début août 2026** (Phase 11) | Serveur MCP (Model Context Protocol) pour consommation par agents LLM tiers (intégration dans des outils métier existants). |

---

## Ce que je cherche à valider dans cet échange

1. **Le besoin** — ces trois questions (provenance, cohérence, temporalité) correspondent-elles à une douleur opérationnelle dans votre pratique ?
2. **Le pack métier** — quels types d'actes, de clauses, de rôles, de dates méritent d'être des prédicats de premier rang dans votre domaine ?
3. **Les contraintes** — déontologie, secret professionnel, RGPD, archivage probant, réversibilité des données : quelles exigences structurent votre choix d'outil ?

Je serais intéressé par un échange pour voir si votre pratique peut bénéficier d'un pilote sur un sous-corpus représentatif.

---

**Contact.** Sébastien Boutet — sboutet06@googlemail.com
