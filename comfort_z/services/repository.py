"""Local JSON and Firestore storage share a small repository interface."""
from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from comfort_z.models import DailyMonitoringReport, MonitoringProfile, OwnerUpdate, StoredObservation

load_dotenv()

class ObservationRepository(ABC):
    @abstractmethod
    def save(self, observation: StoredObservation) -> StoredObservation:
        """Persist one observation."""

    @abstractmethod
    def recent_for_animal(self, animal_id: str, limit: int = 5) -> list[StoredObservation]:
        """Return newest records first."""

    def history_for_animal(self, animal_id: str) -> list[StoredObservation]:
        """Return all saved records newest first when a bounded report needs them."""
        return self.recent_for_animal(animal_id, limit=1000)

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

    def history_for_animal(self, animal_id: str) -> list[StoredObservation]:
        matches = [item for item in self._all() if item.animal_id == animal_id]
        return sorted(matches, key=lambda item: item.timestamp, reverse=True)

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

    def history_for_animal(self, animal_id: str) -> list[StoredObservation]:
        try:
            query = self._observations_for(animal_id).order_by(
                "timestamp", direction=self._firestore.Query.DESCENDING
            )
            return [StoredObservation.model_validate(doc.to_dict()) for doc in query.stream()]
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not retrieve Firestore history for animal {animal_id}. "
                "Check network and Firestore permissions."
            ) from error


