# type: ignore
# we ignore type checking here because of incompatibilities with fhir.resources

import logging
from enum import StrEnum

import requests
from fhir.resources import construct_fhir_element
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.domainresource import DomainResource
from fhir.resources.R4B.relatedperson import RelatedPerson
from fhir.resources.R4B.servicerequest import ServiceRequest

from cgpclient.utils import REQUEST_TIMEOUT_SECS, CGPClientException


class PedigreeRole(StrEnum):
    PROBAND = "proband"
    MOTHER = "mother"
    FATHER = "father"
    SIBLING = "sibling"
    HALF_SIBLING = "half-sibling"
    FAMILY_MEMBER = "family member"


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
        bundle: Bundle = search_for_resource(
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
        bundle: Bundle = search_for_resource(
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


def get_resource(
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


def put_resource(
    resource: DomainResource,
    api_base_url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    url: str = (
        f"{fhir_base_url(api_base_url)}/{resource.resource_type()}/{resource.id()}"
    )
    logging.info("Posting resource %s to endpoint: %s", resource.id(), url)
    response: requests.Response = requests.post(
        url=url,
        headers=headers,
        params=params,
        json=resource.json(),
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


def search_for_resource(
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


def get_service_request_for_ngis_referral_id(
    ngis_referral_id: str, api_base_url: str, headers: dict[str, str] | None = None
) -> CGPServiceRequest:
    bundle: Bundle = search_for_resource(
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
