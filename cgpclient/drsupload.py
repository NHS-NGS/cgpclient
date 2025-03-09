import logging
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
from cgpclient.utils import REQUEST_TIMEOUT_SECS, CGPClientException, md5sum


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
    upload_method_types: list[DrsUploadMethodType] = Field(min_length=1)


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
                    # we use the S3 URL as an access ID to fetch a pre-signed URL
                    access_id=upload_method.access_url.url,
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
    response: requests.Response = requests.post(
        url=f"{api_base_url}/upload-request",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECS,
        data=upload_request.model_dump_json(),
    )
    if response.ok:
        return DrsUploadResponse.model_validate(response.json())

    raise CGPClientException("Upload request failed")


def parse_s3_url(s3_url: str) -> S3Url:
    bucket, key = s3_url.replace("s3://", "").split("/", 1)
    return S3Url(bucket=bucket, key=key)


def upload_file_to_s3(filename: Path, upload_method: DrsUploadMethod) -> str:
    """Upload the provided file to S3 using the details in the supplied upload method"""
    if upload_method.type != DrsUploadMethodType.S3:
        raise CGPClientException(f"Invalid upload_method type: {upload_method.type}")
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=upload_method.credentials["aws_access_key_id"],
            aws_secret_access_key=upload_method.credentials["aws_secret_access_key"],
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
        s3.upload_file(filename, bucket=parsed_url.bucket, key=parsed_url.key)
        logging.info("Uploaded %s to %s", filename, s3_url)
        return s3_url
    except Exception as e:
        raise CGPClientException("Error uploading file to S3") from e


def get_upload_request(
    filename: Path,
    mime_type: str,
    upload_method_type: DrsUploadMethodType,
) -> DrsUploadRequest:
    return DrsUploadRequest(
        objects=[
            DrsUploadRequestObject(
                name=filename.name,
                checksums=[Checksum(type="md5", checksum=md5sum(filename))],
                size=filename.stat().st_size,
                mime_type=mime_type,
                upload_method_types=[upload_method_type],
            )
        ]
    )


def get_upload_object(
    filename: Path,
    mime_type: str,
    upload_method_type: DrsUploadMethodType,
    api_base_url: str,
    headers: dict[str, str] | None = None,
) -> DrsUploadResponseObject:
    upload_request: DrsUploadRequest = get_upload_request(
        filename=filename, mime_type=mime_type, upload_method_type=upload_method_type
    )

    upload_response: DrsUploadResponse = request_upload(
        upload_request=upload_request, api_base_url=api_base_url, headers=headers
    )

    return upload_response.objects[filename.name]


def upload_file(
    filename: Path,
    mime_type: str,
    api_base_url: str,
    post_resource: bool = False,
    headers: dict[str, str] | None = None,
) -> DrsObject:
    upload_object: DrsUploadResponseObject = get_upload_object(
        filename=filename,
        mime_type=mime_type,
        upload_method_type=DrsUploadMethodType.S3,
        api_base_url=api_base_url,
        headers=headers,
    )

    s3_upload_method: DrsUploadMethod = upload_object.get_upload_method(
        upload_method_type=DrsUploadMethodType.S3
    )

    upload_file_to_s3(
        filename=filename,
        upload_method=s3_upload_method,
    )

    drs_object: DrsObject = upload_object.to_drs_object(upload_method=s3_upload_method)

    if post_resource:
        put_object(drs_object, api_base_url, headers)

    return drs_object
