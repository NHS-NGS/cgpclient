# pylint: disable=not-an-iterable,unsubscriptable-object
from __future__ import annotations

import logging
import typing
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import time

import jwt
import requests  # type: ignore
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen
from pydantic import BaseModel

from cgpclient.dragen import upload_dragen_run
from cgpclient.drs import DrsObject, get_drs_object
from cgpclient.drsupload import upload_files_with_drs
from cgpclient.fhir import (  # type: ignore
    CGPServiceRequest,
    ClientConfig,
    get_patient,
    get_resource,
    get_service_request,
    search_for_document_references,
    upload_files,
)
from cgpclient.utils import APIM_BASE_URL, REQUEST_TIMEOUT_SECS, CGPClientException


@dataclass
class CGPFile:
    document_reference_id: str
    participant_id: str
    author_ods_code: str
    name: str
    size: int
    hash: str
    drs_url: str
    content_type: str
    last_updated: str
    sample_id: str | None = None
    run_id: str | None = None
    referral_id: str | None = None
    s3_url: str | None = None
    htsget_url: str | None = None


class CGPReferral:
    referral_id: str


class NHSOAuthToken(BaseModel):
    access_token: str
    expires_in: str
    token_type: str
    issued_at: str


class CGPClient:
    """A client for interacting with Clinical Genomics Platform
    APIs in the NHS APIM"""

    def __init__(
        self,
        api_host: str,
        api_key: str,
        api_name: str | None = None,
        private_key_pem: Path | None = None,
        apim_kid: str | None = None,
        override_api_base_url: bool = False,
        dry_run: bool = False,
        config: ClientConfig | None = None,
    ):
        self.api_key = api_key
        self.api_host = api_host
        self.api_name = api_name
        self.private_key_pem = private_key_pem
        self.apim_kid = apim_kid
        self.override_api_base_url = override_api_base_url
        self.dry_run = dry_run
        self.config = ClientConfig() if config is None else config

        self._oauth_token: NHSOAuthToken | None = None
        self._using_sandbox_env = self.api_host.startswith("sandbox.")

    @property
    def api_base_url(self) -> str:
        """Return the base URL for the overall API"""
        if self.api_name is not None:
            # in APIM the base URL is host + API name
            return f"{self.api_host}/{self.api_name}"
        return self.api_host

    @property
    def oauth_endpoint(self) -> str:
        """Return the NHS OAuth endpoint for the environment"""
        return f"https://{self.api_host}/oauth2/token"

    def get_jwt(self) -> str:
        """Create a JWT in the NHS format and sign it with the private key"""
        # following: https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication # noqa: E501
        if self.private_key_pem is None or self.apim_kid is None:
            raise CGPClientException("Can't create JWT without private key PEM and KID")

        with open(self.private_key_pem, "r", encoding="utf-8") as pem:
            private_key = pem.read()

        expiry_time: int = int(time()) + (5 * 60)  # 5 mins in the future

        logging.debug(
            "Creating JWT for KID: %s and signing with private key: %s",
            self.apim_kid,
            self.private_key_pem,
        )

        return jwt.encode(
            payload={
                "sub": self.api_key,
                "iss": self.api_key,
                "jti": str(uuid.uuid4()),
                "aud": self.oauth_endpoint,
                "exp": expiry_time,
            },
            key=private_key,
            algorithm="RS512",
            headers={"kid": self.apim_kid},
        )

    def request_access_token(self) -> NHSOAuthToken:
        """Fetch an OAuth token from the NHS OAuth server"""
        # following: https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication # noqa: E501
        logging.info("Requesting OAuth token from: %s", self.oauth_endpoint)
        response: requests.Response = requests.post(
            url=self.oauth_endpoint,
            headers={"content-type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": (
                    "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
                ),
                "client_assertion": self.get_jwt(),
            },
            timeout=REQUEST_TIMEOUT_SECS,
        )
        if response.ok:
            logging.info("Got successful response from OAuth server")
            return NHSOAuthToken.model_validate(response.json())

        raise CGPClientException(
            f"Failed to get OAuth token, status code: {response.status_code}"
        )

    def get_oauth_token(self) -> NHSOAuthToken:
        """Get the current OAuth token, making a new request to the NHS
        OAuth server if it is not available or has expired"""
        if self._oauth_token is None or (
            int(time())
            > int(self._oauth_token.issued_at) + int(self._oauth_token.expires_in)
        ):
            # we need to fetch a new token from the NHS
            logging.info("Requesting new OAuth token")
            self._oauth_token = self.request_access_token()

        return self._oauth_token

    def get_access_token(self) -> str | None:
        """Get the current OAuth access token value"""
        if self._using_sandbox_env:
            logging.info("No access token required in sandbox environment")
            return None

        return self.get_oauth_token().access_token

    @property
    def headers(self) -> dict[str, str]:
        """Fetch the HTTP headers necessary to interact with NHS APIM"""

        if self._using_sandbox_env:
            logging.debug("Skipping authentication for sandbox environment")
            return {}

        if self.private_key_pem is not None:
            # use OAuth if we're given a private key
            logging.debug("Using signed JWT authentication")
            return {"Authorization": f"Bearer {self.get_access_token()}"}

        if self.api_key is not None:
            # use the supplied API key
            logging.debug("Using API key authentication")
            if APIM_BASE_URL in self.api_host:
                # use APIM header
                logging.debug("Using APIM API key header")
                return {"apikey": self.api_key}

            # otherwise use standard header
            logging.debug("Using standard API key header")
            return {"X-API-Key": self.api_key}

        # no auth by default
        logging.debug("No API authentication")
        return {}

    def get_service_request(self, referral_id: str) -> CGPServiceRequest:
        """Fetch a FHIR ServiceRequest resource for the given NGIS referral ID"""
        return get_service_request(referral_id=referral_id, client=self)

    def get_patient(self, participant_id: str) -> Patient:
        """Fetch a FHIR Patient resource for the given NGIS participant ID"""
        return get_patient(participant_id=participant_id, client=self)

    def download_data_from_drs_document_reference(
        self,
        document_reference: DocumentReference,
        output: Path | None = None,
        force_overwrite: bool = False,
    ) -> None:
        """Download the DRS object data attached to the DocumentReference"""
        for content in document_reference.content:
            url: str = content.attachment.url  # type: ignore
            doc_ref_hash: str = content.attachment.hash.decode()  # type: ignore
            if url.startswith("drs://"):
                drs_object: DrsObject = get_drs_object(
                    drs_url=url, expected_hash=doc_ref_hash, client=self
                )
                drs_object.download_data(
                    output=output,
                    force_overwrite=force_overwrite,
                    expected_hash=doc_ref_hash,
                    client=self,
                )
                return
        raise CGPClientException("Could not find DRS URL in DocumentReference")

    @typing.no_type_check
    def download_file(
        self,
        document_reference_id: str | None = None,
        output: Path | None = None,
        force_overwrite: bool = False,
    ) -> None:
        """Download the specified file"""
        document_reference: DocumentReference

        if document_reference_id is not None:
            # just use the given DocRef ID
            document_reference = get_resource(
                resource_id=document_reference_id,
                client=self,
            )
        else:
            # search for a matching file
            bundle: Bundle = search_for_document_references(
                client=self,
            )
            if bundle.entry:
                if len(bundle.entry) == 1:
                    document_reference = bundle.entry[0].resource
                else:
                    raise CGPClientException(
                        f"Found {len(bundle.entry)} matching files, please refine search"
                    )
            else:
                raise CGPClientException("Could not find matching file")

        logging.debug(document_reference.json(exclude_none=True))

        self.download_data_from_drs_document_reference(
            document_reference=document_reference,
            output=output,
            force_overwrite=force_overwrite,
        )

    @typing.no_type_check
    def list_files(
        self, include_drs_access_urls: bool = False, mime_type: str | None = None
    ) -> list[CGPFile]:
        bundle: Bundle = search_for_document_references(
            client=self,
        )

        result: list[CGPFile] = []

        if bundle.entry:
            logging.info("Found %i matching files in FHIR server", len(bundle.entry))
            for entry in bundle.entry:
                details: dict = {}

                document_reference: DocumentReference = entry.resource

                logging.debug(document_reference.json(exclude_none=True))

                details["last_updated"] = document_reference.meta.lastUpdated.strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )

                details["document_reference_id"] = (
                    f"{DocumentReference.__name__}/{document_reference.id}"
                )

                details["participant_id"] = document_reference.subject.identifier.value

                if document_reference.author and len(document_reference.author) == 1:
                    details["author_ods_code"] = document_reference.author[
                        0
                    ].identifier.value
                else:
                    raise CGPClientException("Unexpected number of authors")

                if (
                    document_reference.context
                    and document_reference.context.related
                    and len(document_reference.context.related) > 0
                ):
                    for related in document_reference.context.related:
                        if related.type == ServiceRequest.__name__:
                            details["referral_id"] = related.identifier.value
                        elif related.type == Procedure.__name__:
                            details["run_id"] = related.identifier.value
                        elif related.type == Specimen.__name__:
                            details["sample_id"] = related.identifier.value

                if document_reference.content and len(document_reference.content) == 1:
                    attachment: dict = document_reference.content[0].attachment
                    details["name"] = attachment.title
                    details["content_type"] = attachment.contentType
                    details["hash"] = attachment.hash.decode()
                    details["size"] = attachment.size
                    details["drs_url"] = attachment.url

                    if (
                        mime_type is not None
                        and mime_type not in attachment.contentType
                    ):
                        # filter to specified MIME type
                        logging.debug(
                            "Skipping file which doesn't match MIME type %s, %s",
                            mime_type,
                            attachment.contentType,
                        )
                        continue

                    if include_drs_access_urls:
                        drs_object: DrsObject = get_drs_object(
                            drs_url=attachment.url,
                            client=self,
                            expected_hash=details["hash"],
                        )

                        for access_method in drs_object.access_methods:
                            details[f"{access_method.type}_url"] = (
                                access_method.access_url.url
                            )

                else:
                    raise CGPClientException("Unexpected number of attachments")

                try:
                    result.append(CGPFile(**details))
                except TypeError as e:
                    logging.debug(document_reference.json(exclude_none=True))
                    raise CGPClientException("Invalid DocumentReference") from e

        logging.info("Found %i matching files after all filters", len(result))
        return result

    def upload_files_with_drs(
        self,
        filename: Path,
    ) -> list[DrsObject]:
        """Upload a file using the DRS upload protocol"""
        return upload_files_with_drs(
            filenames=[filename],
            client=self,
        )

    def upload_files(self, filenames: list[Path]) -> None:
        """Upload the files using the DRS upload protocol"""
        upload_files(filenames=filenames, client=self)

    def upload_dragen_run(
        self,
        fastq_list_csv: Path,
        run_info_file: Path | None = None,
    ) -> None:
        """Read a DRAGEN format fastq_list.csv and upload the data to the CGP,
        associating the sample with the specified NGIS participant and referral IDs"""
        upload_dragen_run(
            fastq_list_csv=fastq_list_csv,
            run_info_file=run_info_file,
            client=self,
        )
