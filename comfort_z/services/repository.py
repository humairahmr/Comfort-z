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

class FirestoreObservationRepository(ObservationRepository):
    def __init__(self, project: str, collection: str = "animal_observations") -> None:
        from google.cloud import firestore

        self._firestore = firestore
        self.collection = firestore.Client(project=project).collection(collection)

    def save(self, observation: StoredObservation) -> StoredObservation:
        self.collection.document(observation.observation_id).set(observation.model_dump(mode="json"))
        return observation

    def recent_for_animal(self, animal_id: str, limit: int = 5) -> list[StoredObservation]:
        query = (
            self.collection.where("animal_id", "==", animal_id)
            .order_by("timestamp", direction=self._firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [StoredObservation.model_validate(doc.to_dict()) for doc in query.stream()]

def get_repository() -> ObservationRepository:
    if os.getenv("OBSERVATION_STORE", "local").lower() == "firestore":
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required when OBSERVATION_STORE=firestore.")
        return FirestoreObservationRepository(project, os.getenv("FIRESTORE_COLLECTION", "animal_observations"))
    return LocalJsonObservationRepository(os.getenv("LOCAL_OBSERVATION_FILE", "data/observations.json"))
