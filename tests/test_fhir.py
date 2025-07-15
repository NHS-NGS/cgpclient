# flake8: noqa: E501
# pylint: disable=wrong-import-order, redefined-outer-name, ungrouped-imports, line-too-long, too-many-arguments, protected-access


from unittest.mock import MagicMock, patch

import pytest

from cgpclient.client import CGPClient
from cgpclient.fhir import CGPFHIRClient, FHIRConfig  # type: ignore


@pytest.fixture(scope="function")
def service_request() -> dict:
    return {
        "resourceType": "ServiceRequest",
        "id": "d61120e4-0f7b-4f5e-aac3-7286dabf84e5",
        "identifier": [
            {
                "system": "https://genomicsengland.co.uk/ngis-referral-id",
                "value": "r20890680287",
            }
        ],
        "status": "active",
        "intent": "order",
        "category": [
            {
                "coding": [
                    {
                        "system": "https://fhir.hl7.org.uk/CodeSystem/UKCore-GenomeSequencingCategory",
                        "code": "rare-disease-wgs",
                        "display": "Rare Disease - WGS",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "https://fhir.nhs.uk/CodeSystem/England-GenomicTestDirectory",
                    "version": "7",
                    "code": "R193.4",
                    "display": "Cystic renal disease WGS",
                }
            ]
        },
        "orderDetail": [
            {
                "coding": [
                    {
                        "system": "https://fhir.nhs.uk/CodeSystem/England-GenomicTestDirectory",
                        "version": "7",
                        "code": "R193",
                        "display": "Cystic renal disease",
                    }
                ]
            }
        ],
        "subject": {
            "reference": "Patient/5a373fb4-c0f5-4d1c-9f7c-0dfd515c2a67",
            "identifier": {
                "system": "https://genomicsengland.co.uk/ngis-participant-id",
                "value": "p85535466602",
            },
        },
        "performer": [
            {
                "identifier": {
                    "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                    "value": "RPY",
                }
            }
        ],
        "reasonCode": [
            {
                "coding": [
                    {
                        "system": "https://fhir.nhs.uk/CodeSystem/reasonfortesting-genomics",
                        "code": "diagnostic",
                        "display": "Diagnostic",
                    }
                ]
            }
        ],
        "supportingInfo": [
            {"reference": "Observation/50cb1ebf-b1a6-4283-8c04-6020a8371aed"},
        ],
    }


@pytest.fixture(scope="function")
def sr_bundle(service_request: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": service_request, "search": {"mode": "match"}}],
    }


@pytest.fixture(scope="function")
def document_reference() -> dict:
    return {
        "resourceType": "DocumentReference",
        "meta": {"lastUpdated": "2025-07-06T13:09:10Z"},
        "id": "90844498-09d3-4f02-a871-03197c752ad2",
        "status": "current",
        "docStatus": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "https://genomicsengland.co.uk/ngis-file-category",
                        "code": "VCF_small",
                    }
                ]
            }
        ],
        "subject": {
            "reference": "Patient/5a373fb4-c0f5-4d1c-9f7c-0dfd515c2a67",
            "identifier": {
                "system": "https://genomicsengland.co.uk/ngis-participant-id",
                "value": "p85535466602",
            },
        },
        "author": [
            {
                "identifier": {
                    "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                    "value": "8J834",
                }
            }
        ],
        "content": [
            {
                "attachment": {
                    "contentType": "text/vcf",
                    "url": "https://api.service.nhs.uk/genomic-data-access/ga4gh/drs/v1.4/objects/e73524e3-4b36-4624-8af8-fe1b0ad28b07",
                    "title": "variants.vcf",
                    "size": 100,
                    "hash": "NOTAHASH",
                }
            }
        ],
        "context": {
            "related": [
                {
                    "reference": "ServiceRequest/d61120e4-0f7b-4f5e-aac3-7286dabf84e5",
                    "identifier": {
                        "system": "https://genomicsengland.co.uk/ngis-referral-id",
                        "value": "r20890680287",
                    },
                },
                {
                    "reference": "Specimen/9ffaa156-1638-49cb-ba78-e80ad504221a",
                    "identifier": {
                        "system": "https://genomicsengland.co.uk/ngis-sample-id",
                        "value": "LP3000173-DNA_E04",
                    },
                },
                {
                    "reference": "Procedure/8ffaa156-1638-49cb-ba78-e80ad504221a",
                    "identifier": {
                        "system": "https://genomicsengland.co.uk/run-id",
                        "value": "123456",
                    },
                },
            ]
        },
    }


