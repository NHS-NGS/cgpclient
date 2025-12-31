from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Mapping, Any

try:
    from enum import StrEnum  # type: ignore
except ImportError:
    from backports.strenum import StrEnum  # type: ignore

import boto3  # type: ignore
import requests  # type: ignore
from pydantic import BaseModel, Field

from cgpclient.drs import (
    AccessMethod,
    AccessMethodType,
    AccessURL,
    Checksum,
    ChecksumType,
    CGPDrsClient,
    DrsObject, DrsCandidateObject,
)
from cgpclient.htsget import htsget_base_url, mime_type_to_htsget_endpoint
from cgpclient.utils import REQUEST_TIMEOUT_SECS, CGPClientException, md5sum

log = logging.getLogger(__name__)

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


def _normalise_credential_key(key: str) -> str:
    """
    Normalise credential keys to be comparison-friendly:
    - lower-case
    - remove non-alphanumeric characters (underscores, hyphens, spaces, etc.)
    """
    return "".join(ch for ch in key.lower() if ch.isalnum())


def coerce_aws_credentials(credentials: Mapping[str, Any]) -> dict[str, str]:
    """
    Coerce AWS credentials keys from various common spellings/cases into canonical AWS keys:
    - AccessKeyId
    - SecretAccessKey
    - SessionToken (optional)

    Accepts variants like:
      access_key_id, aws_access_key_id, AWSAccessKeyId, AccessKeyID, session-token, etc.
    """
    if not isinstance(credentials, Mapping):
        raise CGPClientException("Invalid AWS credentials format (expected an object/map)")

    # Build a normalised lookup from the provided keys
    normalised_to_value: dict[str, Any] = {
        _normalise_credential_key(str(k)): v for k, v in credentials.items()
    }

    aliases: dict[str, list[str]] = {
        "AccessKeyId": [
            "accesskeyid",
            "awsaccesskeyid",
            "aws_access_key_id",
            "access_key_id",
        ],
        "SecretAccessKey": [
            "secretaccesskey",
            "awssecretaccesskey",
            "aws_secret_access_key",
            "secret_access_key",
        ],
        "SessionToken": [
            "sessiontoken",
            "awssessiontoken",
            "aws_session_token",
            "session_token",
        ],
    }

    coerced: dict[str, str] = {}
    missing_required: list[str] = []

    for canonical_key, key_aliases in aliases.items():
        found = None
        for alias in key_aliases:
            normalised_alias = _normalise_credential_key(alias)
            if normalised_alias in normalised_to_value:
                found = normalised_to_value[normalised_alias]
                break

        if found is None:
            if canonical_key in ("AccessKeyId", "SecretAccessKey"):
                missing_required.append(canonical_key)
            continue

        if not isinstance(found, str):
            raise CGPClientException(
                f"Invalid AWS credential value type for {canonical_key} (expected string)"
            )
        coerced[canonical_key] = found

    if missing_required:
        raise CGPClientException(
            f"Missing necessary AWS credentials: {', '.join(missing_required)}"
        )

    return coerced


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

    def to_drs_candidateobject(
            self, upload_method: DrsUploadMethod, api_base_url: str
    ) -> DrsCandidateObject:
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

        return DrsCandidateObject(
            name=self.name,
            size=self.size,
            mime_type=self.mime_type,
            checksums=self.checksums,
            access_methods=access_methods,
            description=self.description,
        )


class DrsUploadResponse(BaseModel):
    objects: dict[str, DrsUploadResponseObject]


class S3Url(BaseModel):
    bucket: str
    key: str