class MonitoringStateRepository(ABC):
    """Storage for monitoring profiles and generated reports, separate from observations."""

    @abstractmethod
    def save_profile(self, profile: MonitoringProfile) -> MonitoringProfile:
        """Create or update one animal's monitoring instructions."""

    @abstractmethod
    def get_profile(self, animal_id: str) -> MonitoringProfile | None:
        """Return one animal's profile when it exists."""

    @abstractmethod
    def list_profiles(self) -> list[MonitoringProfile]:
        """Return all saved monitoring profiles."""

    @abstractmethod
    def save_report(self, report: DailyMonitoringReport) -> DailyMonitoringReport:
        """Persist a generated daily report."""

    @abstractmethod
    def recent_reports(self, animal_id: str, limit: int = 5) -> list[DailyMonitoringReport]:
        """Return newest reports first."""

    @abstractmethod
    def save_owner_update(self, update: OwnerUpdate) -> OwnerUpdate:
        """Persist one owner-provided care update without replacing profile state."""

    @abstractmethod
    def recent_owner_updates(self, animal_id: str, limit: int = 20) -> list[OwnerUpdate]:
        """Return newest owner updates first."""

    @abstractmethod
    def owner_updates_for_period(
        self,
        animal_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[OwnerUpdate]:
        """Return a bounded chronological context set for monitoring or reporting."""


class LocalJsonMonitoringStateRepository(MonitoringStateRepository):
    """Development fallback stored separately from existing observation JSON."""

    def __init__(self, path: str | Path = "data/monitoring_state.json") -> None:
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"profiles": {}, "reports": [], "owner_updates": {}}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            "profiles": payload.get("profiles", {}),
            "reports": payload.get("reports", []),
            "owner_updates": payload.get("owner_updates", {}),
        }

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save_profile(self, profile: MonitoringProfile) -> MonitoringProfile:
        payload = self._read()
        payload["profiles"][profile.animal_id] = profile.model_dump(mode="json")
        self._write(payload)
        return profile

    def get_profile(self, animal_id: str) -> MonitoringProfile | None:
        raw = self._read()["profiles"].get(animal_id)
        return MonitoringProfile.model_validate(raw) if raw else None

    def list_profiles(self) -> list[MonitoringProfile]:
        raw_profiles = self._read()["profiles"].values()
        return [MonitoringProfile.model_validate(item) for item in raw_profiles]

    def save_report(self, report: DailyMonitoringReport) -> DailyMonitoringReport:
        payload = self._read()
        payload["reports"].append(report.model_dump(mode="json"))
        self._write(payload)
        return report

    def recent_reports(self, animal_id: str, limit: int = 5) -> list[DailyMonitoringReport]:
        reports = [
            DailyMonitoringReport.model_validate(item)
            for item in self._read()["reports"]
            if item.get("animal_id") == animal_id
        ]
        return sorted(reports, key=lambda item: item.generated_at, reverse=True)[:limit]

    def save_owner_update(self, update: OwnerUpdate) -> OwnerUpdate:
        payload = self._read()
        payload["owner_updates"].setdefault(update.animal_id, []).append(
            update.model_dump(mode="json")
        )
        self._write(payload)
        return update

    def recent_owner_updates(self, animal_id: str, limit: int = 20) -> list[OwnerUpdate]:
        updates = [
            OwnerUpdate.model_validate(item)
            for item in self._read()["owner_updates"].get(animal_id, [])
        ]
        return sorted(updates, key=lambda item: item.occurred_at, reverse=True)[:limit]

    def owner_updates_for_period(
        self,
        animal_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[OwnerUpdate]:
        updates = [
            item
            for item in self.recent_owner_updates(animal_id, limit=1000)
            if start <= item.occurred_at <= end
        ]
        return sorted(updates, key=lambda item: item.occurred_at, reverse=True)[:limit]


class FirestoreMonitoringStateRepository(MonitoringStateRepository):
    """Firestore state at animals/{id}/monitoring/profile, reports, and owner updates."""

    def __init__(self, project: str, client: object | None = None) -> None:
        try:
            from google.cloud import firestore

            self._firestore = firestore
            self.client = client or firestore.Client(project=project)
            self.animals = self.client.collection("animals")
        except Exception as error:
            raise ObservationRepositoryError(
                "Could not initialize Firestore monitoring state. Check Application Default "
                "Credentials, GOOGLE_CLOUD_PROJECT, and Firestore access."
            ) from error

    def _animal_document(self, animal_id: str):
        return self.animals.document(animal_id)

    def save_profile(self, profile: MonitoringProfile) -> MonitoringProfile:
        animal = self._animal_document(profile.animal_id)
        try:
            animal.set(
                {
                    "animal_id": profile.animal_id,
                    "animal_name": profile.animal_name,
                    "expected_species": profile.expected_species,
                },
                merge=True,
            )
            animal.collection("monitoring").document("profile").set(
                profile.model_dump(mode="json")
            )
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not save monitoring profile for animal {profile.animal_id}. "
                "Check network and Firestore permissions."
            ) from error
        return profile

    def get_profile(self, animal_id: str) -> MonitoringProfile | None:
        try:
            snapshot = self._animal_document(animal_id).collection("monitoring").document(
                "profile"
            ).get()
            if not snapshot.exists:
                return None
            return MonitoringProfile.model_validate(snapshot.to_dict())
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not retrieve monitoring profile for animal {animal_id}. "
                "Check network and Firestore permissions."
            ) from error

    def list_profiles(self) -> list[MonitoringProfile]:
        try:
            profiles: list[MonitoringProfile] = []
            for doc in self.animals.stream():
                animal_id = getattr(doc, "id", None) or (doc.to_dict() or {}).get("animal_id")
                if not animal_id:
                    continue
                profile = self.get_profile(animal_id)
                if profile is not None:
                    profiles.append(profile)
            return profiles
        except Exception as error:
            if isinstance(error, ObservationRepositoryError):
                raise
            raise ObservationRepositoryError(
                "Could not retrieve monitoring profiles from Firestore. "
                "Check network and Firestore permissions."
            ) from error

    def save_report(self, report: DailyMonitoringReport) -> DailyMonitoringReport:
        try:
            self._animal_document(report.animal_id).collection("reports").document(
                report.report_id
            ).set(report.model_dump(mode="json"))
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not save daily report {report.report_id} for animal {report.animal_id}. "
                "Check network and Firestore permissions."
            ) from error
        return report

    def recent_reports(self, animal_id: str, limit: int = 5) -> list[DailyMonitoringReport]:
        try:
            query = (
                self._animal_document(animal_id)
                .collection("reports")
                .order_by("generated_at", direction=self._firestore.Query.DESCENDING)
                .limit(limit)
            )
            return [DailyMonitoringReport.model_validate(doc.to_dict()) for doc in query.stream()]
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not retrieve daily reports for animal {animal_id}. "
                "Check network and Firestore permissions."
            ) from error

    def save_owner_update(self, update: OwnerUpdate) -> OwnerUpdate:
        try:
            self._animal_document(update.animal_id).collection("owner_updates").document(
                update.owner_update_id
            ).set(update.model_dump(mode="json"))
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not save owner update {update.owner_update_id} for animal "
                f"{update.animal_id}. Check network and Firestore permissions."
            ) from error
        return update

    def recent_owner_updates(self, animal_id: str, limit: int = 20) -> list[OwnerUpdate]:
        try:
            query = (
                self._animal_document(animal_id)
                .collection("owner_updates")
                .order_by("occurred_at", direction=self._firestore.Query.DESCENDING)
                .limit(limit)
            )
            return [OwnerUpdate.model_validate(doc.to_dict()) for doc in query.stream()]
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not retrieve owner updates for animal {animal_id}. "
                "Check network and Firestore permissions."
            ) from error

    def owner_updates_for_period(
        self,
        animal_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[OwnerUpdate]:
        try:
            query = (
                self._animal_document(animal_id)
                .collection("owner_updates")
                .where("occurred_at", ">=", start.isoformat())
                .where("occurred_at", "<=", end.isoformat())
                .order_by("occurred_at", direction=self._firestore.Query.DESCENDING)
                .limit(limit)
            )
            return [OwnerUpdate.model_validate(doc.to_dict()) for doc in query.stream()]
        except Exception as error:
            raise ObservationRepositoryError(
                f"Could not retrieve owner-update context for animal {animal_id}. "
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


def get_monitoring_state_repository() -> MonitoringStateRepository:
    """Choose the same local/Firestore mode used by observation persistence."""
    if os.getenv("OBSERVATION_STORE", "local").lower() == "firestore":
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ObservationRepositoryError(
                "GOOGLE_CLOUD_PROJECT is required when OBSERVATION_STORE=firestore."
            )
        return FirestoreMonitoringStateRepository(project)
    return LocalJsonMonitoringStateRepository(
        os.getenv("LOCAL_MONITORING_STATE_FILE", "data/monitoring_state.json")
    )
