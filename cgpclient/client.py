# pylint: disable=not-an-iterable,unsubscriptable-object
from __future__ import annotations

import logging
import typing
import uuid
from functools import cache
from pathlib import Path
from time import time

import jwt
import requests  # type: ignore
from fhir.resources.R4B.attachment import Attachment
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.relatedperson import RelatedPerson
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen
from pydantic import BaseModel
from tabulate import tabulate  # type: ignore

from cgpclient.dragen import upload_dragen_run
from cgpclient.drs import DrsObject, get_drs_object, map_https_to_drs_url
from cgpclient.drsupload import upload_files_with_drs
from cgpclient.fhir import (  # type: ignore
    CGPServiceRequest,
    ClientConfig,
    PedigreeRole,
    get_patient,
    get_resource,
    get_service_request,
    search_for_document_references,
    search_for_fhir_resource,
    search_for_service_requests,
    upload_files,
)
from cgpclient.utils import (
    APIM_BASE_URL,
    REQUEST_TIMEOUT_SECS,
    CGPClientException,
    create_uuid,
)

log = logging.getLogger(__name__)


class CGPFile:
    _document_reference: DocumentReference
    _drs_object: DrsObject
    _client: CGPClient
    _referral: CGPReferral

    @typing.no_type_check
    def __init__(
        self,
        document_reference: DocumentReference,
        client: CGPClient,
    ) -> None:
        self._document_reference = document_reference
        self._client = client
        self._drs_object = None
        self._referral = None

    @property
    def drs_object(self) -> DrsObject:
        if self._drs_object is None:
            # cache the DRS object so we don't fetch it multiple times
            self._drs_object = get_drs_object(
                drs_url=self.drs_url,
                expected_hash=self.hash,
                client=self._client,
            )

        return self._drs_object

    def _get_access_url(self, access_method_type: str) -> str | None:
        for access_method in self.drs_object.access_methods:
            if access_method.type == access_method_type:
                if access_method.access_url is not None:
                    return access_method.access_url.url
        return None

    @property
    def htsget_url(self) -> str | None:
        return self._get_access_url(access_method_type="htsget")

    @property
    def s3_url(self) -> str | None:
        return self._get_access_url(access_method_type="s3")

    @property
    @typing.no_type_check
    def related(self) -> list[Reference]:
        if (
            self._document_reference.context
            and self._document_reference.context.related
        ):
            return self._document_reference.context.related
        return []

    @typing.no_type_check
    def _get_related_id(self, resource_type: str) -> str | None:
        for related in self.related:
            if related.identifier:
                if related.type == resource_type or (
                    related.reference and related.reference.startswith(resource_type)
                ):
                    return related.identifier.value
        return None

    @property
    def referral_id(self) -> str | None:
        return self._get_related_id(resource_type=ServiceRequest.__name__)

    @property
    def run_id(self) -> str | None:
        return self._get_related_id(resource_type=Procedure.__name__)

    @property
    def sample_id(self) -> str | None:
        return self._get_related_id(resource_type=Specimen.__name__)

    @property
    @typing.no_type_check
    def attachment(self) -> Attachment:
        if not (
            self._document_reference.content
            and len(self._document_reference.content) == 1
        ):
            raise CGPClientException("Unexpected number of attachments")
        return self._document_reference.content[0].attachment

    @property
    def drs_url(self) -> str:
        if not self.attachment.url:
            raise CGPClientException("No URL for DocumentReference Attachment")
        if self.attachment.url.startswith("drs://"):
            return self.attachment.url
        if self.attachment.url.startswith("https://"):
            return map_https_to_drs_url(self.attachment.url)

        raise CGPClientException("No DRS URL for DocumentReference")

    @property
    def name(self) -> str | None:
        return self.attachment.title

    @property
    def content_type(self) -> str | None:
        return self.attachment.contentType

    @property
    def hash(self) -> str | None:
        if self.attachment.hash:
            return self.attachment.hash.decode()
        return None

    @property
    def size(self) -> int | None:
        return self.attachment.size

    @property
    def document_reference_id(self) -> str:
        return f"{DocumentReference.__name__}/{self._document_reference.id}"

    @property
    @typing.no_type_check
    def last_updated(self) -> str | None:
        if self._document_reference.meta and self._document_reference.meta.lastUpdated:
            return self._document_reference.meta.lastUpdated.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        return None

    @property
    @typing.no_type_check
    def participant_id(self) -> str:
        if not (
            self._document_reference.subject
            and self._document_reference.subject.identifier
        ):
            raise CGPClientException("No subject for DocumentReference")
        return self._document_reference.subject.identifier.value

    @property
    @typing.no_type_check
    def participant_role(self) -> str:
        if self._referral is None:
            if self.referral_id is None:
                raise CGPClientException("Need a referral ID")

            self._referral = CGPReferral.get(
                referral_id=self.referral_id, client=self._client
            )

        return self._referral.pedigree_role(self.participant_id)

    @property
    @typing.no_type_check
    def author_ods_code(self) -> str:
        if not (
            self._document_reference.author
            and len(self._document_reference.author) == 1
            and self._document_reference.author[0].identifier
        ):
            raise CGPClientException("Unexpected number of authors")
        return self._document_reference.author[0].identifier.value

    def download_data(
        self,
        output: Path | None = None,
        force_overwrite: bool = False,
    ) -> None:
        """Download the DRS object data attached to the DocumentReference"""
        self._drs_object.download_data(
            output=output,
            force_overwrite=force_overwrite,
            expected_hash=self.hash,
            client=self._client,
        )


