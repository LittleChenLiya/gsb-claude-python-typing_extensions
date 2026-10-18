# nexus_omega_state.py
"""
NEXUS OMEGA STATE (NOS) - High-Performance Immutable State Machine
Remplace le TypedDict Update Planner v2.0.
Noyau de validation : Rust (via Pydantic V2).
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationError

# --- 1. LE NOYAU DE L'ÉTAT (Le Modèle) ---
class NexusState(BaseModel):
    """
    Modèle d'état immuable. 
    Une fois instancié, il ne peut plus être modifié directement.
    """
    # Configuration : Immuable, Strict sur les types de base
    model_config = ConfigDict(
        frozen=True,           # Rend l'objet immuable (pas de modification in-place)
        extra='forbid',        # Rejette les clés inconnues (Sparse Only)
        strict=True,           # Refuse la coercition de type (ex: "1" ne devient pas 1)
        validate_assignment=True
    )

    # Exemple de champs avec métadonnées
    id: str = Field(..., description="Identifiant unique de l'état")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configuration globale")
    
    # Champs "ReadOnly" (immuables après création)
    _immutable_fields = {"id"}

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v.startswith("nexus_"):
            raise ValueError("L'ID doit commencer par 'nexus_'")
        return v

# --- 2. LE MOTEUR DE MISE À JOUR (Le Planner) ---
class StatePlanner:
    """
    Orchestre les mises à jour partielles (Sparse Updates).
    Gère les contraintes de sécurité (Required, ReadOnly) à l'exécution.
    """

    @staticmethod
    def plan_update(current_state: NexusState, updates: Dict[str, Any]) -> NexusState:
        """
        Applique une mise à jour partielle sur l'état actuel.
        Retourne un NOUVEL objet état (le précédent est intact).
        """
        # 1. Vérification des champs immuables (ReadOnly)
        for key in updates.keys():
            if key in current_state.model_fields and key in getattr(current_state, '_immutable_fields', set()):
                raise PermissionError(f"Sécurité : Le champ '{key}' est en lecture seule (ReadOnly).")

        # 2. Extraction des données actuelles
        # On utilise model_dump() qui est ultra-rapide grâce à Rust
        current_data = current_state.model_dump()
        
        # 3. Fusion Sparsifiée
        # On applique seulement les clés fournies dans 'updates'
        merged_data = {**current_data, **updates}

        # 4. Re-validation et création d'un NOUVEL état
        try:
            new_state = NexusState(**merged_data)
            return new_state
        except ValidationError as e:
            # Renvoie l'erreur structurée (clé, raison, input) pour un rebond automatique
            print(f"Échec de la mise à jour : {e.errors()}")
            raise

# --- 3. EXEMPLE D'EXÉCUTION ---
if __name__ == "__main__":
    # Création d'un état initial
    state_v1 = NexusState(id="nexus_9400", config={"mode": "production", "debug": False})
    print(f"État initial : {state_v1.model_dump_json(indent=2)}\n")

    # Mise à jour autorisée
    planner = StatePlanner()
    state_v2 = planner.plan_update(state_v1, {"config": {"mode": "test", "debug": True}})
    print(f"État mis à jour : {state_v2.model_dump_json(indent=2)}\n")

    # Tentative de mise à jour illégale (ReadOnly)
    try:
        planner.plan_update(state_v2, {"id": "nexus_9999"})
    except PermissionError as e:
        print(f"Erreur de sécurité interceptée : {e}")