class S3Client:
    """Handles S3 upload operations"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def upload_file(self, filename: Path, upload_method: DrsUploadMethod) -> None:
        """Upload file to S3 using the upload method details"""
        if upload_method.type != DrsUploadMethodType.S3:
            raise CGPClientException(
                f"Invalid upload_method type: {upload_method.type}"
            )

        if self.dry_run:
            log.info("Dry run, so skipping uploading S3 object")
            return

        try:
            creds = coerce_aws_credentials(upload_method.credentials)

            s3 = boto3.client(
                "s3",
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds.get("SessionToken"),
                region_name=upload_method.region,
            )
        except KeyError as e:
            raise CGPClientException("Missing necessary AWS credentials") from e
        except Exception as e:
            raise CGPClientException("Error creating S3 client") from e

        try:
            s3_url = upload_method.access_url.url
            parsed_url = self._parse_s3_url(s3_url)
            log.info("Uploading %s", filename)
            s3.upload_file(filename, Bucket=parsed_url.bucket, Key=parsed_url.key)
            log.info("Uploaded successfully to %s", s3_url)
        except Exception as e:
            raise CGPClientException("Error uploading file to S3") from e

    def _parse_s3_url(self, s3_url: str) -> S3Url:
        """Parse an S3 URL into an S3Url object"""
        bucket, key = s3_url.replace("s3://", "").split("/", 1)
        return S3Url(bucket=bucket, key=key)


class DrsUploader:
    """Handles DRS file upload operations"""

    def __init__(self, drs_client: CGPDrsClient, s3_client: S3Client | None = None):
        self.drs_client = drs_client
        self.s3_client = s3_client or S3Client(drs_client.dry_run)

    def upload_files(
        self, filenames: list[Path], output_dir: Path | None = None
    ) -> list[DrsObject]:
        """Upload files following the DRS upload protocol"""
        upload_response_objects = self._get_upload_response_objects(filenames)
        drs_objects = []

        for filename in filenames:
            upload_response_object = next(
               obj for obj in upload_response_objects.values()
                if obj.name == filename.name
            )
            drs_objects.append(
                self._upload_file_with_response_object(
                    filename=filename,
                    upload_response_object=upload_response_object,
                    output_dir=output_dir,
                )
            )

        return drs_objects

    def _get_upload_response_objects(
        self, filenames: list[Path]
    ) -> dict[str, DrsUploadResponseObject]:
        """Request upload details from the DRS server"""
        upload_request = self._create_upload_request(filenames)
        upload_response = self._request_upload(upload_request)
        return upload_response.objects

    def _create_upload_request(self, filenames: list[Path]) -> DrsUploadRequest:
        """Create a DrsUploadRequest object for the files"""
        objects = []
        for filename in filenames:
            objects.append(
                DrsUploadRequestObject(
                    name=filename.name,
                    checksums=[
                        Checksum(type=ChecksumType.MD5, checksum=md5sum(filename))
                    ],
                    size=filename.stat().st_size,
                    mime_type=self._guess_mime_type(filename),
                )
            )
        return DrsUploadRequest(objects=objects)

    def _request_upload(self, upload_request: DrsUploadRequest) -> DrsUploadResponse:
        """Request upload details from the DRS server"""
        log.info("Requesting upload")
        log.debug(upload_request.model_dump_json(exclude_defaults=True))

        response = requests.post(
            url=f"{self.drs_client.base_url}/upload-request",
            headers=self.drs_client.headers,
            timeout=REQUEST_TIMEOUT_SECS,
            json=upload_request.model_dump(),
        )
        response.raise_for_status()

        if response.ok:
            log.info("Upload request successful")
            drs_response = DrsUploadResponse.model_validate(response.json())
            log.debug(drs_response.model_dump_json(exclude_defaults=True))
            return drs_response

        raise CGPClientException("Upload request failed")

    def _upload_file_with_response_object(
        self,
        filename: Path,
        upload_response_object: DrsUploadResponseObject,
        output_dir: Path | None = None,
    ) -> DrsObject:
        """Upload a single file using the upload response object"""
        s3_upload_method = upload_response_object.get_upload_method(
            upload_method_type=DrsUploadMethodType.S3
        )

        self.s3_client.upload_file(filename=filename, upload_method=s3_upload_method)

        drs_candidate_object = upload_response_object.to_drs_candidateobject(
            upload_method=s3_upload_method, api_base_url=self.drs_client.api_base_url
        )

        drs_object = self.drs_client.post_drs_candidate_object(drs_candidate_object, output_dir)
        return drs_object

    def _guess_mime_type(self, filename: Path) -> str:
        """Guess MIME type from filename"""
        (mime_type, _) = mimetypes.guess_type(filename)
        if mime_type is not None:
            return mime_type
        raise CGPClientException(f"Unable to guess MIME type for file: {filename}")
