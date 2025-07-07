# pylint: disable=not-an-iterable,unsubscriptable-object
from __future__ import annotations

import logging
import typing
from dataclasses import dataclass
from pathlib import Path

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen
from tabulate import tabulate  # type: ignore

from cgpclient.auth import AuthProvider, create_auth_provider
from cgpclient.dragen import upload_dragen_run
from cgpclient.drs import DrsObject, get_drs_object
from cgpclient.drsupload import upload_files_with_drs
from cgpclient.fhir import CGPFHIRService, CGPServiceRequest, FHIRConfig  # type: ignore
from cgpclient.utils import CGPClientException, create_uuid


@dataclass
class CGPFile:
    document_reference_id: str
    participant_id: str
    author_ods_code: str
    name: str
    size: int
    drs_url: str
    content_type: str
    last_updated: str
    hash: str | None = None
    sample_id: str | None = None
    run_id: str | None = None
    referral_id: str | None = None
    s3_url: str | None = None
    htsget_url: str | None = None


@dataclass
class CGPFiles:
    files: list[CGPFile]

    def print_table(
        self,
        summary: bool = False,
        include_drs_access_urls: bool = False,
        sort_by: str = "name",
        table_format: str = "simple",
    ) -> None:
        """Print the list of files as a table"""
        self.files.sort(key=lambda f: getattr(f, sort_by))

        # columns to include for summary output
        short_cols: list[str] = [
            "name",
            "size",
            "content_type",
            "last_updated",
            "author_ods_code",
            "referral_id",
            "participant_id",
            "sample_id",
            "run_id",
        ]

        # additional columns (rather verbose)
        all_cols: list[str] = short_cols + ["document_reference_id", "drs_url", "hash"]

        cols = short_cols if summary else all_cols

        if include_drs_access_urls:
            cols.extend(["s3_url", "htsget_url"])

        print(
            tabulate(
                [[getattr(f, c) for c in cols] for f in self.files],
                headers=cols,
                tablefmt=table_format,
            )
        )


@dataclass
class CGPSample:
    sample_id: str


@dataclass
class CGPSamples:
    referrals: list[CGPSample]


@dataclass
class CGPRun:
    run_id: str
    files: list[CGPFile]


@dataclass
class CGPRuns:
    referrals: CGPReferrals
    files: CGPFiles
    samples: CGPSamples


@dataclass
class CGPParticipant:
    participant_id: str
    files: CGPFiles
    referrals: CGPReferrals
    samples: CGPSamples


@dataclass
class CGPParticipants:
    referrals: list[CGPParticipant]


@dataclass
class CGPReferral:
    referral_id: str
    proband_id: str
    pedigree: str
    files: list[CGPFile]
    participants: list[CGPParticipant]
    runs: list[CGPRun]
    samples: list[CGPSample]


@dataclass
class CGPReferrals:
    referrals: list[CGPReferral]


