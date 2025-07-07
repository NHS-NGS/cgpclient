# type: ignore
# we ignore type checking here because of incompatibilities with fhir.resources
# pylint: disable=unsubscriptable-object,not-an-iterable
from __future__ import annotations

import logging
import typing
from pathlib import Path

try:
    from enum import StrEnum
except ImportError:
    from backports.strenum import StrEnum

import requests
from fhir.resources.R4B import construct_fhir_element
from fhir.resources.R4B.attachment import Attachment
from fhir.resources.R4B.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.composition import Composition, CompositionSection
from fhir.resources.R4B.device import Device, DeviceDeviceName, DeviceVersion
from fhir.resources.R4B.documentreference import (
    DocumentReference,
    DocumentReferenceContent,
    DocumentReferenceContext,
)
from fhir.resources.R4B.domainresource import DomainResource
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.meta import Meta
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.provenance import Provenance, ProvenanceAgent
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen

import cgpclient
from cgpclient.drs import DrsObject
from cgpclient.drsupload import upload_files_with_drs
from cgpclient.utils import (
    REQUEST_TIMEOUT_SECS,
    CGPClientException,
    create_uuid,
    get_current_datetime,
)

log = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 100
MAX_UNSIGNED_INT = 2147483647  # https://hl7.org/fhir/R4/datatypes.html#unsignedInt


class ProcedureStatus(StrEnum):
    PREPARATION = "preparation"
    IN_PROGRESS = "in-progress"
    NOT_DONE = "not-done"
    ON_HOLD = "on-hold"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ENTERED_IN_ERROR = "entered-in-error"
    UNKNOWN = "unknown"


class SpecimenStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSATISFACTORY = "unsatisfactory"
    ENTERED_IN_ERROR = "entered-in-error"


