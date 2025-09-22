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
from fhir.resources.R4B.extension import Extension
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.meta import Meta
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.provenance import Provenance, ProvenanceAgent
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen
from fhir.resources.R4B.task import Task

import cgpclient
from cgpclient.drs import CGPDrsClient, DrsObject
from cgpclient.drsupload import DrsUploader
from cgpclient.utils import (
    REQUEST_TIMEOUT_SECS,
    CGPClientException,
    create_uuid,
    get_current_datetime,
)

log = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 100
MAX_UNSIGNED_INT = (
    2147483647  # https://hl7.org/fhir/R4/datatypes.html#unsignedInt # noqa: E501
)
MAX_PAGES = 100


# Enumerations for various FHIR resource fields
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


# A Device resource representing this package used in Provenance resources
# for FHIR resources created by this package
CGPClientDevice: Device = Device(
    id=create_uuid(),
    version=[DeviceVersion(value=cgpclient.__version__)],
    deviceName=[DeviceDeviceName(name="cgpclient", type="manufacturer-name")],
)


class CGPFHIRClient:
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
        if "/" in resource_id:
            resource_type, resource_id = resource_id.split("/")

        if resource_type is None:
            raise CGPClientException("Need explicit resource type")

        url = f"{self.base_url}/{resource_type}/{resource_id}"
        log.info("Requesting endpoint: %s", url)
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

    def _search_paged(
        self,
        url: str,
        query_params: list[tuple] | None = None,
    ) -> Bundle:
        """Peform a search request and page through the results"""
        pages = 1
        while pages <= MAX_PAGES:
            response = requests.get(
                url=url,
                headers=self.headers,
                params=query_params,
                timeout=REQUEST_TIMEOUT_SECS,
            )
            if response.ok:
                bundle = Bundle.parse_obj(response.json())
                yield bundle
                if (
                    bundle.link
                    and len(bundle.link) == 1
                    and bundle.link[0].relation == "next"
                ):
                    log.info("Requesting page %i", pages)
                    # we need to switch the HealthLake URL for one with our prefix # noqa: E501
                    prefix = url.rsplit("/", 1)[0]
                    suffix = bundle.link[0].url.rsplit("/", 1)[-1]
                    url = f"{prefix}/{suffix}"
                    query_params = []  # reset params as these are baked into the URL # noqa: E501
                    pages += 1
                else:
                    return
            else:
                raise CGPClientException(f"Failed to fetch from endpoint: {url}")
        log.info("Reached maximum number of pages")

    def _merge_bundles(self, bundles: list[Bundle]) -> Bundle:
        """Merge a list of Bundles into a single one, retaining the
        metadata of the first"""
        first: Bundle = bundles[0]
        for bundle in bundles[1:]:
            first.entry.extend(bundle.entry)
        return first

    def search_for_fhir_resource(
        self, resource_type: str, query_params: list[tuple] = []
    ) -> Bundle:
        """Search for a FHIR resource using the query parameters"""
        url = f"{self.base_url}/{resource_type}"

        if query_params is None:
            query_params = []

        query_params.append(("_count", str(MAX_SEARCH_RESULTS)))

        if self.config.workspace_id is not None:
            query_params.append(("_tag", self.config.workspace_id))

        log.info("Requesting endpoint: %s", url)
        log.info("Query parameters: %s", query_params)

        bundles: list[Bundle] = []

        for response in self._search_paged(url=url, query_params=query_params):
            bundles.append(response)

        return self._merge_bundles(bundles)

    def search_for_tasks(self, search_params: FHIRConfig | None = None) -> list[Task]:
        query_params: list[tuple] = []

        if search_params is not None:
            if search_params.task_id is not None:
                query_params.append(("_id", search_params.task_id))

            if search_params.participant_id is not None:
                query_params.append(
                    (
                        "subject:identifier",
                        identifier_search_string(search_params.participant_identifier),
                    )
                )

            if search_params.ods_code is not None:
                query_params.append(
                    (
                        "performer:identifier",
                        identifier_search_string(search_params.ods_code),
                    )
                )

    def search_for_document_references(
        self, search_params: FHIRConfig | None = None
    ) -> list[DocumentReference]:
        """Search for DocumentReferences using the parameters in the FHIR
        config"""
        query_params: list[tuple] = []

        if search_params is not None:
            if search_params.document_reference_id is not None:
                query_params.append(("_id", search_params.document_reference_id))

            if search_params.file_id is not None:
                query_params.append(
                    (
                        "identifier",
                        identifier_search_string(search_params.file_identifier()),
                    )
                )

            if search_params.nhs_number is not None:
                query_params.append(
                    (
                        "subject:identifier",
                        identifier_search_string(search_params.nhs_number_identifier),
                    )
                )

            if search_params.related_query_string is not None:
                query_params.append(
                    ("related:identifier", search_params.related_query_string)
                )

            if search_params.participant_id is not None:
                query_params.append(
                    (
                        "subject:identifier",
                        identifier_search_string(search_params.participant_identifier),
                    )
                )

            if search_params.ods_code is not None:
                query_params.append(
                    (
                        "author:identifier",
                        identifier_search_string(search_params.org_identifier),
                    )
                )

        bundle: Bundle = self.search_for_fhir_resource(
            resource_type=DocumentReference.__name__,
            query_params=query_params,
        )

        if bundle.entry:
            return [entry.resource for entry in bundle.entry]
        return []

    def check_clinical_indication(
        self, clinical_indication_code: str, service_request: ServiceRequest
    ) -> bool:
        details = service_request.orderDetail
        if details is not None:
            for detail in details:
                for coding in detail.coding:
                    if coding.code == clinical_indication_code:
                        return True
        return False

    def search_for_service_requests(
        self, search_params: FHIRConfig | None = None
    ) -> list[ServiceRequest]:
        """Search for ServiceRequests using the parameters in the FHIR config"""
        query_params: list[tuple] = []

        if search_params is not None:
            if search_params.referral_id is not None:
                query_params.append(
                    (
                        "identifier",
                        identifier_search_string(search_params.referral_identifier),
                    )
                )

            if search_params.participant_id is not None:
                query_params.append(
                    (
                        "subject:identifier",
                        identifier_search_string(search_params.participant_identifier),
                    )
                )

            if search_params.ods_code is not None:
                print(search_params.org_identifier)
                query_params.append(
                    (
                        "performer:identifier",
                        identifier_search_string(search_params.org_identifier),
                    )
                )

            # only start date provided - user wants to filter for all referrals
            # updated after the provided start date
            if search_params.start_date is not None:
                query_params.append(("_lastUpdated", f"ge{search_params.start_date}"))

            # only end date provided - user wants to filter for all referrals
            # updated before the provided end date
            if search_params.end_date is not None:
                query_params.append(("_lastUpdated", f"le{search_params.end_date}"))

        bundle: Bundle = self.search_for_fhir_resource(
            resource_type=ServiceRequest.__name__,
            query_params=query_params,
        )

        result: list[ServiceRequest] = []

        if bundle.entry:
            result = [entry.resource for entry in bundle.entry]

        # we can't currently search by orderDetail, so we filter the response
        if (
            search_params is not None
            and search_params.clinical_indication_code is not None
        ):
            log.debug(
                "Filtering ServiceRequests to clinical indication %s",
                search_params.clinical_indication.coding[0].code,
            )
            result = [
                sr
                for sr in result
                if self.check_clinical_indication(
                    search_params.clinical_indication.coding[0].code, sr
                )
            ]

        return result

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
            extension=[
                # we use an extension to encode the real file size
                Extension(
                    url="https://genomicsengland.co.uk/file-size",
                    valueDecimal=drs_object.size,
                )
            ],
        )

    def create_drs_document_references(
        self, filenames: list[Path]
    ) -> list[DocumentReference]:
        """Upload the files using the DRS upload protocol and return a
        DocumentReference"""
        drs_client = CGPDrsClient(self.api_base_url, self.headers, self.dry_run)
        uploader = DrsUploader(drs_client)
        drs_objects: list[DrsObject] = uploader.upload_files(filenames, self.output_dir)

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

            log.debug(
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
            log.info("Posting bundle to the root FHIR endpoint")
            url = f"{fhir_base_url(self.api_base_url)}/"
            if self.config.org_reference is not None:
                resource = add_provenance_for_bundle(
                    bundle=resource, org_reference=self.config.org_reference
                )
            self.add_workspace_meta_tag_to_bundle(bundle=resource)
            log.info("Posting bundle including %i entries", len(resource.entry))

        self.add_workspace_meta_tag(resource=resource)

        log.info("Posting resource to endpoint: %s", url)

        if self.output_dir is not None:
            output_file: Path = self.output_dir / Path("fhir_resources.json")
            log.info("Writing FHIR resource to %s", output_file)
            with open(output_file, "a", encoding="utf-8") as out:
                print(resource.json(exclude_none=True), file=out)

        if self.dry_run:
            log.info("Dry run, so skipping posting resource")
            return

        response: requests.Response = requests.post(
            url=url,
            headers=self.headers,
            params=params,
            data=resource.json(exclude_none=True),
            timeout=REQUEST_TIMEOUT_SECS,
        )
        if response.ok:
            log.info("Successfully posted FHIR resource")
            return

        raise CGPClientException(
            f"Failed to post to endpoint: {url} "
            f"status: {response.status_code} response: {response.text}"
        )


def create_resource_from_dict(data: dict) -> DomainResource:
    """Construct a FHIR resource from a python dictionary"""
    return construct_fhir_element(data["resourceType"], data)


def reference_for(
    resource: DomainResource,
    include_first_identifier: bool = False,
    use_placeholder_id: bool = True,
    special_resource_types: frozenset[str] = frozenset(
        {"Patient", "Specimen", "ServiceRequest", "Procedure"}
    ),
) -> Reference:
    """Create a Reference resource for the given FHIR resource"""
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
    """Create a Provenance resource for the given FHIR resource"""
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
    resource: DomainResource,
    method: BundleRequestMethod = BundleRequestMethod.POST,
) -> BundleEntry:
    """Create a BundleEntry for the resource, using the specified method"""
    return BundleEntry(
        fullUrl=f"urn:uuid:{resource.id}",
        resource=resource,
        request=BundleEntryRequest(method=method, url=resource.resource_type),
    )


