#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

source venv/bin/activate

echo ""
echo "=== PILIER 1 : PROVENANCE — Parties et date du compromis de vente ==="
echo ""
python -m extraction query "Qui sont les parties au compromis de vente et quelle est la date de signature ?" 2>/dev/null

echo ""
echo "=== PILIER 2 : COHÉRENCE — Adresses de Sébastien Boutet dans les documents ==="
echo ""
python -m extraction query "Quelles adresses apparaissent pour Sébastien Boutet dans les documents ?" 2>/dev/null

echo ""
echo "=== PILIER 3 : TEMPORALITÉ — Adresse la plus récente dans les documents ==="
echo ""
python -m extraction query "Quelle est l'adresse la plus récente mentionnée dans les documents ?" 2>/dev/null

echo ""
echo "=== FIN DE LA DÉMO ==="
