import logging
import mimetypes
from enum import StrEnum
from pathlib import Path

import boto3  # type: ignore
import requests  # type: ignore
from pydantic import BaseModel, Field

from cgpclient.drs import (
    AccessMethod,
    AccessMethodType,
    AccessURL,
    Checksum,
    DrsObject,
    put_object,
)
from cgpclient.utils import (
    REQUEST_TIMEOUT_SECS,
    CGPClientException,
    create_uuid,
    md5sum,
)


class DrsUploadMethodType(StrEnum):
    S3 = "s3"
    HTTPS = "https"


class DrsUploadMethod(BaseModel):
    type: DrsUploadMethodType
    access_url: AccessURL
    region: str | None = None
    credentials: dict[str, str]


class DrsUploadRequestObject(BaseModel):
    name: str
    size: int
    mime_type: str
    checksums: list[Checksum] = Field(min_length=1)
    description: str | None = None
    aliases: list[str] | None = []


class DrsUploadRequest(BaseModel):
    objects: list[DrsUploadRequestObject]


class DrsUploadResponseObject(BaseModel):
    id: str
    self_uri: str
    name: str
    size: int
    mime_type: str
    checksums: list[Checksum] = Field(min_length=1)
    description: str | None = None
    aliases: list[str] | None = []
    upload_methods: list[DrsUploadMethod] | None = []

    def get_upload_method(
        self, upload_method_type: DrsUploadMethodType
    ) -> DrsUploadMethod:
        if self.upload_methods is None:
            raise CGPClientException("No upload_methods found")

        matching_upload_methods: list[DrsUploadMethod] = [
            method
            for method in self.upload_methods
            if method.type == upload_method_type
        ]

        if len(matching_upload_methods) != 1:
            raise CGPClientException("Expected exactly 1 matching upload_method")

        return matching_upload_methods[0]

    def to_drs_object(self, upload_method: DrsUploadMethod) -> DrsObject:
        access_methods: list[AccessMethod] = []
        if upload_method.type == DrsUploadMethodType.S3:
            access_methods.append(
                AccessMethod(
                    type=AccessMethodType.S3,
                    access_id="s3",
                    access_url=upload_method.access_url,
                    region=upload_method.region,
                )
            )
        else:
            raise CGPClientException(
                f"Unsupported upload_method type: {upload_method.type}"
            )

        return DrsObject(
            id=self.id,
            self_uri=self.self_uri,
            name=self.name,
            size=self.size,
            mime_type=self.mime_type,
            checksums=self.checksums,
            description=self.description,
            aliases=self.aliases,
            access_methods=access_methods,
        )


class DrsUploadResponse(BaseModel):
    objects: dict[str, DrsUploadResponseObject]


class S3Url(BaseModel):
    bucket: str
    key: str


def request_upload(
    upload_request: DrsUploadRequest,
    api_base_url: str,
    headers: dict[str, str] | None = None,
) -> DrsUploadResponse:
    logging.info("Requesting upload")

    logging.debug(upload_request.model_dump_json())

    response: requests.Response = requests.post(
        url=f"https://{api_base_url}/upload-request",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECS,
        json=upload_request.model_dump(),
    )
    response.raise_for_status()

    if response.ok:
        logging.debug("Got response from DRS upload request endpoint")
        return DrsUploadResponse.model_validate(response.json())

    raise CGPClientException("Upload request failed")


def parse_s3_url(s3_url: str) -> S3Url:
    bucket, key = s3_url.replace("s3://", "").split("/", 1)
    return S3Url(bucket=bucket, key=key)


def _mock_request_upload(
    upload_request: DrsUploadRequest,
    api_base_url: str,
    headers: dict[str, str] | None = None,
) -> DrsUploadResponse:
    objects: dict = {}
    for obj in upload_request.objects:
        drs_id: str = create_uuid()
        objects[obj.name] = DrsUploadResponseObject(
            id=drs_id,
            name=obj.name,
            self_uri=f"drs://tbc/{drs_id}",
            size=obj.size,
            mime_type=obj.mime_type,
            checksums=obj.checksums,
            upload_methods=[
                DrsUploadMethod(
                    type=DrsUploadMethodType.S3,
                    access_url=AccessURL(url=f"s3://bucket/prefix/{obj.name}"),
                    region="eu-west-2",
                    credentials={},
                )
            ],
        )

    return DrsUploadResponse(objects=objects)


def upload_file_to_s3(filename: Path, upload_method: DrsUploadMethod) -> str:
    """Upload the provided file to S3 using the details in the supplied upload method"""
    if upload_method.type != DrsUploadMethodType.S3:
        raise CGPClientException(f"Invalid upload_method type: {upload_method.type}")
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=upload_method.credentials["AccessKeyId"],
            aws_secret_access_key=upload_method.credentials["SecretAccessKey"],
            aws_session_token=upload_method.credentials["SessionToken"],
            region_name=upload_method.region,
        )
    except KeyError as e:
        raise CGPClientException("Missing necessary AWS credentials") from e
    except Exception as e:
        raise CGPClientException("Error creating S3 client") from e

    try:
        s3_url: str = upload_method.access_url.url
        parsed_url: S3Url = parse_s3_url(s3_url=s3_url)
        logging.info("Uploading %s to %s", filename, s3_url)
        s3.upload_file(filename, Bucket=parsed_url.bucket, Key=parsed_url.key)
        logging.info("Uploaded %s to %s", filename, s3_url)
        return s3_url
    except Exception as e:
        raise CGPClientException("Error uploading file to S3") from e


def get_upload_request(
    filename: Path,
    mime_type: str,
) -> DrsUploadRequest:
    return DrsUploadRequest(
        objects=[
            DrsUploadRequestObject(
                name=filename.name,
                checksums=[Checksum(type="md5", checksum=md5sum(filename))],
                size=filename.stat().st_size,
                mime_type=mime_type,
            )
        ]
    )


def get_upload_response_object(
    filename: Path,
    mime_type: str,
    api_base_url: str,
    headers: dict[str, str] | None = None,
    do_upload: bool = True,
) -> DrsUploadResponseObject:
    upload_request: DrsUploadRequest = get_upload_request(
        filename=filename, mime_type=mime_type
    )

    upload_response: DrsUploadResponse
    if do_upload:
        upload_response = request_upload(
            upload_request=upload_request, api_base_url=api_base_url, headers=headers
        )
    else:
        upload_response = _mock_request_upload(
            upload_request=upload_request, api_base_url=api_base_url, headers=headers
        )

    return upload_response.objects[filename.name]


def upload_file(
    filename: Path,
    api_base_url: str,
    mime_type: str | None,
    headers: dict[str, str] | None = None,
    do_upload: bool = True,
) -> DrsObject:
    if mime_type is None:
        (mime_type, _) = mimetypes.guess_file_type(filename)
        if mime_type is None:
            raise CGPClientException(f"Unable to guess MIME type for file: {filename}")

    upload_response_object: DrsUploadResponseObject = get_upload_response_object(
        filename=filename,
        mime_type=mime_type,
        api_base_url=api_base_url,
        headers=headers,
        do_upload=do_upload,
    )

    s3_upload_method: DrsUploadMethod = upload_response_object.get_upload_method(
        upload_method_type=DrsUploadMethodType.S3
    )

    if do_upload:
        upload_file_to_s3(
            filename=filename,
            upload_method=s3_upload_method,
        )

    drs_object: DrsObject = upload_response_object.to_drs_object(
        upload_method=s3_upload_method
    )

    if do_upload:
        put_object(drs_object, api_base_url, headers)

    return drs_object