def bundle_for(
    resources: list[DomainResource],
    bundle_type: BundleType = BundleType.TRANSACTION,
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
        clinical_indication_code: str | None = None,
        file_id: str | None = None,
        workspace_id: str | None = None,
        nhs_number: str | None = None,
        document_reference_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ):
        self.participant_id = participant_id
        self.referral_id = referral_id
        self.run_id = run_id
        self.ods_code = ods_code
        self.sample_id = sample_id
        self.tumour_id = tumour_id
        self.clinical_indication_code = clinical_indication_code
        self.file_id = file_id
        self.workspace_id = workspace_id
        self.nhs_number = nhs_number
        self.document_reference_id = document_reference_id
        self.start_date = start_date
        self.end_date = end_date

        if document_reference_id is not None and document_reference_id.startswith(
            DocumentReference.__name__
        ):
            # allow IDs of the form DocumentReference/UUID
            self.document_reference_id = document_reference_id.split("/")[-1]

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
    def nhs_number_identifier(self) -> Identifier:
        if self.nhs_number is None:
            raise CGPClientException("No NHS number supplied")
        return Identifier(
            system="https://fhir.nhs.uk/Id/nhs-number",
            value=self.nhs_number,
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
    def clinical_indication(self) -> CodeableConcept:
        if self.clinical_indication_code is None:
            raise CGPClientException("No clinical indication code supplied")
        return CodeableConcept(
            coding=[
                Coding(
                    system="https://fhir.nhs.uk/CodeSystem/England-GenomicTestDirectory",
                    code=self.clinical_indication_code,
                )
            ],
        )

    # def start_date(self):
    #     if self.start_date is None:
    #         raise CGPClientException("No start date supplied")
    #     return f"ge{self.start_date}"

    # def end_date(self):
    #     if self.end_date is None:
    #         raise CGPClientException("No end date supplied")
    #     return f"le{self.end_date}"

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
