from __future__ import annotations

import logging
import uuid
from pathlib import Path
from time import time

import jwt
import requests  # type: ignore
from pydantic import BaseModel

from cgpclient.dragen import upload_sample_from_fastq_list
from cgpclient.drs import DrsObject, get_access_url
from cgpclient.drsupload import upload_file_with_drs
from cgpclient.fhir import (  # type: ignore
    CGPServiceRequest,
    Patient,
    PedigreeRole,
    get_patient,
    get_service_request,
)
from cgpclient.utils import APIM_BASE_URL, REQUEST_TIMEOUT_SECS, CGPClientException


class GenomicFile(BaseModel):
    ngis_referral_id: str
    ngis_participant_id: str
    pedigree_role: PedigreeRole
    ngis_document_category: str
    htsget_url: str | None = None


class GenomicFiles(BaseModel):
    files: list[GenomicFile]


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
    ):
        self.api_key = api_key
        self.api_host = api_host
        self.api_name = api_name
        self.private_key_pem = private_key_pem
        self.apim_kid = apim_kid
        self.override_api_base_url = override_api_base_url

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

    def get_service_request(self, ngis_referral_id: str) -> CGPServiceRequest:
        """Fetch a FHIR ServiceRequest resource for the given NGIS referral ID"""
        return get_service_request(
            ngis_referral_id=ngis_referral_id,
            api_base_url=self.api_base_url,
            headers=self.headers,
        )

    def get_patient(self, ngis_participant_id: str) -> Patient:
        """Fetch a FHIR Patient resource for the given NGIS participant ID"""
        return get_patient(
            ngis_participant_id=ngis_participant_id,
            api_base_url=self.api_base_url,
            headers=self.headers,
        )

    def get_genomic_files(self, ngis_referral_id: str) -> GenomicFiles:
        """Retrieve details of genomic files associated with an NGIS referral ID"""
        service_request: CGPServiceRequest = self.get_service_request(ngis_referral_id)
        pedigree_roles: dict[str, PedigreeRole] = service_request.get_pedigree_roles(
            api_base_url=self.api_base_url, headers=self.headers
        )
        files: list[GenomicFile] = []
        for doc_ref in service_request.document_references(
            api_base_url=self.api_base_url, headers=self.headers
        ):
            files.append(
                GenomicFile(
                    ngis_referral_id=ngis_referral_id,
                    ngis_participant_id=doc_ref.ngis_participant_id(),
                    ngis_document_category=",".join(
                        doc_ref.ngis_document_category_codes()
                    ),
                    htsget_url=get_access_url(
                        doc_ref.url(),
                        access_type="htsget",
                        headers=self.headers,
                        api_base_url_override=(
                            self.api_base_url if self.override_api_base_url else None
                        ),
                    ),
                    pedigree_role=pedigree_roles[doc_ref.ngis_participant_id()],
                )
            )

        return GenomicFiles(files=files)

    def upload_file_with_drs(
        self, filename: Path, mime_type: str | None = None, dry_run: bool = False
    ) -> DrsObject:
        """Upload a file using the DRS upload protocol"""
        return upload_file_with_drs(
            filename=filename,
            mime_type=mime_type,
            api_base_url=self.api_base_url,
            headers=self.headers,
            dry_run=dry_run,
        )

    def upload_dragen_fastq_list(
        self,
        fastq_list_csv: Path,
        ngis_participant_id: str,
        ngis_referral_id: str,
        run_id: str,
        ods_code: str,
        tumour_id: str | None = None,
        fastq_list_sample_id: str | None = None,
        run_info_file: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        """Read a DRAGEN format fastq_list.csv and upload the data to the CGP,
        associating the sample with the specified NGIS participant and referral IDs"""
        upload_sample_from_fastq_list(
            fastq_list_csv=fastq_list_csv,
            fastq_list_sample_id=fastq_list_sample_id,
            ngis_participant_id=ngis_participant_id,
            ngis_referral_id=ngis_referral_id,
            run_id=run_id,
            run_info_file=run_info_file,
            tumour_id=tumour_id,
            ods_code=ods_code,
            dry_run=dry_run,
            api_base_url=self.api_base_url,
            headers=self.headers,
        )