class CGPFiles:
    def __init__(self, document_references: list[DocumentReference], client: CGPClient):
        self._files = [
            CGPFile(document_reference=doc_ref, client=client)
            for doc_ref in document_references
        ]

    @classmethod
    def search(cls, client: CGPClient) -> CGPFiles:
        return CGPFiles(
            document_references=search_for_document_references(
                client=client, search_params=client.config
            ),
            client=client,
        )

    def __len__(self) -> int:
        return len(self._files)

    def __getitem__(self, index: int) -> CGPFile:
        return self._files[index]

    def print_table(
        self,
        summary: bool = False,
        include_drs_access_urls: bool = False,
        sort_by: str | None = None,
        table_format: str = "plain",
        pivot: bool = False,
        mime_type: str | None = None,
        include_header: bool = True,
    ) -> None:
        """Print the list of files as a table"""

        files: list[CGPFile] = self._files

        if mime_type is not None:
            files = [f for f in files if f.content_type and mime_type in f.content_type]

        if sort_by is not None:
            files.sort(key=lambda f: getattr(f, sort_by))

        # columns to include for summary output
        short_cols: list[str] = [
            "last_updated",
            "content_type",
            "size",
            "author_ods_code",
            "referral_id",
            "participant_id",
            "participant_role",
            "sample_id",
            "run_id",
            "name",
        ]

        # additional columns (rather verbose)
        all_cols: list[str] = short_cols + ["document_reference_id", "drs_url", "hash"]

        cols = short_cols if summary else all_cols

        if include_drs_access_urls:
            cols.extend(["s3_url", "htsget_url"])

        rows: list[list[str]] = [[getattr(f, c) for c in cols] for f in files]

        if pivot:
            # print each row as its own table
            for row in rows:
                print(
                    tabulate(
                        zip(cols, row),
                        headers=["file property", "value"],
                        tablefmt=table_format,
                    ),
                    end="\n\n",
                )

        else:
            print(
                tabulate(
                    rows,
                    headers=cols if include_header else (),
                    tablefmt=table_format,
                )
            )


class CGPSample:
    def __init__(self, specimen: Specimen):
        self._specimen = specimen


class CGPSamples:
    def __init__(self, specimens: list[Specimen]):
        self._samples = [CGPSample(s) for s in specimens]

    def __len__(self) -> int:
        return len(self._samples)


class CGPRun:
    def __init__(self, procedure: Procedure):
        self._procedure = procedure


class CGPRuns:
    def __init__(self, procedures: list[Procedure]):
        self._runs = [CGPRun(r) for r in procedures]

    def __len__(self) -> int:
        return len(self._runs)


class CGPParticipant:
    def __init__(self, patient: Patient):
        self._patient = patient


class CGPParticipants:
    def __init__(self, patients: list[Patient]):
        self._participants = [CGPParticipant(p) for p in patients]

    def __len__(self) -> int:
        return len(self._participants)


class CGPReferral:
    def __init__(self, service_request: ServiceRequest, client: CGPClient):
        self._service_request = service_request
        self._client = client
        self._pedigree = None

    @classmethod
    @cache
    def get(cls, referral_id: str, client: CGPClient) -> CGPReferral:
        referrals: CGPReferrals = CGPReferrals.search(
            search_params=ClientConfig(referral_id=referral_id), client=client
        )
        if len(referrals) != 0:
            log.info(CGPClientException("Expected a single matching Referral"))

        return referrals[0]

    @typing.no_type_check
    def _get_identifier(self, system: str) -> str | None:
        if (
            self._service_request.identifier
            and len(self._service_request.identifier) > 0
        ):
            for identifier in self._service_request.identifier:
                if identifier.system == system:
                    return identifier.value
        return None

    @property
    def referral_id(self) -> str:
        referral_id: str | None = self._get_identifier(
            system="https://genomicsengland.co.uk/ngis-referral-id"
        )
        if referral_id is None:
            raise CGPClientException("ServiceRequest with no referral ID")
        return referral_id

    @property
    @typing.no_type_check
    def proband_participant_id(self) -> str:
        if self._service_request.subject and self._service_request.subject.identifier:
            return self._service_request.subject.identifier.value
        raise CGPClientException("Can't find ServiceRequest subject")

    @property
    @typing.no_type_check
    def pedigree(self) -> dict[str, str]:
        if self._pedigree is None:
            self._pedigree = {self.proband_participant_id: PedigreeRole.PROBAND}

            bundle: Bundle = search_for_fhir_resource(
                resource_type=RelatedPerson.get_resource_type(),
                query_params={"patient": self.proband_participant_id},
                client=self._client,
            )

            if bundle.entry is not None:
                for entry in bundle.entry:
                    relative: RelatedPerson = RelatedPerson.parse_obj(
                        entry.resource.dict()
                    )

                    self._pedigree[relative.identifier[0].value] = PedigreeRole(
                        relative.relationship[0].coding[0].display
                    )

        return self._pedigree

    def pedigree_role(self, participant_id: str) -> str:
        if participant_id == self.proband_participant_id:
            # we can avoid doing a lookup for the proband
            return PedigreeRole.PROBAND
        if participant_id not in self.pedigree:
            raise CGPClientException("Can't find pedigree role")
        return self.pedigree[participant_id]


