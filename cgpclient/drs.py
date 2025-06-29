from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

try:
    from enum import StrEnum  # type: ignore
except ImportError:
    from backports.strenum import StrEnum

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


class Error(BaseModel):
    msg: str
    status_code: int


def drs_base_url(api_base_url: str) -> str:
    """Return the base HTTPS URL for the DRS server"""
    return f"https://{api_base_url}/ga4gh/drs/v1.4"


def get_drs_object_from_url(url: str, client: cgpclient.client.CGPClient) -> DrsObject:
    """Fetch a DRS object from the specified URL"""
    logging.info("Requesting endpoint: %s", url)
    response: requests.Response = requests.get(
        url=url,
        headers=client.headers,
        timeout=REQUEST_TIMEOUT_SECS,
    )
    if response.ok:
        return DrsObject.model_validate(response.json())

    logging.error(
        "Failed to fetch from endpoint: %s status: %i response: %s",
        url,
        response.status_code,
        response.text,
    )

    raise CGPClientException(
        f"Error getting DRS object, got status code: {response.status_code}"
    )


def get_drs_object(object_id: str, client: cgpclient.client.CGPClient) -> DrsObject:
    """Fetch the DRS object from the server"""
    return get_drs_object_from_url(
        url=f"{drs_base_url(client.api_base_url)}/objects/{object_id}",
        client=client,
    )


def get_s3_access_url(drs_object: DrsObject, client: cgpclient.client.CGPClient) -> str:
    url: str = f"{drs_base_url(client.api_base_url)}/objects/{drs_object.id}/access/s3"
    for method in drs_object.access_methods:
        if method.type == AccessMethodType.S3:
            logging.info("Requesting endpoint: %s", url)
            response = requests.get(
                url=url,
                headers=client.headers,
                timeout=REQUEST_TIMEOUT_SECS,
            )
            if response.ok:
                access_url: AccessURL = AccessURL.model_validate(response.json())
                logging.info("Successfully retrieved S3 access URL")
                logging.debug(access_url.url)
                return access_url.url
    raise CGPClientException("Failed to get S3 access URL")


def stream_data_from_url(
    url: str,
    output: Path,
    force_overwrite: bool = False,
    object_hash: str | None = None,
) -> None:
    logging.info("Writing to %s", output)
    if output.exists() and not force_overwrite:
        overwrite: str = input(f"overwrite existing {output}? (y/n [n]) ")
        if not overwrite.lower().startswith("y"):
            print("not overwritten", file=sys.stderr)
            return

    logging.info("Streaming data from URL")
    with requests.get(url=url, stream=True, timeout=REQUEST_TIMEOUT_SECS) as response:
        response.raise_for_status()
        num_chunks: int = 0
        with open(output, "wb") as out:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE_BYTES):
                out.write(chunk)
                num_chunks += 1
        logging.info("Download complete in %i chunks", num_chunks)
        if object_hash is not None:
            # check for object integrity
            if md5sum(output) != object_hash:
                raise CGPClientException("Incorrect hash for downloaded file")
            logging.info("File hash successfully verified")


def normalise_drs_url(object_url: str, client: cgpclient.client.CGPClient) -> str:
    if object_url.startswith("drs:"):
        object_url = map_drs_to_https_url(object_url)

    if object_url.startswith("https:"):
        if client.override_api_base_url:
            object_url = _override_api_base_url(
                url=object_url, host=client.api_base_url
            )

            return object_url

    raise CGPClientException(f"Invalid DRS URL format {object_url}")


def download_object_data(
    drs_url: str,
    client: cgpclient.client.CGPClient,
    output: Path | None = None,
    force_overwrite: bool = False,
    object_hash: str | None = None,
) -> None:
    logging.info("Downloading data for DRS URL: %s", drs_url)
    resolved_url: str = normalise_drs_url(object_url=drs_url, client=client)
    logging.info("Resolved DRS URL to: %s", resolved_url)
    drs_object: DrsObject = get_drs_object_from_url(url=resolved_url, client=client)
    logging.debug(drs_object)
    if object_hash is not None:
        for checksum in drs_object.checksums:
            if checksum.type == ChecksumType.MD5 and checksum.checksum != object_hash:
                raise CGPClientException(
                    f"Mismatching hash on DRS object and DocumentReference: "
                    f"{checksum.checksum} vs {object_hash}"
                )
    presigned_url: str = get_s3_access_url(drs_object=drs_object, client=client)
    if output is None and drs_object.name is not None:
        output = Path(drs_object.name)
    if output is None:
        raise CGPClientException("Need either an output path or a DRS object name")
    stream_data_from_url(
        url=presigned_url,
        output=output,
        force_overwrite=force_overwrite,
        object_hash=object_hash,
    )


def map_drs_to_https_url(drs_url: str) -> str:
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


def map_https_to_drs_url(https_url: str) -> str:
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


def get_access_url(
    object_url: str,
    client: cgpclient.client.CGPClient,
    access_type: str | None = None,
) -> str | None:
    """Fetch an access URL of the specified type for the corresponding DRS object"""
    logging.info("Fetching %s access_url for DRS URL: %s", access_type, object_url)
    if object_url.startswith("drs:"):
        object_url = map_drs_to_https_url(object_url)

    if object_url.startswith("https:"):
        if client.override_api_base_url is not None:
            object_url = _override_api_base_url(
                url=object_url, host=drs_base_url(client.api_base_url)
            )
        response: DrsObject = get_drs_object_from_url(url=object_url, client=client)
        for access_method in response.access_methods:
            if access_method.access_url is not None:
                if access_type is None or access_method.type == access_type:
                    logging.info(
                        "Found %s access_url: %s",
                        access_type,
                        access_method.access_url.url,
                    )
                    return access_method.access_url.url
        # we didn't find an access_method
        return None
    raise CGPClientException(f"Unsupported protocol for access URL: {object_url}")


def post_drs_object(drs_object: DrsObject, client: cgpclient.client.CGPClient) -> None:
    endpoint: str = f"{drs_base_url(client.api_base_url)}/objects"
    logging.info("Posting DRS object: %s", drs_object.id)
    logging.debug(drs_object.model_dump_json(exclude_defaults=True))

    if client.dry_run:
        logging.info("Dry run, so skipping posting DRS object")
        return

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
