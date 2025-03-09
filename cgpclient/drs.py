import logging
from enum import StrEnum
from typing import List

import requests  # type: ignore
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from cgpclient.utils import REQUEST_TIMEOUT_SECS, CGPClientException, create_uuid

# Definitions from:
# https://ga4gh.github.io/data-repository-service-schemas/preview/release/drs-1.4.0/docs/


class AccessMethodType(StrEnum):
    S3 = "s3"
    GS = "gs"
    FTP = "ftp"
    GSIFTP = "gsiftp"
    GLOBUS = "globus"
    HTSGET = "htsget"
    HTTPS = "https"
    FILE = "file"


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
    return f"https://{api_base_url}/ga4gh/drs/v1.4"


def get_object_from_url(url: str, headers: dict[str, str] | None = None) -> DrsObject:
    logging.info("Requesting endpoint: %s", url)
    response: requests.Response = requests.get(
        url=url,
        headers=headers,
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


def get_object(
    object_id: str, api_base_url: str, headers: dict[str, str] | None = None
) -> DrsObject:
    return get_object_from_url(
        url=f"{drs_base_url(api_base_url)}/objects/{object_id}",
        headers=headers,
    )


def map_drs_to_https_url(drs_url: str) -> str:
    if not drs_url.startswith("drs://"):
        raise CGPClientException(f"Invalid DRS URL: {drs_url}")
    try:
        # e.g.       drs://api.service.nhs.uk/genomic-data-access/1234
        # maps to: https://api.service.nhs.uk/genomic-data-access/ga4gh/drs/v1.4/objects/1234 # noqa: E501
        (_, _, base_url, api_name, object_id) = drs_url.split("/")
        api_base_url: str = f"{base_url}/{api_name}"
        https_url: str = f"{drs_base_url(api_base_url)}/objects/{object_id}"
        logging.info("Mapped DRS URL: %s to HTTPS URL: %s", drs_url, https_url)
        return https_url
    except ValueError as e:
        logging.error("Error parsing DRS URL: %s", drs_url)
        raise CGPClientException(f"Unable to parse DRS URL: {drs_url}") from e


def map_https_to_drs_url(https_url: str) -> str:
    if not https_url.startswith("https://"):
        raise CGPClientException(f"Invalid HTTPS URL: {https_url}")
    try:
        # e.g.    https://api.service.nhs.uk/genomic-data-access/ga4gh/drs/v1.4/objects/1234 # noqa: E501
        # maps to:  drs://api.service.nhs.uk/genomic-data-access/1234
        (_, _, base_url, api_name, _, _, _, _, object_id) = https_url.split("/")
        drs_url: str = f"drs://{base_url}/{api_name}/{object_id}"
        logging.info("Mapped HTTPS URL: %s to DRS URL: %s", https_url, drs_url)
        return drs_url
    except ValueError as e:
        logging.error("Error parsing HTTPS DRS URL: %s", https_url)
        raise CGPClientException(f"Unable to parse HTTPS DRS URL: {https_url}") from e


def _rewrite_api_base_url(url: str, host: str) -> str:
    _, path = url.split("/ga4gh/")
    return f"https://{host}/ga4gh/{path}"


def get_access_url(
    object_url: str,
    access_type: str | None = None,
    headers: dict[str, str] | None = None,
    api_base_url_override: str | None = None,
) -> str | None:
    logging.info("Fetching %s access_url for DRS URL: %s", access_type, object_url)
    if object_url.startswith("drs:"):
        object_url = map_drs_to_https_url(object_url)

    if object_url.startswith("https:"):
        if api_base_url_override is not None:
            object_url = _rewrite_api_base_url(object_url, api_base_url_override)
        response: DrsObject = get_object_from_url(url=object_url, headers=headers)
        for access_method in response.access_methods:
            if access_method.access_url is not None:
                if access_type is None or access_method.type == access_type:
                    logging.info(
                        "Found %s access_url: %s",
                        access_type,
                        access_method.access_url.url,
                    )
                    if api_base_url_override:
                        return _rewrite_api_base_url(
                            access_method.access_url.url, api_base_url_override
                        )
                    return access_method.access_url.url
        # we didn't find an access_method
        return None
    raise CGPClientException(f"Unsupported protocol for access URL: {object_url}")


def put_object(
    drs_object: DrsObject, api_base_url: str, headers: dict[str, str] | None = None
) -> None:
    endpoint: str = drs_uri(drs_object.id, api_base_url)
    logging.info("Posting DRS object: %s to: %s", drs_object.id, endpoint)
    response: requests.Response = requests.post(
        url=endpoint,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECS,
        json=drs_object.model_dump_json(),
    )
    if not response.ok:
        raise CGPClientException(
            (
                f"Error posting DRS object, status code: "
                f"{response.status_code} response: {response.text}"
            )
        )


def drs_uri(object_id: str, api_base_url: str) -> str:
    return f"{drs_base_url(api_base_url)}/objects/{object_id}"


def access_method_for_s3(
    s3_bucket: str,
    s3_key: str,
    s3_region: str,
) -> AccessMethod:
    return AccessMethod(
        type="s3", access_id=f"s3://{s3_bucket}/{s3_key}", region=s3_region
    )


def object_for_s3(
    s3_bucket: str,
    s3_key: str,
    mime_type: str,
    api_base_url: str,
    s3_region: str = "eu-west-2",
    size: int = 0,
    md5_checksum: str = "",
    drs_id: str | None = None,
) -> DrsObject:
    if drs_id is None:
        drs_id = create_uuid()

    return DrsObject(
        id=drs_id,
        name=s3_key,
        mime_type=mime_type,
        size=size,
        checksums=[Checksum(type="md5", checksum=md5_checksum)],
        self_uri=drs_uri(object_id=drs_id, api_base_url=api_base_url),
        access_methods=[
            access_method_for_s3(
                s3_bucket=s3_bucket, s3_key=s3_key, s3_region=s3_region
            )
        ],
    )
