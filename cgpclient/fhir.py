# type: ignore
# we ignore type checking here because of incompatibilities with fhir.resources

import logging
from enum import StrEnum

import requests
from fhir.resources.R4B import construct_fhir_element
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.domainresource import DomainResource
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.relatedperson import RelatedPerson
from fhir.resources.R4B.servicerequest import ServiceRequest

from cgpclient.utils import REQUEST_TIMEOUT_SECS, CGPClientException


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
    def get_pedigree_roles(
        self, api_base_url: str, headers: dict[str, str] | None = None
    ) -> dict[str, PedigreeRole]:
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

    def document_references(
        self,
        api_base_url: str,
        headers: dict[str, str] | None = None,
    ) -> list[CGPDocumentReference]:
        bundle: Bundle = search_for_fhir_resource(
            resource_type=DocumentReference.get_resource_type(),
            params={"related": self.id},
            api_base_url=api_base_url,
            headers=headers,
        )

        doc_refs: list[CGPDocumentReference] = []

        for entry in bundle.entry:
            doc_refs.append(CGPDocumentReference.parse_obj(entry.resource.dict()))

        return doc_refs


def fhir_base_url(api_base_url: str) -> str:
    return f"https://{api_base_url}/FHIR/R4"


def reference_for(
    resource: DomainResource,
    include_first_identifier: bool = False,
    use_placeholder_id: bool = True,
    special_resource_types: frozenset[str] = frozenset(
        {"Patient", "Specimen", "ServiceRequest"}
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


def get_fhir_resource(
    resource_type: str,
    resource_id: str,
    api_base_url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> DomainResource:
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


def post_fhir_resource(
    resource: DomainResource,
    api_base_url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    dry_run: bool = False,
) -> None:
    url: str = f"{fhir_base_url(api_base_url)}/{resource.resource_type}/{resource.id}"

    if resource.resource_type == "Bundle" and resource.type in (
        BundleType.BATCH,
        BundleType.TRANSACTION,
    ):
        # these bundle types are posted to the root of the FHIR server
        logging.info("Posting transaction bundle to the root FHIR endpoint")
        url = f"{fhir_base_url(api_base_url)}/"

    logging.info("Posting resource to endpoint: %s", url)
    logging.debug(resource.json(exclude_none=True))

    if dry_run:
        logging.info("Dry run, so skipping posting resource")
        return

    response: requests.Response = requests.post(
        url=url,
        headers=headers,
        params=params,
        json=resource.json(exclude_none=True),
        timeout=REQUEST_TIMEOUT_SECS,
    )
    if not response.ok:
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