class CGPClient:
    """A client for interacting with Clinical Genomics Platform
    APIs in the NHS APIM"""

    def __init__(
        self,
        api_host: str,
        auth_provider: AuthProvider | None = None,
        api_key: str | None = None,
        api_name: str | None = None,
        private_key_pem: Path | None = None,
        apim_kid: str | None = None,
        override_api_base_url: bool = False,
        dry_run: bool = False,
        output_dir: Path | None = None,
        fhir_config: FHIRConfig | None = None,
    ):
        self.api_host = api_host
        self.api_name = api_name
        self.override_api_base_url = override_api_base_url
        self.dry_run = dry_run
        self.output_dir = output_dir
        self.fhir_config = FHIRConfig() if fhir_config is None else fhir_config

        # Use provided auth provider or create one from legacy parameters
        self.auth_provider = auth_provider or create_auth_provider(
            api_host=api_host,
            api_key=api_key,
            private_key_pem=private_key_pem,
            apim_kid=apim_kid,
        )

        if self.output_dir is not None:
            self.output_dir = self.output_dir / Path(create_uuid())
            self.output_dir.mkdir(parents=True, exist_ok=True)
            logging.info("Created output directory: %s", self.output_dir)

        # Initialize a fhir service
        self.fhir_service = CGPFHIRService(
            api_base_url=self.api_base_url,
            headers=self.headers,
            config=self.fhir_config,
            dry_run=self.dry_run,
            output_dir=self.output_dir,
        )

    # API
    @property
    def api_base_url(self) -> str:
        """Return the base URL for the overall API"""
        if self.api_name is not None:
            # in APIM the base URL is host + API name
            return f"{self.api_host}/{self.api_name}"
        return self.api_host

    @property
    def headers(self) -> dict[str, str]:
        """Fetch the HTTP headers necessary to interact with NHS APIM"""
        return self.auth_provider.get_headers(self.api_host)

    # FHIR Service delegation
    def get_service_request(self, referral_id: str) -> CGPServiceRequest:
        """Fetch a FHIR ServiceRequest resource for the given NGIS referral ID"""
        return self.fhir_service.get_service_request(referral_id=referral_id)

    def get_patient(self, participant_id: str) -> Patient:
        """Fetch a FHIR Patient resource for the given NGIS participant ID"""
        return self.fhir_service.get_patient(participant_id=participant_id)

    # DRS
    def download_data_from_drs_document_reference(
        self,
        document_reference: DocumentReference,
        output: Path | None = None,
        force_overwrite: bool = False,
    ) -> None:
        """Download the DRS object data attached to the DocumentReference"""
        for content in document_reference.content:
            url: str = content.attachment.url  # type: ignore
            doc_ref_hash: str | None = None
            if content.attachment.hash is not None:  # type: ignore
                doc_ref_hash = content.attachment.hash.decode()  # type: ignore
            if url.startswith("drs://"):
                drs_object: DrsObject = get_drs_object(
                    drs_url=url,
                    expected_hash=doc_ref_hash,
                    api_base_url=self.api_base_url,
                    override_api_base_url=self.override_api_base_url,
                    headers=self.headers,
                )
                drs_object.download_data(
                    output=output,
                    force_overwrite=force_overwrite,
                    expected_hash=doc_ref_hash,
                    api_base_url=self.api_base_url,
                    headers=self.headers,
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
            document_reference = self.fhir_serviceget_resource(
                resource_id=document_reference_id
            )
        else:
            # search for a matching file
            bundle: Bundle = self.fhir_service.search_for_document_references()
            if bundle.entry:
                if len(bundle.entry) == 1:
                    document_reference = bundle.entry[0].resource
                else:
                    raise CGPClientException(
                        f"Found {len(bundle.entry)} matching files,  refine search"
                    )
            else:
                raise CGPClientException("Could not find matching file")

        logging.debug(document_reference.json(exclude_none=True))

        self.download_data_from_drs_document_reference(
            document_reference=document_reference,
            output=output,
            force_overwrite=force_overwrite,
        )

    def list_referrals(self) -> CGPReferrals:
        return []

    @typing.no_type_check
    def list_files(
        self, include_drs_access_urls: bool = False, mime_type: str | None = None
    ) -> CGPFiles:
        bundle: Bundle = self.fhir_service.search_for_document_references()

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
                    if attachment.hash is not None:
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
        return CGPFiles(files=result)

    def upload_files_with_drs(
        self,
        filename: Path,
    ) -> list[DrsObject]:
        """Upload a file using the DRS upload protocol"""
        return upload_files_with_drs(
            filenames=[filename],
            headers=self.headers,
            api_base_url=self.api_base_url,
            dry_run=self.dry_run,
            output_dir=self.output_dir,
        )

    def upload_files(self, filenames: list[Path]) -> None:
        """Upload the files using the DRS upload protocol"""
        self.fhir_service.upload_files(filenames=filenames)

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
            fhir_service=self.fhir_service,
        )
