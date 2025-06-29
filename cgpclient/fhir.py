# type: ignore
# we ignore type checking here because of incompatibilities with fhir.resources
# pylint: disable=unsubscriptable-object
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
from fhir.resources.R4B.device import Device, DeviceDeviceName, DeviceVersion
from fhir.resources.R4B.documentreference import (
    DocumentReference,
    DocumentReferenceContent,
    DocumentReferenceContext,
)
from fhir.resources.R4B.domainresource import DomainResource
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.provenance import Provenance, ProvenanceAgent
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.relatedperson import RelatedPerson
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen

import cgpclient
from cgpclient.drs import DrsObject
from cgpclient.drsupload import upload_file_with_drs
from cgpclient.utils import (
    REQUEST_TIMEOUT_SECS,
    CGPClientException,
    create_uuid,
    get_current_datetime,
)

MAX_SEARCH_RESULTS = 100


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


# pylint: disable=too-many-ancestors
class CGPDocumentReference(DocumentReference):
    def ngis_document_category_codes(self) -> set[str]:
        codes: set[str] = set()
        for category in self.category:
            for coding in category.coding:
                if coding.system == "https://genomicsengland.co.uk/ngis-file-category":
                    codes.add(coding.code)
        return codes

    def participant_id(self) -> str:
        # pylint: disable=no-member
        if (
            self.subject.identifier.system
            == "https://genomicsengland.co.uk/ngis-participant-id"
        ):
            return self.subject.identifier.value

        raise CGPClientException("No NGIS participant identifier found")

    def url(self) -> str:
        if len(self.content) == 1:
            return self.content[0].attachment.url
        raise CGPClientException("More than one attachment found in DocumentReference")


class CGPServiceRequest(ServiceRequest):
    """A subclass of a FHIR ServiceRequest modelling an NGIS referral"""

    def get_pedigree_roles(
        self, client: cgpclient.client.CGPClient
    ) -> dict[str, PedigreeRole]:
        """Search the FHIR server for the roles of each participant in the pedigree"""
        # pylint: disable=no-member
        proband_id: str = self.subject.reference
        bundle: Bundle = search_for_fhir_resource(
            resource_type=RelatedPerson.get_resource_type(),
            query_params={"patient": proband_id},
            client=client,
        )
        roles: dict[str, str] = {self.subject.identifier.value: "proband"}
        if bundle.entry is not None:
            for entry in bundle.entry:
                relative: RelatedPerson = RelatedPerson.parse_obj(entry.resource.dict())
                roles[relative.identifier[0].value] = PedigreeRole(
                    relative.relationship[0].coding[0].display
                )

        return roles

    @property
    def referral_id(self) -> str:
        """Retrieve the NGIS referral identfier from the ServiceRequest"""
        for identifier in self.identifier:
            if identifier.system == "https://genomicsengland.co.uk/ngis-referral-id":
                return identifier.value
        raise CGPClientException("No NGIS referral ID for ServiceRequest")

    def document_references(
        self, client: cgpclient.client.CGPClient
    ) -> list[CGPDocumentReference]:
        """Fetch associated DocumentReference resources from the FHIR server"""
        bundle: Bundle = search_for_fhir_resource(
            resource_type=DocumentReference.get_resource_type(),
            query_params={"related:identifier": self.referral_id, "_count": 100},
            client=client,
        )

        doc_refs: list[CGPDocumentReference] = []

        for entry in bundle.entry:
            doc_refs.append(CGPDocumentReference.parse_obj(entry.resource.dict()))

        return doc_refs


CGPClientDevice: Device = Device(
    id=create_uuid(),
    version=[DeviceVersion(value=cgpclient.__version__)],
    deviceName=[DeviceDeviceName(name="cgpclient", type="manufacturer-name")],
)


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


def get_resource(
    resource_id: str,
    client: cgpclient.client.CGPClient,
    resource_type: str | None = None,
    params: dict[str, str] | None = None,
) -> DomainResource:
    """Fetch a FHIR resource from the FHIR server"""
    if resource_type is None and "/" in resource_id:
        resource_type, resource_id = resource_id.split("/")
    else:
        raise CGPClientException("Need explicit resource type")

    url: str = f"{fhir_base_url(client.api_base_url)}/{resource_type}/{resource_id}"
    logging.info("Requesting endpoint: %s", url)
    response: requests.Response = requests.get(
        url=url,
        headers=client.headers,
        params=params,
        timeout=REQUEST_TIMEOUT_SECS,
    )
    if response.ok:
        return construct_fhir_element(resource_type, response.json())

    raise CGPClientException(
        (
            f"Failed to fetch from endpoint: {url} "
            f"status: {response.status_code} "
            f"response: {response.text}"
        )
    )


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
def document_reference_for_drs_object(
    drs_object: DrsObject, client: cgpclient.client.CGPClient
) -> DocumentReference:
    """Create a DocumentReference resource corresponding to a DRS object"""
    return DocumentReference(
        id=create_uuid(),
        identifier=[client.config.file_identifier(drs_object.name)],
        status=DocumentReferenceStatus.CURRENT,
        docStatus=DocumentReferenceDocStatus.FINAL,
        author=[client.config.org_reference],
        subject=client.config.participant_reference,
        content=[
            DocumentReferenceContent(
                attachment=Attachment(
                    url=drs_object.self_uri,
                    contentType=drs_object.mime_type,
                    title=drs_object.name,
                    size=drs_object.size,
                    hash=drs_object.checksums[0].checksum,
                )
            ),
        ],
        context=DocumentReferenceContext(related=client.config.related_references),
    )


