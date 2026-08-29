from datetime import datetime, timedelta, timezone

import pytest

from comfort_z.models import (
    GeminiObservation,
    MonitoringProfile,
    MonitoringSourceType,
    ObservationStatus,
    Severity,
    StoredObservation,
)
from comfort_z.services import repository as repository_module
from comfort_z.services.repository import (
    FirestoreObservationRepository,
    FirestoreMonitoringStateRepository,
    LocalJsonObservationRepository,
    ObservationRepositoryError,
    get_repository,
)


class FakeSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class FakeDocument:
    def __init__(self):
        self.data = None
        self.merge_values = []
        self.subcollections = {}

    def collection(self, name):
        return self.subcollections.setdefault(name, FakeCollection())

    def set(self, data, merge=False):
        self.merge_values.append(merge)
        self.data = {**(self.data or {}), **data} if merge else data

    def get(self):
        return FakeSnapshot(self.data)


class FakeCollection:
    def __init__(self):
        self.documents = {}
        self.order_by_arguments = None
        self._limit = None

    def document(self, identifier):
        return self.documents.setdefault(identifier, FakeDocument())

    def order_by(self, field, direction):
        self.order_by_arguments = (field, direction)
        return self

    def limit(self, value):
        self._limit = value
        return self

    def stream(self):
        values = [document.data for document in self.documents.values() if document.data]
        if any("timestamp" in val for val in values):
            ordered = sorted(values, key=lambda value: value.get("timestamp", ""), reverse=True)
        else:
            ordered = values
        return [FakeSnapshot(value) for value in ordered[: self._limit]]


class FakeFirestoreClient:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return self.collections.setdefault(name, FakeCollection())


class FailingFirestoreClient(FakeFirestoreClient):
    def collection(self, name):
        collection = super().collection(name)
        original_document = collection.document

        def failing_document(identifier):
            document = original_document(identifier)
            document.set = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline"))
            return document

        collection.document = failing_document
        return collection


def make_observation(timestamp: datetime) -> StoredObservation:
    visual = GeminiObservation(
        species="Betta splendens",
        animal_visible=True,
        observation_status=ObservationStatus.VALID,
        posture="swimming",
        activity_level="moderate",
        apparent_movement="moving",
        confidence=0.9,
        behavioral_interpretation="The fish appears alert.",
        uncertainty="One frame only.",
        severity=Severity.NORMAL,
    )
    return StoredObservation(
        animal_id="raku",
        animal_name="Raku",
        expected_species="Betta splendens",
        timestamp=timestamp,
        gemini_observation=visual,
        severity=Severity.NORMAL,
        explanation=visual.behavioral_interpretation,
        source_info="source=demo; frame=1; position=0.00s",
    )


def test_firestore_repository_uses_animal_subcollection_and_round_trips_data():
    client = FakeFirestoreClient()
    repository = FirestoreObservationRepository("comfort-z-test", client=client)
    first = make_observation(datetime(2026, 8, 28, tzinfo=timezone.utc))
    second = make_observation(first.timestamp + timedelta(seconds=5))

    repository.save(first)
    repository.save(second)
    history = repository.recent_for_animal("raku")

    animal = client.collections["animals"].documents["raku"]
    stored = animal.subcollections["observations"].documents[first.observation_id].data
    assert animal.data == {
        "animal_id": "raku",
        "animal_name": "Raku",
        "expected_species": "Betta splendens",
    }
    assert stored["source_info"] == "source=demo; frame=1; position=0.00s"
    assert stored["gemini_observation"]["animal_visible"] is True
    assert stored["gemini_observation"]["observation_status"] == "valid"
    assert [item.observation_id for item in history] == [second.observation_id, first.observation_id]


def test_firestore_save_error_is_actionable():
    repository = FirestoreObservationRepository("comfort-z-test", client=FailingFirestoreClient())

    with pytest.raises(ObservationRepositoryError, match="Could not save observation"):
        repository.save(make_observation(datetime.now(timezone.utc)))


def test_firestore_monitoring_profile_uses_animal_monitoring_subcollection():
    client = FakeFirestoreClient()
    repository = FirestoreMonitoringStateRepository("comfort-z-test", client=client)
    profile = MonitoringProfile(
        animal_id="raku",
        animal_name="Raku",
        expected_species="Betta splendens",
        monitoring_goal="Keep an eye on Raku.",
        source_reference="Raku.mp4",
        source_type=MonitoringSourceType.VIDEO,
        normal_sampling_interval_seconds=5,
        elevated_sampling_interval_seconds=1,
        daily_sample_budget=10,
    )

    repository.save_profile(profile)
    loaded = repository.get_profile("raku")

    stored = client.collections["animals"].documents["raku"].subcollections["monitoring"].documents[
        "profile"
    ].data
    assert stored["monitoring_goal"] == "Keep an eye on Raku."
    assert loaded is not None
    assert loaded.source_reference == "Raku.mp4"

    profiles = repository.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].animal_id == "raku"



def test_repository_selection_defaults_to_local_and_firestore_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVATION_STORE", "local")
    monkeypatch.setenv("LOCAL_OBSERVATION_FILE", str(tmp_path / "observations.json"))
    assert isinstance(get_repository(), LocalJsonObservationRepository)

    created = {}

    class CapturingFirestoreRepository:
        def __init__(self, project, observations_collection):
            created["project"] = project
            created["collection"] = observations_collection

    monkeypatch.setenv("OBSERVATION_STORE", "firestore")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "comfort-z-test")
    monkeypatch.setenv("FIRESTORE_OBSERVATIONS_COLLECTION", "observations")
    monkeypatch.setattr(repository_module, "FirestoreObservationRepository", CapturingFirestoreRepository)

    get_repository()
    assert created == {"project": "comfort-z-test", "collection": "observations"}
