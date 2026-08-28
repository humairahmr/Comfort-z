"""Local JSON and Firestore storage share a small repository interface."""
from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from dotenv import load_dotenv
from comfort_z.models import StoredObservation

load_dotenv()

class ObservationRepository(ABC):
    @abstractmethod
    def save(self, observation: StoredObservation) -> StoredObservation:
        """Persist one observation."""

    @abstractmethod
    def recent_for_animal(self, animal_id: str, limit: int = 5) -> list[StoredObservation]:
        """Return newest records first."""

class LocalJsonObservationRepository(ObservationRepository):
    def __init__(self, path: str | Path = "data/observations.json") -> None:
        self.path = Path(path)

    def _all(self) -> list[StoredObservation]:
        if not self.path.exists():
            return []
        raw_items = json.loads(self.path.read_text(encoding="utf-8"))
        return [StoredObservation.model_validate(item) for item in raw_items]

    def _write(self, observations: list[StoredObservation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in observations]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save(self, observation: StoredObservation) -> StoredObservation:
        observations = self._all()
        observations.append(observation)
        self._write(observations)
        return observation

    def recent_for_animal(self, animal_id: str, limit: int = 5) -> list[StoredObservation]:
        matches = [item for item in self._all() if item.animal_id == animal_id]
        return sorted(matches, key=lambda item: item.timestamp, reverse=True)[:limit]

class ObservationRepositoryError(RuntimeError):
    """A storage failure with enough context for an agent or owner to act on it."""


class FirestoreObservationRepository(ObservationRepository):
    """Firestore history at animals/{animal_id}/observations/{observation_id}."""

    def __init__(
        self,
        project: str,
        observations_collection: str = "observations",
        client: object | None = None,
    ) -> None:
        try:
            from google.cloud import firestore

            self._firestore = firestore
            self.client = client or firestore.Client(project=project)
            self.animals = self.client.collection("animals")
            self.observations_collection = observations_collection
        except Exception as error:
            raise ObservationRepositoryError(
                "Could not initialize Firestore. Check Application Default Credentials, "
                "GOOGLE_CLOUD_PROJECT, and Firestore access."
            ) from error

    def _observations_for(self, animal_id: str):
        return self.animals.document(animal_id).collection(self.observations_collection)

    def save(self, observation: StoredObservation) -> StoredObservation:
        animal_document = self.animals.document(observation.animal_id)
        animal_metadata = {
            "animal_id": observation.animal_id,
            "animal_name": observation.animal_name,
            "expected_species": observation.expected_species,
        }
        try:
            animal_document.set(animal_metadata, merge=True)
            self._observations_for(observation.animal_id).document(
                observation.observation_id
            ).set(observation.model_dump(mode="json"))
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not save observation {observation.observation_id} to Firestore for "
                f"animal {observation.animal_id}. Check network and Firestore permissions."
            ) from error
        return observation

    def recent_for_animal(self, animal_id: str, limit: int = 5) -> list[StoredObservation]:
        try:
            query = (
                self._observations_for(animal_id)
                .order_by("timestamp", direction=self._firestore.Query.DESCENDING)
                .limit(limit)
            )
            return [StoredObservation.model_validate(doc.to_dict()) for doc in query.stream()]
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not retrieve Firestore history for animal {animal_id}. "
                "Check network and Firestore permissions."
            ) from error

def get_repository() -> ObservationRepository:
    if os.getenv("OBSERVATION_STORE", "local").lower() == "firestore":
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ObservationRepositoryError(
                "GOOGLE_CLOUD_PROJECT is required when OBSERVATION_STORE=firestore."
            )
        observations_collection = os.getenv(
            "FIRESTORE_OBSERVATIONS_COLLECTION",
            os.getenv("FIRESTORE_COLLECTION", "observations"),
        )
        return FirestoreObservationRepository(project, observations_collection)
    return LocalJsonObservationRepository(os.getenv("LOCAL_OBSERVATION_FILE", "data/observations.json"))
