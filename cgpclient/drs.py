from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

try:
    from enum import StrEnum  # type: ignore
except ImportError:
    from backports.strenum import StrEnum  # type: ignore

import requests  # type: ignore
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

import cgpclient
import cgpclient.client
from cgpclient.utils import (
    CHUNK_SIZE_BYTES,
    REQUEST_TIMEOUT_SECS,
    CGPClientException,
    md5sum,
)

# Definitions from:
# https://ga4gh.github.io/data-repository-service-schemas/preview/release/drs-1.4.0/docs/


class AccessMethodType(StrEnum):  # type: ignore
    S3 = "s3"
    GS = "gs"
    FTP = "ftp"
    GSIFTP = "gsiftp"
    GLOBUS = "globus"
    HTSGET = "htsget"
    HTTPS = "https"
    FILE = "file"


class ChecksumType(StrEnum):  # type: ignore
    MD5 = "md5"


class Checksum(BaseModel):
    checksum: str
    type: str


class AccessURL(BaseModel):
    url: str
    headers: list[str] | None = []


class Authorizations(BaseModel):
    drs_object_id: str
    supported_types: list[str] | None = []
    passport_auth_issuers: list[str] | None = []
    bearer_auth_issuers: list[str] | None = []


class AccessMethod(BaseModel):
    type: AccessMethodType
    access_url: AccessURL | None = None
    access_id: str | None = None
    region: str | None = None
    authorizations: Authorizations | None = None

    @model_validator(mode="after")
    def check_access_method_provided(self) -> Self:
        if self.access_id is None and self.access_url is None:
            raise ValueError(
                "access_method must have at least one of access_id or access_url set"
            )
        return self


class ContentsObject(BaseModel):
    name: str
    id: str | None = None
    drs_uri: list[str] | None = []
    contents: List["ContentsObject"] | None = []


class DrsObject(BaseModel):
    id: str
    name: str | None = None
    self_uri: str
    size: int
    created_time: str | None = (
        None  # this is required in the spec, but can be set by the server
    )
    updated_time: str | None = None
    version: str | None = None
    mime_type: str | None = None
    checksums: list[Checksum] = Field(min_length=1)
    access_methods: list[AccessMethod] = Field(min_length=1)
    contents: list[ContentsObject] | None = []
    description: str | None = None
    aliases: list[str] | None = []

    def _get_fetchable_url_for_access_id(
        self,
        client: cgpclient.client.CGPClient,
        access_method_type: AccessMethodType = AccessMethodType.S3,  # type: ignore
    ) -> str:
        access_method: AccessMethod | None = self.get_access_method(
            access_method_type=access_method_type
        )
        if access_method is None:
            raise CGPClientException(
                f"No access method found for type {access_method_type}"
            )

        if access_method.access_id is None:
            raise CGPClientException(
                f"No access ID found for access method of type {access_method_type}"
            )

        https_url: str = _https_url_from_id(self.id, client=client)
        url: str = f"{https_url}/access/{access_method.access_id}"
        logging.info("Requesting endpoint: %s", url)
        response = requests.get(
            url=url,
            headers=client.headers,
            timeout=REQUEST_TIMEOUT_SECS,
        )
        if response.ok:
            access_url: AccessURL = AccessURL.model_validate(response.json())
            logging.info("Successfully retrieved fetchable URL")
            logging.debug(access_url.url)
            return access_url.url

        raise CGPClientException("Failed to get fetchable URL from access ID")

    def get_access_method(
        self, access_method_type: AccessMethodType
    ) -> AccessMethod | None:
        for access_method in self.access_methods:
            if access_method.type == access_method_type:
                return access_method
        return None

    def download_data(
        self,
        client: cgpclient.client.CGPClient,
        output: Path | None = None,
        force_overwrite: bool = False,
        expected_hash: str | None = None,
    ) -> None:
        logging.info("Downloading data for DRS object")
        presigned_url: str = self._get_fetchable_url_for_access_id(
            access_method_type=AccessMethodType.S3,  # type: ignore
            client=client,
        )
        if output is None and self.name is not None:
            output = Path(self.name)
        if output is None:
            raise CGPClientException("Need either an output path or a DRS object name")
        _stream_data_from_https_url(
            https_url=presigned_url,
            output=output,
            force_overwrite=force_overwrite,
            expected_hash=expected_hash,
        )


class Error(BaseModel):
    msg: str
    status_code: int


def drs_base_url(api_base_url: str) -> str:
    """Return the base HTTPS URL for the DRS server"""
    return f"https://{api_base_url}/ga4gh/drs/v1.4"


def _map_drs_to_https_url(drs_url: str) -> str:
    """Map a DRS URL to the corresponding HTTPS URL"""
    if not drs_url.startswith("drs://"):
        raise CGPClientException(f"Invalid DRS URL: {drs_url}")
    try:
        # e.g.       drs://api.service.nhs.uk/genomic-data-access/1234
        # maps to: https://api.service.nhs.uk/genomic-data-access/ga4gh/drs/v1.4/objects/1234 # noqa: E501
        (_, _, base_url, api_name, object_id) = drs_url.split("/")
        api_base_url: str = f"{base_url}/{api_name}"
        https_url: str = f"{drs_base_url(api_base_url)}/objects/{object_id}"
        logging.debug("Mapped DRS URL: %s to HTTPS URL: %s", drs_url, https_url)
        return https_url
    except ValueError as e:
        logging.error("Error parsing DRS URL: %s", drs_url)
        raise CGPClientException(f"Unable to parse DRS URL: {drs_url}") from e