class CGPReferrals:
    def __init__(self, service_requests: list[ServiceRequest], client: CGPClient):
        self._referrals = [CGPReferral(s, client=client) for s in service_requests]
        self._client = client

    def __len__(self) -> int:
        return len(self._referrals)

    def __getitem__(self, index: int) -> CGPReferral:
        return self._referrals[index]

    @classmethod
    def search(
        cls, client: CGPClient, search_params: ClientConfig | None = None
    ) -> CGPReferrals:
        serv_reqs: list[ServiceRequest] = search_for_service_requests(
            client=client, search_params=search_params
        )

        return CGPReferrals(service_requests=serv_reqs, client=client)


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
        api_key: str | None = None,
        api_name: str | None = None,
        private_key_pem: Path | None = None,
        apim_kid: str | None = None,
        override_api_base_url: bool = False,
        dry_run: bool = False,
        output_dir: Path | None = None,
        config: ClientConfig | None = None,
    ):
        self.api_key = api_key
        self.api_host = api_host
        self.api_name = api_name
        self.private_key_pem = private_key_pem
        self.apim_kid = apim_kid
        self.override_api_base_url = override_api_base_url
        self.dry_run = dry_run
        self.output_dir = output_dir
        self.config = ClientConfig() if config is None else config

        self._oauth_token: NHSOAuthToken | None = None
        self._using_sandbox_env = self.api_host.startswith("sandbox.")

        if self.output_dir is not None:
            self.output_dir = self.output_dir / Path(create_uuid())
            self.output_dir.mkdir(parents=True, exist_ok=True)
            log.info("Created output directory: %s", self.output_dir)

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

        log.debug(
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
        log.info("Requesting OAuth token from: %s", self.oauth_endpoint)
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
            log.info("Got successful response from OAuth server")
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
            log.info("Requesting new OAuth token")
            self._oauth_token = self.request_access_token()

        return self._oauth_token

    def get_access_token(self) -> str | None:
        """Get the current OAuth access token value"""
        if self._using_sandbox_env:
            log.info("No access token required in sandbox environment")
            return None

        return self.get_oauth_token().access_token

    @property
    def headers(self) -> dict[str, str]:
        """Fetch the HTTP headers necessary to interact with NHS APIM"""

        if self._using_sandbox_env:
            log.debug("Skipping authentication for sandbox environment")
            return {}

        if self.private_key_pem is not None:
            # use OAuth if we're given a private key
            log.debug("Using signed JWT authentication")
            return {"Authorization": f"Bearer {self.get_access_token()}"}

        if self.api_key is not None:
            # use the supplied API key
            log.debug("Using API key authentication")
            if APIM_BASE_URL in self.api_host:
                # use APIM header
                log.debug("Using APIM API key header")
                return {"apikey": self.api_key}

            # otherwise use standard header
            log.debug("Using standard API key header")
            return {"X-API-Key": self.api_key}

        # no auth by default
        log.debug("No API authentication")
        return {}

    def get_service_request(self, referral_id: str) -> CGPServiceRequest:
        """Fetch a FHIR ServiceRequest resource for the given NGIS referral ID"""
        return get_service_request(referral_id=referral_id, client=self)

    def get_patient(self, participant_id: str) -> Patient:
        """Fetch a FHIR Patient resource for the given NGIS participant ID"""
        return get_patient(participant_id=participant_id, client=self)

    @typing.no_type_check
    def download_file(
        self,
        document_reference_id: str | None = None,
        output: Path | None = None,
        force_overwrite: bool = False,
    ) -> None:
        """Download the specified file"""
        matches: CGPFiles

        if document_reference_id is not None:
            # just use the given DocRef ID
            matches = CGPFiles(
                document_references=[
                    get_resource(
                        resource_id=document_reference_id,
                        client=self,
                    )
                ],
                client=self,
            )
        else:
            # search for matching files
            matches = CGPFiles(
                document_references=search_for_document_references(
                    client=self, search_params=self.config
                ),
                client=self,
            )

        if len(matches) == 0:
            raise CGPClientException("Could not find matching file(s)")
        if len(matches) == 1:
            matches[0].download_data(output=output, force_overwrite=force_overwrite)
        else:
            # TODO: Download all matching files
            raise CGPClientException(
                f"Found {len(matches)} matching files, please refine search"
            )

    def get_referrals(self) -> CGPReferrals:
        return CGPReferrals(
            service_requests=search_for_service_requests(client=self), client=self
        )

    def get_files(self) -> CGPFiles:
        return CGPFiles.search(client=self)

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