def create_drs_document_reference(
    filename: Path,
    client: cgpclient.client.CGPClient,
) -> DocumentReference:
    """Upload the file using the DRS upload protocol and return a DocumentReference"""
    drs_object: DrsObject = upload_file_with_drs(filename=filename, client=client)

    return document_reference_for_drs_object(
        drs_object=drs_object,
        client=client,
    )


def upload_file(
    filename: Path,
    client: cgpclient.client.CGPClient,
) -> None:
    """Upload the file using the DRS upload protocol and post a
    DocumentReference to the FHIR server"""

    document_reference: DocumentReference = create_drs_document_reference(
        filename=filename,
        client=client,
    )

    post_fhir_resource(
        resource=bundle_for([document_reference]),
        client=client,
    )


def post_fhir_resource(
    resource: DomainResource,
    client: cgpclient.client.CGPClient,
    params: dict[str, str] | None = None,
) -> None:
    """Post a FHIR resource to the FHIR server"""
    url: str = (
        f"{fhir_base_url(client.api_base_url)}/{resource.resource_type}/{resource.id}"
    )

    if resource.resource_type == Bundle.__name__ and resource.type in (
        BundleType.BATCH,
        BundleType.TRANSACTION,
    ):
        # these bundle types are posted to the root of the FHIR server
        logging.info("Posting bundle to the root FHIR endpoint")
        url = f"{fhir_base_url(client.api_base_url)}/"
        if client.config.org_reference is not None:
            resource = add_provenance_for_bundle(
                bundle=resource, org_reference=client.config.org_reference
            )

        logging.info("Posting bundle including %i entries", len(resource.entry))

    logging.info("Posting resource to endpoint: %s", url)
    logging.debug(resource.json(exclude_none=True))

    if client.dry_run:
        logging.info("Dry run, so skipping posting resource")
        return

    response: requests.Response = requests.post(
        url=url,
        headers=client.headers,
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


def search_for_document_reference(
    client: cgpclient.client.CGPClient, query_params: dict[str, str] | None = None
) -> Bundle:
    if query_params is None:
        # use the client config to define search parameters
        query_params: dict = {
            "_count": "100",
        }

        if client.config.file_id is not None:
            query_params["identifier"] = identifier_search_string(
                client.config.file_identifier()
            )

        if client.config.related_query_string is not None:
            query_params["related:identifier"] = client.config.related_query_string

        if client.config.participant_id is not None:
            query_params["subject:identifier"] = identifier_search_string(
                client.config.participant_identifier
            )

        if client.config.ods_code is not None:
            query_params["author:identifier"] = identifier_search_string(
                client.config.org_identifier
            )

    return search_for_fhir_resource(
        resource_type=DocumentReference.__name__,
        query_params=query_params,
        client=client,
    )


def search_for_fhir_resource(
    resource_type: str,
    query_params: dict[str, str],
    client: cgpclient.client.CGPClient,
) -> Bundle:
    """Search for a FHIR resource using the query parameters"""
    url: str = f"{fhir_base_url(client.api_base_url)}/{resource_type}"
    query_params["_count"] = str(MAX_SEARCH_RESULTS)

    logging.info("Requesting endpoint: %s", url)
    logging.info("Query parameters: %s", query_params)

    response: requests.Response = requests.get(
        url=url,
        headers=client.headers,
        params=query_params,
        timeout=REQUEST_TIMEOUT_SECS,
    )
    if response.ok or response.status_code:
        logging.debug(response.json())
        bundle: Bundle = Bundle.parse_obj(response.json())
        if bundle.link and len(bundle.link) == 1 and bundle.link[0].relation == "next":
            # TODO: need to override host
            url: str = bundle.link[0].url
            logging.info(
                "More than %i results for search, implement paging!", MAX_SEARCH_RESULTS
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


def get_service_request(
    referral_id: str, client: cgpclient.client.CGPClient
) -> CGPServiceRequest:
    """Search for a ServiceRequest resource corresponding to an NGIS referral ID"""
    bundle: Bundle = search_for_fhir_resource(
        resource_type=ServiceRequest.get_resource_type(),
        query_params={"identifier": referral_id},
        client=client,
    )
    if bundle.entry is None:
        raise CGPClientException(
            f"Didn't find a ServiceRequest for NGIS referral ID: {referral_id}"
        )
    if len(bundle.entry) == 1:
        # pylint: disable=unsubscriptable-object
        return CGPServiceRequest.parse_obj(bundle.entry[0].resource.dict())
    raise CGPClientException("Unexpected number of ServiceRequests found")


def get_patient(participant_id: str, client: cgpclient.client.CGPClient):
    """Search for a Patient resource corresponding to an NGIS participant ID"""
    bundle: Bundle = search_for_fhir_resource(
        resource_type=Patient.get_resource_type(),
        query_params={"identifier": participant_id},
        client=client,
    )
    if bundle.entry is None:
        raise CGPClientException(
            f"Didn't find a Patient for NGIS participant ID: {participant_id}"
        )
    if len(bundle.entry) == 1:
        # pylint: disable=unsubscriptable-object
        return Patient.parse_obj(bundle.entry[0].resource.dict())
    raise CGPClientException("Unexpected number of Patients found")


class ClientConfig:
    def __init__(
        self,
        participant_id: str | None = None,
        referral_id: str | None = None,
        ods_code: str | None = None,
        run_id: str | None = None,
        sample_id: str | None = None,
        tumour_id: str | None = None,
        file_id: str | None = None,
    ):
        self.participant_id = participant_id
        self.referral_id = referral_id
        self.run_id = run_id
        self.ods_code = ods_code
        self.sample_id = sample_id
        self.tumour_id = tumour_id
        self.file_id = file_id

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