class DocumentReferenceStatus(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    ENTERED_IN_ERROR = "entered-in-error"


class DocumentReferenceDocStatus(StrEnum):
    PRELIMINARY = "preliminary"
    FINAL = "final"
    AMENDED = "amended"
    ENTERED_IN_ERROR = "entered-in-error"


class PedigreeRole(StrEnum):
    PROBAND = "proband"
    MOTHER = "mother"
    FATHER = "father"
    SIBLING = "sibling"
    HALF_SIBLING = "half-sibling"
    FAMILY_MEMBER = "family member"


class BundleType(StrEnum):
    DOCUMENT = "document"
    MESSAGE = "message"
    TRANSACTION = "transaction"
    TRANSACTION_RESPONSE = "transaction-response"
    BATCH = "batch"
    BATCH_RESPONSE = "batch-response"
    HISTORY = "history"
    SEARCH_SET = "searchset"
    COLLECTION = "collection"


class BundleRequestMethod(StrEnum):
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class DocumentReferenceRelationship(StrEnum):
    APPENDS = "appends"
    TRANSFORMS = "transforms"
    REPLACES = "replaces"
    SIGNS = "signs"


class CompositionStatus(StrEnum):
    PRELIMINARY = "preliminary"
    FINAL = "final"
    AMENDED = "amended"
    ENTERED_IN_ERROR = "entered-in-error"


CGPClientDevice: Device = Device(
    id=create_uuid(),
    version=[DeviceVersion(value=cgpclient.__version__)],
    deviceName=[DeviceDeviceName(name="cgpclient", type="manufacturer-name")],
)


class CGPFHIRService:
    """Service class for FHIR operations, encapsulating client and config"""

    def __init__(
        self,
        api_base_url: str,
        headers: dict,
        config: FHIRConfig,
        dry_run: bool,
        output_dir: Path | None = None,
    ):
        self.api_base_url = api_base_url
        self.headers = headers
        self.config = config
        self.dry_run = dry_run
        self.output_dir = output_dir

    @property
    def base_url(self) -> str:
        return fhir_base_url(self.api_base_url)

    def get_resource(
        self,
        resource_id: str,
        resource_type: str | None = None,
        params: dict[str, str] | None = None,
    ) -> DomainResource:
        """Fetch a FHIR resource from the FHIR server"""
        if resource_type is None:
            if "/" in resource_id:
                resource_type, resource_id = resource_id.split("/")
            raise CGPClientException("Need explicit resource type")

        url = f"{self.base_url}/{resource_type}/{resource_id}"
        logging.info("Requesting endpoint: %s", url)
        response = requests.get(
            url=url,
            headers=self.headers,
            params=params,
            timeout=REQUEST_TIMEOUT_SECS,
        )
        if response.ok:
            return construct_fhir_element(resource_type, response.json())

        raise CGPClientException(
            f"Failed to fetch from endpoint: {url} "
            f"status: {response.status_code} response: {response.text}"
        )

    def search_for_fhir_resource(
        self,
        resource_type: str,
        query_params: dict[str, str] | None = None,
    ) -> Bundle:
        """Search for a FHIR resource using the query parameters"""
        url = f"{self.base_url}/{resource_type}"

        if query_params is None:
            query_params = {}

        query_params["_count"] = str(MAX_SEARCH_RESULTS)

        if self.config.workspace_id is not None:
            query_params["_tag"] = self.config.workspace_id

        logging.info("Requesting endpoint: %s", url)
        logging.info("Query parameters: %s", query_params)

        response = requests.get(
            url=url,
            headers=self.headers,
            params=query_params,
            timeout=REQUEST_TIMEOUT_SECS,
        )
        if response.ok:
            logging.debug(response.json())
            bundle = Bundle.parse_obj(response.json())
            if (
                bundle.link
                and len(bundle.link) == 1
                and bundle.link[0].relation == "next"
            ):
                url = bundle.link[0].url
                logging.info(
                    "More than %i results for search, implement paging!",
                    MAX_SEARCH_RESULTS,
                )
            return bundle

        logging.error(
            "Failed to fetch from endpoint: %s status: %i response: %s",
            url,
            response.status_code,
            response.text,
        )
        raise CGPClientException(
            f"Error searching for resource, got status code: {response.status_code}"
        )

    def search_for_document_references(
        self, search_params: FHIRConfig | None = None
    ) -> list[DocumentReference]:
        query_params: dict[str, str] = {}

        if search_params is not None:
            if search_params.file_id is not None:
                query_params["identifier"] = identifier_search_string(
                    search_params.file_identifier()
                )

            if search_params.related_query_string is not None:
                query_params["related:identifier"] = search_params.related_query_string

            if search_params.participant_id is not None:
                query_params["subject:identifier"] = identifier_search_string(
                    search_params.participant_identifier
                )

            if search_params.ods_code is not None:
                query_params["author:identifier"] = identifier_search_string(
                    search_params.org_identifier
                )

        bundle: Bundle = self.search_for_fhir_resource(
            resource_type=DocumentReference.__name__,
            query_params=query_params,
        )

        if bundle.entry:
            return [entry.resource for entry in bundle.entry]
        return []

    def search_for_service_requests(
        self, search_params: FHIRConfig | None = None
    ) -> list[ServiceRequest]:
        query_params: dict[str, str] = {}

        if search_params is not None:
            if search_params.referral_id is not None:
                query_params["identifier"] = identifier_search_string(
                    search_params.referral_identifier
                )

            if search_params.participant_id is not None:
                query_params["subject:identifier"] = identifier_search_string(
                    search_params.participant_identifier
                )

        bundle: Bundle = self.search_for_fhir_resource(
            resource_type=ServiceRequest.__name__,
            query_params=query_params,
        )

        if bundle.entry:
            return [entry.resource for entry in bundle.entry]
        return []

    @typing.no_type_check
    def document_reference_for_drs_object(
        self, drs_object: DrsObject
    ) -> DocumentReference:
        """Create a DocumentReference resource corresponding to a DRS object"""
        return DocumentReference(
            id=create_uuid(),
            identifier=[self.config.file_identifier(drs_object.name)],
            status=DocumentReferenceStatus.CURRENT,
            docStatus=DocumentReferenceDocStatus.FINAL,
            author=[self.config.org_reference],
            subject=self.config.participant_reference,
            content=[
                DocumentReferenceContent(
                    attachment=Attachment(
                        url=drs_object.self_uri,
                        contentType=drs_object.mime_type,
                        title=drs_object.name,
                        # in FHIR R4 size is an unsignedInt:
                        # https://hl7.org/fhir/R4/datatypes.html#unsignedInt
                        size=min(drs_object.size, MAX_UNSIGNED_INT),
                        hash=drs_object.checksums[0].checksum,
                    )
                ),
            ],
            context=DocumentReferenceContext(related=self.config.related_references),
            meta=Meta(
                # as a work around to the size limit above, we include the real
                # file size as a string here as a meta tag
                tag=[
                    Coding(
                        system="https://genomicsengland.co.uk/workaround-attachment-size",
                        code=f"{drs_object.size}",
                        display="attachment size in bytes",
                    )
                ]
            ),
        )

    def create_drs_document_references(
        self, filenames: list[Path]
    ) -> list[DocumentReference]:
        """Upload the files using the DRS upload protocol and return a
        DocumentReference"""
        drs_objects: list[DrsObject] = upload_files_with_drs(
            filenames=filenames,
            headers=self.headers,
            api_base_url=self.api_base_url,
            dry_run=self.dry_run,
            output_dir=self.output_dir,
        )

        return [
            self.document_reference_for_drs_object(
                drs_object=o,
            )
            for o in drs_objects
        ]

    def upload_files(
        self,
        filenames: list[Path],
    ) -> None:
        """Upload the files using the DRS upload protocol and post
        DocumentReferences to the FHIR server"""

        document_references: list[DocumentReference] = (
            self.create_drs_document_references(
                filenames=filenames,
            )
        )

        self.post_fhir_resource(resource=bundle_for(document_references))

    def add_workspace_meta_tag(self, resource: DomainResource) -> None:
        """Add the workspace ID to the FHIR meta tags"""
        if self.config.workspace_id is not None:
            if resource.meta is None:
                resource.meta = Meta()

            if resource.meta.tag is None:
                resource.meta.tag = []

            logging.debug(
                "Adding workspace ID %s to resource meta tags",
                self.config.workspace_id,
            )
            resource.meta.tag.append(self.config.workspace_meta_tag)

    def add_workspace_meta_tag_to_bundle(self, bundle: Bundle) -> None:
        for entry in bundle.entry:
            self.add_workspace_meta_tag(resource=entry.resource)

    def post_fhir_resource(
        self,
        resource: DomainResource,
        params: dict[str, str] | None = None,
    ) -> None:
        """Post a FHIR resource to the FHIR server"""
        url: str = f"{fhir_base_url(self.api_base_url)}/{resource.resource_type}/"

        if resource.resource_type == Bundle.__name__ and resource.type in (
            BundleType.BATCH,
            BundleType.TRANSACTION,
        ):
            # these bundle types are posted to the root of the FHIR server
            logging.info("Posting bundle to the root FHIR endpoint")
            url = f"{fhir_base_url(self.api_base_url)}/"
            if self.config.org_reference is not None:
                resource = add_provenance_for_bundle(
                    bundle=resource, org_reference=self.config.org_reference
                )
            self.add_workspace_meta_tag_to_bundle(bundle=resource)
            logging.info("Posting bundle including %i entries", len(resource.entry))

        self.add_workspace_meta_tag(resource=resource)

        logging.info("Posting resource to endpoint: %s", url)

        if self.output_dir is not None:
            output_file: Path = self.output_dir / Path("fhir_resources.json")
            logging.info("Writing FHIR resource to %s", output_file)
            with open(output_file, "a", encoding="utf-8") as out:
                print(resource.json(exclude_none=True), file=out)

        if self.dry_run:
            logging.info("Dry run, so skipping posting resource")
            return

        response: requests.Response = requests.post(
            url=url,
            headers=self.headers,
            params=params,
            data=resource.json(exclude_none=True),
            timeout=REQUEST_TIMEOUT_SECS,
        )
        if response.ok:
            logging.info("Successfully posted FHIR resource")
        else:
            logging.error(
                "Failed to post resource to: %s status: %i response: %s",
                url,
                response.status_code,
                response.text,
            )

            raise CGPClientException(
                f"Error posting resource, got status code: {response.status_code}"
            )


def create_resource_from_dict(data: dict) -> DomainResource:
    return construct_fhir_element(data["resourceType"], data)


def reference_for(
    resource: DomainResource,
    include_first_identifier: bool = False,
    use_placeholder_id: bool = True,
    special_resource_types: frozenset[str] = frozenset(
        {"Patient", "Specimen", "ServiceRequest", "Procedure"}
    ),
) -> Reference:
    if use_placeholder_id:
        reference_value = f"urn:uuid:{resource.id}"
    else:
        reference_value = f"{resource.resource_type}/{resource.id}"
    reference: Reference = Reference(reference=reference_value)

    if resource.resource_type in special_resource_types:
        # we set this argument by default for these special resource types
        include_first_identifier = True

    if (
        include_first_identifier
        and resource.identifier is not None
        and len(resource.identifier) > 0
    ):
        reference.identifier = resource.identifier[0]
    return reference


def identifier_search_string(identifier: Identifier) -> str:
    return f"{identifier.system}|{identifier.value}"


def provenance_for(resource: DomainResource, org_reference: Reference) -> Provenance:
    log.info(
        "Creating Provenance resource for Organization %s for FHIR resource %s",
        org_reference.identifier.value,
        f"{resource.resource_type}/{resource.id}",
    )
    return Provenance(
        id=create_uuid(),
        target=[reference_for(resource)],
        recorded=get_current_datetime(),
        agent=[
            ProvenanceAgent(
                who=reference_for(CGPClientDevice),
                onBehalfOf=org_reference,
            )
        ],
    )


def fhir_base_url(api_base_url: str) -> str:
    """Return the base URL for the FHIR server"""
    return f"https://{api_base_url}/FHIR/R4"


def bundle_entry_for(
    resource: DomainResource, method: BundleRequestMethod = BundleRequestMethod.POST
) -> BundleEntry:
    """Create a BundleEntry for the resource, using the specified method"""
    return BundleEntry(
        fullUrl=f"urn:uuid:{resource.id}",
        resource=resource,
        request=BundleEntryRequest(method=method, url=resource.resource_type),
    )


def bundle_for(
    resources: list[DomainResource], bundle_type: BundleType = BundleType.TRANSACTION
) -> Bundle:
    """Create a FHIR Bundle including the list of resources"""
    return Bundle(
        type=bundle_type,
        entry=[bundle_entry_for(resource) for resource in resources],
    )


def add_provenance_for_bundle(bundle: Bundle, org_reference: Reference) -> Bundle:
    """Add Provenance resources for each of the resources in the Bundle"""

    # add the Device resource
    bundle.entry += [bundle_entry_for(CGPClientDevice)]

    provenance_resources: list[BundleEntry] = [
        bundle_entry_for(
            resource=provenance_for(entry.resource, org_reference=org_reference)
        )
        for entry in bundle.entry
    ]

    # include the original resources and the Provenance resources
    bundle.entry = bundle.entry + provenance_resources
    return bundle


@typing.no_type_check
def create_composition(
    specimen: Specimen,
    procedure: Procedure,
    document_references: list[DocumentReference],
    fhir_config: FHIRConfig,
) -> Composition:
    log.info("Creating Composition resource for delivery")
    return Composition(
        id=create_uuid(),
        status=CompositionStatus.FINAL,
        type=CodeableConcept(
            coding=[
                Coding(
                    system="http://loinc.org",
                    code="86206-0",
                    display="Whole genome sequence analysis",
                )
            ]
        ),
        date=get_current_datetime(),
        author=[fhir_config.org_reference],
        title="WGS sample run",
        section=[
            CompositionSection(title="sample", entry=[reference_for(specimen)]),
            CompositionSection(title="run", entry=[reference_for(procedure)]),
            CompositionSection(
                title="files",
                entry=[
                    reference_for(document_reference)
                    for document_reference in document_references
                ],
            ),
        ],
    )


class FHIRConfig:
    def __init__(
        self,
        participant_id: str | None = None,
        referral_id: str | None = None,
        ods_code: str | None = None,
        run_id: str | None = None,
        sample_id: str | None = None,
        tumour_id: str | None = None,
        file_id: str | None = None,
        workspace_id: str | None = None,
    ):
        self.participant_id = participant_id
        self.referral_id = referral_id
        self.run_id = run_id
        self.ods_code = ods_code
        self.sample_id = sample_id
        self.tumour_id = tumour_id
        self.file_id = file_id
        self.workspace_id = workspace_id

    @property
    def workspace_meta_tag(self) -> Coding:
        return Coding(
            system="https://genomicsengland.co.uk/workspace_id",
            code=self.workspace_id,
            display="workspace_id",
        )

    @property
    def workspace_identifier_string(self) -> str:
        return f"{self.workspace_meta_tag.system}|{self.workspace_id}"

    @property
    def related_references(self) -> list[Reference]:
        methods: list[str] = [
            "referral_reference",
            "sample_reference",
            "run_reference",
        ]

        related: list[Reference] = []

        for method in methods:
            try:
                related.append(getattr(self, method))
            except CGPClientException:
                # not supplied
                pass

        return related

    @property
    def related_query_string(self) -> str | None:
        methods: list[str] = [
            "referral_identifier",
            "sample_identifier",
            "run_identifier",
            "tumour_identifier",
        ]

        parameters: list[str] = []

        for method in methods:
            try:
                identifier: Identifier = getattr(self, method)
                parameters.append(identifier_search_string(identifier))
            except CGPClientException:
                # not supplied, so don't include
                pass

        if len(parameters) == 0:
            return None

        return ",".join(parameters)

    @property
    def participant_identifier(self) -> Identifier:
        if self.participant_id is None:
            raise CGPClientException("No participant ID supplied")
        return Identifier(
            system="https://genomicsengland.co.uk/ngis-participant-id",
            value=self.participant_id,
        )

    @property
    def participant_reference(self) -> Reference:
        return Reference(
            identifier=self.participant_identifier,
            type=Patient.__name__,
        )

    @property
    def referral_identifier(self) -> Identifier:
        if self.referral_id is None:
            raise CGPClientException("No referral ID supplied")
        return Identifier(
            system="https://genomicsengland.co.uk/ngis-referral-id",
            value=self.referral_id,
        )

    @property
    def referral_reference(self) -> Reference:
        return Reference(
            identifier=self.referral_identifier,
            type=ServiceRequest.__name__,
        )

    @property
    def sample_identifier(self) -> Identifier:
        if self.sample_id is None:
            raise CGPClientException("No sample ID supplied")
        return Identifier(
            system=f"https://{self.org_identifier.value}.nhs.uk/lab-sample-id",
            value=self.sample_id,
        )

    @property
    def sample_reference(self) -> Reference:
        return Reference(
            identifier=self.sample_identifier,
            type=Specimen.__name__,
        )

    @property
    def org_identifier(self) -> Reference:
        if self.ods_code is None:
            raise CGPClientException("No ODS code supplied")
        return Identifier(
            system="https://fhir.nhs.uk/Id/ods-organization-code",
            value=self.ods_code,
        )

    @property
    def org_reference(self) -> Reference:
        return Reference(
            identifier=self.org_identifier,
            type=Organization.__name__,
        )

    @property
    def tumour_identifier(self) -> Identifier:
        if self.tumour_id is None:
            raise CGPClientException("No tumour ID supplied")
        return Identifier(
            system=f"https://{self.org_identifier.value}.nhs.uk/tumour-id",
            value=self.tumour_id,
        )

    @property
    def run_identifier(self) -> Identifier:
        if self.run_id is None:
            raise CGPClientException("No run ID supplied")
        return Identifier(
            system=f"https://{self.org_identifier.value}.nhs.uk/sequencing-run-id",
            value=self.run_id,
        )

    @property
    def run_reference(self) -> Reference:
        return Reference(
            identifier=self.run_identifier,
            type=Procedure.__name__,
        )

    def file_identifier(self, file_id: str | None = None) -> Identifier:
        if file_id is None:
            if self.file_id is None:
                raise CGPClientException("No file ID supplied")
            # use instance field
            file_id = self.file_id
        return Identifier(
            system=f"https://{self.org_identifier.value}.nhs.uk/file-id",
            value=file_id,
        )

    def file_reference(self, file_id: str) -> Reference:
        return Reference(
            identifier=self.file_identifier(file_id),
            type=DocumentReference.__name__,
        )
