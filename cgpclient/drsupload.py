from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

try:
    from enum import StrEnum  # type: ignore
except ImportError:
    from backports.strenum import StrEnum  # type: ignore

import boto3  # type: ignore
import requests  # type: ignore
from pydantic import BaseModel, Field

import cgpclient
import cgpclient.client
from cgpclient.drs import (
    AccessMethod,
    AccessMethodType,
    AccessURL,
    Checksum,
    ChecksumType,
    DrsObject,
    post_drs_object,
)
from cgpclient.htsget import htsget_base_url, mime_type_to_htsget_endpoint
from cgpclient.utils import REQUEST_TIMEOUT_SECS, CGPClientException, md5sum

mimetypes.add_type("text/vcf", ext=".vcf")
mimetypes.add_type("application/cram", ext=".cram")
mimetypes.add_type("application/bam", ext=".bam")
mimetypes.add_type("text/fastq", ext=".fastq")
mimetypes.add_type("text/fasta", ext=".fasta")
mimetypes.add_type("text/fastq", ext=".ora")
mimetypes.add_type("application/index", ext=".tbi")
mimetypes.add_type("application/index", ext=".csi")
mimetypes.add_type("application/index", ext=".crai")
mimetypes.add_type("application/index", ext=".bai")


class DrsUploadMethodType(StrEnum):  # type: ignore
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

    def to_drs_object(
        self, upload_method: DrsUploadMethod, api_base_url: str
    ) -> DrsObject:
        access_methods: list[AccessMethod] = []
        if upload_method.type == DrsUploadMethodType.S3:
            access_methods.append(
                AccessMethod(
                    type=AccessMethodType.S3,  # type: ignore
                    access_id="s3",
                    access_url=upload_method.access_url,
                    region=upload_method.region,
                )
            )
        else:
            raise CGPClientException(
                f"Unsupported upload_method type: {upload_method.type}"
            )

        htsget_endpoint: str | None = mime_type_to_htsget_endpoint(self.mime_type)
        if htsget_endpoint is not None:
            endpoint = (
                f"{htsget_base_url(api_base_url=api_base_url)}/"
                f"{htsget_endpoint}/{self.id}"
            )
            access_methods.append(
                AccessMethod(
                    type=AccessMethodType.HTSGET, access_url=AccessURL(url=endpoint)
                )
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


def guess_mime_type(filename: Path) -> str:
    (mime_type, _) = mimetypes.guess_type(filename)
    if mime_type is not None:
        return mime_type
    raise CGPClientException(f"Unable to guess MIME type for file: {filename}")


def _request_upload(
    upload_request: DrsUploadRequest,
    client: cgpclient.client.CGPClient,  # type: ignore
) -> DrsUploadResponse:
    """Request upload details from the DRS server"""
    logging.info("Requesting upload")

    logging.debug(upload_request.model_dump_json(exclude_defaults=True))

    response: requests.Response = requests.post(
        url=f"https://{client.api_base_url}/upload-request",
        headers=client.headers,
        timeout=REQUEST_TIMEOUT_SECS,
        json=upload_request.model_dump(),
    )
    response.raise_for_status()

    if response.ok:
        logging.info("Upload request successful")
        drs_response: DrsUploadResponse = DrsUploadResponse.model_validate(
            response.json()
        )
        logging.debug(drs_response.model_dump_json(exclude_defaults=True))
        return drs_response

    raise CGPClientException("Upload request failed")


def parse_s3_url(s3_url: str) -> S3Url:
    """Parse an S3 URL into an S3Url object"""
    bucket, key = s3_url.replace("s3://", "").split("/", 1)
    return S3Url(bucket=bucket, key=key)


def _upload_file_to_s3(
    filename: Path, upload_method: DrsUploadMethod, dry_run: bool = False
) -> None:
    """Upload the provided file to S3 using the details in the supplied upload method"""
    if upload_method.type != DrsUploadMethodType.S3:
        raise CGPClientException(f"Invalid upload_method type: {upload_method.type}")

    if dry_run:
        logging.info("Dry run, so skipping uploading S3 object")
        return

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
        logging.info("Uploading %s", filename)
        s3.upload_file(filename, Bucket=parsed_url.bucket, Key=parsed_url.key)
        logging.info("Uploaded successfully to %s", s3_url)
    except Exception as e:
        raise CGPClientException("Error uploading file to S3") from e


def _create_upload_request_object(
    filenames: list[Path],
) -> list[DrsUploadRequestObject]:
    objects: list[DrsUploadRequestObject] = []
    for filename in filenames:
        objects.append(
            DrsUploadRequestObject(
                name=filename.name,
                checksums=[Checksum(type=ChecksumType.MD5, checksum=md5sum(filename))],
                size=filename.stat().st_size,
                mime_type=guess_mime_type(filename),
            )
        )
    return objects


def _create_upload_request(filenames: list[Path]) -> DrsUploadRequest:
    """Create a DrsUploadRequest object for the files"""
    return DrsUploadRequest(objects=_create_upload_request_object(filenames=filenames))


def _get_upload_response_object(
    filenames: list[Path],
    client: cgpclient.client.CGPClient,  # type: ignore
) -> dict[str, DrsUploadResponseObject]:
    """Request to upload the file to the DRS server"""
    upload_request: DrsUploadRequest = _create_upload_request(filenames=filenames)

    upload_response: DrsUploadResponse = _request_upload(
        upload_request=upload_request, client=client
    )

    return upload_response.objects


def _upload_file_with_upload_response_object(
    filename: Path,
    upload_response_object: DrsUploadResponseObject,
    client: cgpclient.client.CGPClient,  # type: ignore
) -> DrsObject:
    s3_upload_method: DrsUploadMethod = upload_response_object.get_upload_method(
        upload_method_type=DrsUploadMethodType.S3  # type: ignore
    )

    _upload_file_to_s3(
        filename=filename, upload_method=s3_upload_method, dry_run=client.dry_run
    )

    drs_object: DrsObject = upload_response_object.to_drs_object(
        upload_method=s3_upload_method, api_base_url=client.api_base_url
    )

    post_drs_object(drs_object, client=client)

    return drs_object


def upload_files_with_drs(
    filenames: list[Path],
    client: cgpclient.client.CGPClient,
) -> list[DrsObject]:
    """Upload the file following the DRS upload protocol"""

    upload_response_objects: dict[str, DrsUploadResponseObject] = (
        _get_upload_response_object(
            filenames=filenames,
            client=client,
        )
    )

    drs_objects: list[DrsObject] = []

    for filename in filenames:
        drs_objects.append(
            _upload_file_with_upload_response_object(
                filename=filename,
                upload_response_object=upload_response_objects[str(filename.name)],
                client=client,
            )
        )

    return drs_objects
