from pathlib import Path

import pytest

from comfort_z.services.source import (
    GoogleCloudStorageAccessError,
    InvalidGoogleCloudStorageUriError,
    parse_google_cloud_storage_uri,
    resolve_video_source,
)


class FakeBlob:
    def __init__(self):
        self.downloaded_to = None
        self.error = None

    def download_to_filename(self, filename):
        self.downloaded_to = filename
        if self.error:
            raise self.error
        Path(filename).write_bytes(b"fake-video")


class FakeBucket:
    def __init__(self, blob):
        self.blob_instance = blob
        self.object_name = None

    def blob(self, object_name):
        self.object_name = object_name
        return self.blob_instance


class FakeStorageClient:
    def __init__(self, bucket):
        self.bucket_instance = bucket
        self.bucket_name = None

    def bucket(self, bucket_name):
        self.bucket_name = bucket_name
        return self.bucket_instance


def fake_storage():
    blob = FakeBlob()
    bucket = FakeBucket(blob)
    return FakeStorageClient(bucket), bucket, blob


def test_parse_valid_gcs_uri():
    parsed = parse_google_cloud_storage_uri("gs://animal-media/videos/today.mp4")

    assert parsed.bucket_name == "animal-media"
    assert parsed.object_name == "videos/today.mp4"


@pytest.mark.parametrize("uri", ["gs://", "gs:///video.mp4", "gs://animal-media", "gs://animal-media/"])
def test_parse_rejects_malformed_gcs_uri(uri):
    with pytest.raises(InvalidGoogleCloudStorageUriError, match="gs://bucket/object"):
        parse_google_cloud_storage_uri(uri)


def test_gcs_video_downloads_to_temporary_file_and_cleans_up_after_success():
    client, bucket, blob = fake_storage()

    with resolve_video_source(
        "gs://animal-media/videos/today.mp4", storage_client_factory=lambda: client
    ) as resolved:
        temporary_path = Path(resolved.local_source)
        assert temporary_path.exists()
        assert temporary_path.suffix == ".mp4"
        assert temporary_path.read_bytes() == b"fake-video"
        assert resolved.source_label == "gs://animal-media/videos/today.mp4"

    assert client.bucket_name == "animal-media"
    assert bucket.object_name == "videos/today.mp4"
    assert blob.downloaded_to == str(temporary_path)
    assert not temporary_path.exists()


def test_gcs_temporary_file_is_cleaned_when_processing_raises():
    client, _, _ = fake_storage()

    with pytest.raises(RuntimeError, match="processing failed"):
        with resolve_video_source(
            "gs://animal-media/videos/today.mp4", storage_client_factory=lambda: client
        ) as resolved:
            temporary_path = Path(resolved.local_source)
            assert temporary_path.exists()
            raise RuntimeError("processing failed")

    assert not temporary_path.exists()


def test_local_paths_and_webcams_are_unchanged_and_do_not_create_storage_clients(tmp_path):
    local_video = tmp_path / "animal.mp4"
    local_video.write_bytes(b"video")

    def no_storage_client():
        raise AssertionError("Storage must not be used for local sources.")

    with resolve_video_source(str(local_video), storage_client_factory=no_storage_client) as local:
        assert local.local_source == str(local_video)
        assert local.source_label is None
    with resolve_video_source(0, storage_client_factory=no_storage_client) as webcam:
        assert webcam.local_source == 0
        assert webcam.source_label is None


def test_gcs_permission_error_has_a_safe_domain_error():
    client, _, blob = fake_storage()

    class ForbiddenError(RuntimeError):
        code = 403

    blob.error = ForbiddenError("secret backend detail")

    with pytest.raises(GoogleCloudStorageAccessError, match="cannot access"):
        with resolve_video_source(
            "gs://animal-media/videos/today.mp4", storage_client_factory=lambda: client
        ):
            pass
