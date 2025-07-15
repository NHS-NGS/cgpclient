# flake8: noqa: E501
# pylint: disable=wrong-import-order, redefined-outer-name, ungrouped-imports, line-too-long, too-many-arguments, protected-access

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cgpclient.client import CGPClient
from cgpclient.drs import DrsObject
from cgpclient.drsupload import (
    AccessURL,
    DrsUploadMethod,
    DrsUploadMethodType,
    DrsUploadRequest,
    DrsUploadResponse,
    DrsUploader,
    S3Client,
    upload_files_with_drs,
)
from cgpclient.drs import DrsClient
from cgpclient.utils import CGPClientException, create_uuid


@pytest.fixture(scope="function")
def client() -> CGPClient:
    return CGPClient(api_host="host")


def make_upload_response(upload_request: DrsUploadRequest) -> dict:
    objects: dict = {}
    for obj in upload_request.objects:
        drs_id: str = create_uuid()
        objects[obj.name] = {
            "id": drs_id,
            "name": obj.name,
            "self_uri": f"drs://api.service.nhs.uk/genomic-data-access/{drs_id}",
            "size": obj.size,
            "mime_type": obj.mime_type,
            "checksums": obj.checksums,
            "upload_methods": [
                {
                    "type": "s3",
                    "access_url": {"url": f"s3://bucket/prefix/{obj.name}"},
                    "region": "eu-west-2",
                    "credentials": {
                        "aws_access_key_id": "123",
                        "aws_secret_access_key": "secret",
                    },
                }
            ],
        }
    return {"objects": objects}


@patch("requests.post")
def test_request_upload(mock_server: MagicMock, tmp_path, client: CGPClient):
    file_name = "test.fastq.gz"
    filename: Path = Path(tmp_path / file_name)
    with open(filename, "w", encoding="utf-8") as file:
        file.write("foo")
    drs_client = DrsClient(
        client.api_base_url,
        client.headers,
        client.dry_run,
        client.override_api_base_url,
    )
    uploader = DrsUploader(drs_client)
    upload_request: DrsUploadRequest = uploader._create_upload_request(
        filenames=[filename]
    )

    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return make_upload_response(upload_request)

        def raise_for_status(self):
            pass

    mock_server.return_value = MockedResponse()

    response: DrsUploadResponse = uploader._request_upload(upload_request)

    mock_server.assert_called_once()

    assert len(response.objects) == 1


@patch("boto3.client")
def test_s3_upload(mock_boto: MagicMock) -> None:
    file = Path("test.fastq.gz")
    input_bucket = "foo"
    input_key = "bar.txt"
    s3_url = f"s3://{input_bucket}/{input_key}"
    creds = {"AccessKeyId": "key", "SecretAccessKey": "secret", "SessionToken": "token"}

    class MockedBotoS3Client:
        def upload_file(self, upload, Bucket, Key):
            assert upload == file
            assert Bucket == input_bucket
            assert Key == input_key
            return True

    mock_boto.return_value = MockedBotoS3Client()

    s3_client = S3Client(dry_run=False)
    s3_client.upload_file(
        file,
        upload_method=DrsUploadMethod(
            type=DrsUploadMethodType.S3,
            access_url=AccessURL(url=s3_url),
            credentials=creds,
            region="eu-west-2",
        ),
    )

    mock_boto.assert_called_once_with(
        "s3",
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name="eu-west-2",
    )

    with pytest.raises(CGPClientException):
        # wrong upload type
        s3_client.upload_file(
            Path("test.fastq.gz"),
            upload_method=DrsUploadMethod(
                type=DrsUploadMethodType.HTTPS,
                access_url=AccessURL(url=s3_url),
                credentials=creds,
            ),
        )

    with pytest.raises(CGPClientException):
        # wrong creds
        s3_client.upload_file(
            Path("test.fastq.gz"),
            upload_method=DrsUploadMethod(
                type=DrsUploadMethodType.S3,
                access_url=AccessURL(url=s3_url),
                credentials={},
            ),
        )


@patch("cgpclient.drsupload.DrsUploader._request_upload")
@patch("cgpclient.drsupload.S3Client.upload_file")
@patch("cgpclient.drs.DrsClient.post_drs_object")
def test_drs_upload_file(
    mock_post_object: MagicMock,
    mock_s3_upload: MagicMock,
    mock_request_upload: MagicMock,
    tmp_path,
    client: CGPClient,
):
    file_name = "test.fastq.gz"
    file_data: str = "foo"
    filename: Path = Path(tmp_path / file_name)
    with open(filename, "w", encoding="utf-8") as file:
        file.write(file_data)

    drs_client = DrsClient(
        client.api_base_url,
        client.headers,
        client.dry_run,
        client.override_api_base_url,
    )
    uploader = DrsUploader(drs_client)
    upload_request: DrsUploadRequest = uploader._create_upload_request(
        filenames=[filename]
    )

    mock_request_upload.return_value = DrsUploadResponse.model_validate(
        make_upload_response(upload_request)
    )
    mock_s3_upload.return_value = "foo"
    mock_post_object.return_value = None

    drs_objects: list[DrsObject] = upload_files_with_drs(
        filenames=[filename],
        headers=client.headers,
        api_base_url=client.api_base_url,
        dry_run=client.dry_run,
        output_dir=client.output_dir,
    )

    assert len(drs_objects) == 1

    drs_object: DrsObject = drs_objects[0]

    mock_request_upload.assert_called_once()
    mock_s3_upload.assert_called_once()
    mock_post_object.assert_called_once()

    assert drs_object.name == file_name
    assert drs_object.size == len(file_data)
    assert len(drs_object.access_methods) == 1
    assert drs_object.access_methods[0].access_id == "s3"
