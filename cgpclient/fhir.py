# type: ignore
# we ignore type checking here because of incompatibilities with fhir.resources

import logging
from enum import StrEnum

import requests
from fhir.resources.R4B import construct_fhir_element
from fhir.resources.R4B.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.R4B.device import Device, DeviceDeviceName, DeviceVersion
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.domainresource import DomainResource
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.provenance import Provenance, ProvenanceAgent
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.relatedperson import RelatedPerson
from fhir.resources.R4B.servicerequest import ServiceRequest

import cgpclient
from cgpclient.utils import (
    REQUEST_TIMEOUT_SECS,
    CGPClientException,
    create_uuid,
    get_current_datetime,
)


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

    def ngis_participant_id(self) -> str:
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
        self, api_base_url: str, headers: dict[str, str] | None = None
    ) -> dict[str, PedigreeRole]:
        """Search the FHIR server for the roles of each participant in the pedigree"""
        # pylint: disable=no-member
        proband_id: str = self.subject.reference
        bundle: Bundle = search_for_fhir_resource(
            resource_type=RelatedPerson.get_resource_type(),
            params={"patient": proband_id},
            api_base_url=api_base_url,
            headers=headers,
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
    def ngis_referral_id(self) -> str:
        """Retrieve the NGIS referral identfier from the ServiceRequest"""
        for identifier in self.identifier:
            if identifier.system == "https://genomicsengland.co.uk/ngis-referral-id":
                return identifier.value
        raise CGPClientException("No NGIS referral ID for ServiceRequest")

    def document_references(
        self,
        api_base_url: str,
        headers: dict[str, str] | None = None,
    ) -> list[CGPDocumentReference]:
        """Fetch associated DocumentReference resources from the FHIR server"""
        bundle: Bundle = search_for_fhir_resource(
            resource_type=DocumentReference.get_resource_type(),
            params={"related:identifier": self.ngis_referral_id, "_count": 100},
            api_base_url=api_base_url,
            headers=headers,
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


def provenance_for(resource: DomainResource, ods_code: str) -> Provenance:
    return Provenance(
        id=create_uuid(),
        target=[reference_for(resource)],
        recorded=get_current_datetime(),
        agent=[
            ProvenanceAgent(
                who=reference_for(CGPClientDevice),
                onBehalfOf=Reference(
                    identifier=Identifier(
                        system="https://fhir.nhs.uk/Id/ods-organization-code",
                        value=ods_code,
                    ),
                    type=Organization.__name__,
                ),
            )
        ],
    )


def fhir_base_url(api_base_url: str) -> str:
    """Return the base URL for the FHIR server"""
    return f"https://{api_base_url}/FHIR/R4"


def reference_for(
    resource: DomainResource,
    include_first_identifier: bool = False,
    use_placeholder_id: bool = True,
    special_resource_types: frozenset[str] = frozenset(
        {"Patient", "Specimen", "ServiceRequest"}
    ),
) -> Reference:
    """Create a FHIR Reference resource referring to the resource"""
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


def get_fhir_resource(
    resource_type: str,
    resource_id: str,
    api_base_url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> DomainResource:
    """Fetch a FHIR resource from the FHIR server"""
    url: str = f"{fhir_base_url(api_base_url)}/{resource_type}/{resource_id}"
    logging.info("Requesting endpoint: %s", url)
    response: requests.Response = requests.get(
        url=url,
        headers=headers,
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


def add_provenance_for_bundle(bundle: Bundle, ods_code: str) -> Bundle:
    """Add Provenance resources for each of the resources in the Bundle"""

    # add the Device resource
    bundle.entry += [bundle_entry_for(CGPClientDevice)]

    provenance_resources: list[BundleEntry] = [
        bundle_entry_for(resource=provenance_for(entry.resource, ods_code=ods_code))
        for entry in bundle.entry
    ]

    # include the original resources and the Provenance resources
    bundle.entry = bundle.entry + provenance_resources
    return bundle


def post_fhir_resource(
    resource: DomainResource,
    api_base_url: str,
    ods_code: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    dry_run: bool = False,
    include_provenance: bool = True,
) -> None:
    """Post a FHIR resource to the FHIR server"""
    url: str = f"{fhir_base_url(api_base_url)}/{resource.resource_type}/{resource.id}"

    if resource.resource_type == Bundle.__name__ and resource.type in (
        BundleType.BATCH,
        BundleType.TRANSACTION,
    ):
        # these bundle types are posted to the root of the FHIR server
        logging.info("Posting bundle to the root FHIR endpoint")
        url = f"{fhir_base_url(api_base_url)}/"
        if include_provenance:
            resource = add_provenance_for_bundle(bundle=resource, ods_code=ods_code)

        logging.info("Posting bundle including %i entries", len(resource.entry))
    else:
        if include_provenance and "X-Provenance" not in headers:
            headers["X-Provenance"] = provenance_for(
                resource=resource, ods_code=ods_code
            ).json(exclude_none=True)

    logging.info("Posting resource to endpoint: %s", url)
    logging.debug(resource.json(exclude_none=True))

    if dry_run:
        logging.info("Dry run, so skipping posting resource")
        return

    response: requests.Response = requests.post(
        url=url,
        headers=headers,
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


def search_for_fhir_resource(
    resource_type: str,
    params: dict[str, str],
    api_base_url: str,
    headers: dict[str, str] | None = None,
) -> Bundle:
    """Search for a FHIR resource using the query parameters"""
    url: str = f"{fhir_base_url(api_base_url)}/{resource_type}"
    logging.info("Requesting endpoint: %s", url)
    response: requests.Response = requests.get(
        url=url,
        headers=headers,
        params=params,
        timeout=REQUEST_TIMEOUT_SECS,
    )
    if response.ok or response.status_code:
        return Bundle.parse_obj(response.json())

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
    ngis_referral_id: str, api_base_url: str, headers: dict[str, str] | None = None
) -> CGPServiceRequest:
    """Search for a ServiceRequest resource corresponding to an NGIS referral ID"""
    bundle: Bundle = search_for_fhir_resource(
        resource_type=ServiceRequest.get_resource_type(),
        params={"identifier": ngis_referral_id},
        api_base_url=api_base_url,
        headers=headers,
    )
    if bundle.entry is None:
        raise CGPClientException(
            f"Didn't find a ServiceRequest for NGIS referral ID: {ngis_referral_id}"
        )
    if len(bundle.entry) == 1:
        # pylint: disable=unsubscriptable-object
        return CGPServiceRequest.parse_obj(bundle.entry[0].resource.dict())
    raise CGPClientException("Unexpected number of ServiceRequests found")


def get_patient(
    ngis_participant_id: str, api_base_url: str, headers: dict[str, str] | None = None
):
    """Search for a Patient resource corresponding to an NGIS participant ID"""
    bundle: Bundle = search_for_fhir_resource(
        resource_type=Patient.get_resource_type(),
        params={"identifier": ngis_participant_id},
        api_base_url=api_base_url,
        headers=headers,
    )
    if bundle.entry is None:
        raise CGPClientException(
            f"Didn't find a Patient for NGIS participant ID: {ngis_participant_id}"
        )
    if len(bundle.entry) == 1:
        # pylint: disable=unsubscriptable-object
        return Patient.parse_obj(bundle.entry[0].resource.dict())
    raise CGPClientException("Unexpected number of Patients found")
