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
    post_drs_object,
)
from cgpclient.utils import REQUEST_TIMEOUT_SECS, CGPClientException, md5sum

mimetypes.add_type("text/vcf", ext=".vcf")
mimetypes.add_type("application/cram", ext=".cram")
mimetypes.add_type("application/bam", ext=".bam")
mimetypes.add_type("text/fastq", ext=".fastq")
mimetypes.add_type("text/fasta", ext=".fasta")
mimetypes.add_type("text/fastq", ext=".ora")


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


def _request_upload(
    upload_request: DrsUploadRequest,
    api_base_url: str,
    headers: dict[str, str] | None = None,
) -> DrsUploadResponse:
    """Request upload details from the DRS server"""
    logging.info("Requesting upload")

    logging.debug(upload_request.model_dump_json(exclude_defaults=True))

    response: requests.Response = requests.post(
        url=f"https://{api_base_url}/upload-request",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECS,
        json=upload_request.model_dump(),
    )
    response.raise_for_status()

    if response.ok:
        logging.info("Got response from DRS upload request endpoint")
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
        logging.info("Uploading %s to %s", filename, s3_url)
        s3.upload_file(filename, Bucket=parsed_url.bucket, Key=parsed_url.key)
        logging.info("Uploaded %s to %s", filename, s3_url)
    except Exception as e:
        raise CGPClientException("Error uploading file to S3") from e


def _create_upload_request(
    filename: Path,
    mime_type: str,
) -> DrsUploadRequest:
    """Create a DrsUploadRequest object for the file"""
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


def _get_upload_response_object(
    filename: Path,
    mime_type: str,
    api_base_url: str,
    headers: dict[str, str] | None = None,
) -> DrsUploadResponseObject:
    """Request to upload the file to the DRS server"""
    upload_request: DrsUploadRequest = _create_upload_request(
        filename=filename, mime_type=mime_type
    )

    upload_response: DrsUploadResponse = _request_upload(
        upload_request=upload_request, api_base_url=api_base_url, headers=headers
    )

    return upload_response.objects[filename.name]


def upload_file_with_drs(
    filename: Path,
    api_base_url: str,
    mime_type: str | None = None,
    headers: dict[str, str] | None = None,
    dry_run: bool = False,
) -> DrsObject:
    """Upload the file following the DRS upload protocol"""
    if mime_type is None:
        (mime_type, _) = mimetypes.guess_file_type(filename)
        if mime_type is None:
            raise CGPClientException(f"Unable to guess MIME type for file: {filename}")

    upload_response_object: DrsUploadResponseObject = _get_upload_response_object(
        filename=filename,
        mime_type=mime_type,
        api_base_url=api_base_url,
        headers=headers,
    )

    s3_upload_method: DrsUploadMethod = upload_response_object.get_upload_method(
        upload_method_type=DrsUploadMethodType.S3
    )

    _upload_file_to_s3(
        filename=filename, upload_method=s3_upload_method, dry_run=dry_run
    )

    drs_object: DrsObject = upload_response_object.to_drs_object(
        upload_method=s3_upload_method
    )

    post_drs_object(drs_object, api_base_url, headers, dry_run)

    return drs_object