@pytest.fixture(scope="function")
def doc_ref_bundle(document_reference: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": document_reference, "search": {"mode": "match"}}],
    }


@pytest.fixture(scope="function")
def serv_req_bundle(service_request: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": service_request, "search": {"mode": "match"}}],
    }


@pytest.fixture(scope="function")
def drs_object() -> dict:
    return {
        "id": "d6237181-65f8-474d-ba6b-a530b5678c38",
        "self_uri": "drs://api.service.nhs.uk/genomic-data-access/d6237181-65f8-474d-ba6b-a530b5678c38",
        "size": 1351,
        "mime_type": "application/cram",
        "name": "reads.cram",
        "checksums": [{"type": "md5", "checksum": "0556530eb3d73a27581ce7b2ca4dc3e7"}],
        "created_time": "2024-04-12T23:20:50.52Z",
        "access_methods": [
            {
                "type": "s3",
                "access_url": {
                    "url": "https://s3.eu-west-2.amazonaws.com/cgp-test-bucket/173cd57a-969f-49f9-8754-1e22e218cdbf"
                },
                "access_id": "173cd57a-969f-49f9-8754-1e22e218cdbf",
                "region": "eu-west-2",
            },
            {
                "type": "htsget",
                "access_url": {
                    "url": "https://internal-dev.api.service.nhs.uk/genomic-data-access/ga4gh/htsget/v1.3/reads/173cd57a-969f-49f9-8754-1e22e218cdbf"
                },
            },
        ],
    }


@pytest.fixture(scope="function")
def client() -> CGPClient:
    return CGPClient(api_host="host")


@patch("cgpclient.fhir.requests.get")
def test_get_resource(mock_get: MagicMock, document_reference: dict) -> None:
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return document_reference

    mock_get.return_value = MockedResponse()

    config: FHIRConfig = FHIRConfig()

    fhir: CGPFHIRClient = CGPFHIRClient(
        api_base_url="host", headers={}, config=config, dry_run=False
    )
    resource = fhir.get_resource(resource_id="foo", resource_type="DocumentReference")
    assert resource.resource_type == "DocumentReference"


@patch("cgpclient.fhir.requests.get")
def test_search_resource(mock_get: MagicMock, doc_ref_bundle: dict) -> None:
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return doc_ref_bundle

    mock_get.return_value = MockedResponse()

    config: FHIRConfig = FHIRConfig()

    fhir: CGPFHIRClient = CGPFHIRClient(
        api_base_url="host", headers={}, config=config, dry_run=False
    )
    resource = fhir.search_for_fhir_resource(resource_type="DocumentReference")
    assert resource.entry and len(resource.entry) == 1


@patch("cgpclient.fhir.requests.get")
def test_search_doc_refs(mock_get: MagicMock, doc_ref_bundle: dict) -> None:
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return doc_ref_bundle

    mock_get.return_value = MockedResponse()

    config: FHIRConfig = FHIRConfig()

    fhir: CGPFHIRClient = CGPFHIRClient(
        api_base_url="host", headers={}, config=config, dry_run=False
    )
    doc_refs = fhir.search_for_document_references()
    assert len(doc_refs) == 1


@patch("cgpclient.fhir.requests.get")
def test_search_serv_reqs(mock_get: MagicMock, serv_req_bundle: dict) -> None:
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return serv_req_bundle

    mock_get.return_value = MockedResponse()

    config: FHIRConfig = FHIRConfig()

    fhir: CGPFHIRClient = CGPFHIRClient(
        api_base_url="host", headers={}, config=config, dry_run=False
    )
    serv_reqs = fhir.search_for_service_requests()
    assert len(serv_reqs) == 1