def _map_https_to_drs_url(https_url: str) -> str:
    """Map an HTTPS URL to a DRS URL"""
    if not https_url.startswith("https://"):
        raise CGPClientException(f"Invalid HTTPS URL: {https_url}")
    try:
        # e.g.    https://api.service.nhs.uk/genomic-data-access/ga4gh/drs/v1.4/objects/1234 # noqa: E501
        # maps to:  drs://api.service.nhs.uk/genomic-data-access/1234
        (_, _, base_url, api_name, _, _, _, _, object_id) = https_url.split("/")
        drs_url: str = f"drs://{base_url}/{api_name}/{object_id}"
        logging.debug("Mapped HTTPS URL: %s to DRS URL: %s", https_url, drs_url)
        return drs_url
    except ValueError as e:
        logging.error("Error parsing HTTPS DRS URL: %s", https_url)
        raise CGPClientException(f"Unable to parse HTTPS DRS URL: {https_url}") from e


def _override_api_base_url(url: str, host: str) -> str:
    _, path = url.split("/ga4gh/")
    return f"https://{host}/ga4gh/{path}"


def _https_url_from_id(object_id: str, client: cgpclient.client.CGPClient) -> str:
    """Construct a n HTTPS DRS URL from a DRS object ID"""
    if "/" in object_id:
        raise CGPClientException(f"Invalid DRS object ID: {object_id}")
    return f"{drs_base_url(client.api_base_url)}/objects/{object_id}"


def _resolve_drs_url_to_https(drs_url: str, client: cgpclient.client.CGPClient) -> str:
    """Turn a drs:// URL into https:// overriding the host as required"""
    if drs_url.startswith("drs:"):
        drs_url = _map_drs_to_https_url(drs_url)

    if drs_url.startswith("https:"):
        if client.override_api_base_url:
            drs_url = _override_api_base_url(url=drs_url, host=client.api_base_url)

            return drs_url

    raise CGPClientException(f"Invalid DRS URL format {drs_url}")


def _get_drs_object_from_https_url(
    https_url: str, client: cgpclient.client.CGPClient
) -> DrsObject:
    """Fetch a DRS object from the specified URL"""
    logging.info("Requesting endpoint: %s", https_url)
    response: requests.Response = requests.get(
        url=https_url,
        headers=client.headers,
        timeout=REQUEST_TIMEOUT_SECS,
    )
    if response.ok:
        return DrsObject.model_validate(response.json())

    logging.error(
        "Failed to fetch from endpoint: %s status: %i response: %s",
        https_url,
        response.status_code,
        response.text,
    )

    raise CGPClientException(
        f"Error getting DRS object, got status code: {response.status_code}"
    )


def _stream_data_from_https_url(
    https_url: str,
    output: Path,
    force_overwrite: bool = False,
    expected_hash: str | None = None,
) -> None:
    if not https_url.lower().startswith("https://"):
        raise CGPClientException(f"Expecting HTTPS URL, got: {https_url}")

    logging.info("Writing to %s", output)
    if output.exists() and not force_overwrite:
        overwrite: str = input(f"overwrite existing {output}? (y/n [n]) ")
        if not overwrite.lower().startswith("y"):
            print("not overwritten", file=sys.stderr)
            return

    logging.info("Streaming data from URL")
    with requests.get(
        url=https_url, stream=True, timeout=REQUEST_TIMEOUT_SECS
    ) as response:
        response.raise_for_status()
        num_chunks: int = 0
        with open(output, "wb") as out:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE_BYTES):
                out.write(chunk)
                num_chunks += 1
        logging.info("Download complete in %i chunks", num_chunks)
        if expected_hash is not None:
            # check for object integrity
            if md5sum(output) != expected_hash:
                raise CGPClientException(
                    f"Downloaded file hash does not match expected hash {expected_hash}"
                )
            logging.info("File hash successfully verified")


def get_drs_object(
    drs_url: str, client: cgpclient.client.CGPClient, expected_hash: str | None = None
) -> DrsObject:
    logging.info("Fetching DRS object from URL: %s", drs_url)
    https_url: str = _resolve_drs_url_to_https(drs_url=drs_url, client=client)
    logging.info("Resolved DRS URL to: %s", https_url)
    drs_object: DrsObject = _get_drs_object_from_https_url(
        https_url=https_url, client=client
    )
    if expected_hash is not None:
        for checksum in drs_object.checksums:
            if checksum.type == ChecksumType.MD5 and checksum.checksum != expected_hash:
                raise CGPClientException(
                    f"Mismatching hash for DRS object, got "
                    f"{checksum.checksum} expected {expected_hash}"
                )
        logging.info("DRS object hash matches expected")
    logging.debug(drs_object)
    return drs_object


def post_drs_object(drs_object: DrsObject, client: cgpclient.client.CGPClient) -> None:
    endpoint: str = f"{drs_base_url(client.api_base_url)}/objects"
    logging.info("Posting DRS object: %s", drs_object.id)
    logging.debug(drs_object.model_dump_json(exclude_defaults=True))

    if client.dry_run:
        logging.info("Dry run, so skipping posting DRS object")
        return

    if client.output_dir is not None:
        output_file: Path = client.output_dir / Path("drs_objects.json")
        logging.info("Writing DRS object to %s", output_file)
        with open(output_file, "a", encoding="utf-8") as out:
            print(drs_object.model_dump_json(), file=out)

    response: requests.Response = requests.post(
        url=endpoint,
        headers=client.headers,
        timeout=REQUEST_TIMEOUT_SECS,
        json=drs_object.model_dump(),
    )
    if response.ok:
        logging.info("Successfully posted DRS objects")
    else:
        raise CGPClientException(
            (
                f"Error posting DRS object, status code: "
                f"{response.status_code} response: {response.text}"
            )
        )
