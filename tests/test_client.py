# flake8: noqa: E501
# pylint: disable=wrong-import-order, redefined-outer-name, ungrouped-imports, line-too-long, too-many-arguments, protected-access

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fhir.resources.R4B.servicerequest import ServiceRequest

from cgpclient.client import (
    CGPClient,
    CGPClientException,
    GenomicFile,
    GenomicFiles,
    NHSOAuthToken,
)
from cgpclient.drs import (
    DrsObject,
    get_access_url,
    get_object,
    get_object_from_url,
    map_drs_to_https_url,
)
from cgpclient.fhir import (  # type: ignore
    CGPDocumentReference,
    CGPServiceRequest,
    PedigreeRole,
    get_service_request_for_ngis_referral_id,
)


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
                    "contentType": "application/vcf",
                    "url": "https://api.service.nhs.uk/genomic-data-access/ga4gh/drs/v1.4/objects/e73524e3-4b36-4624-8af8-fe1b0ad28b07",
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
def drs_object() -> dict:
    return {
        "id": "d6237181-65f8-474d-ba6b-a530b5678c38",
        "self_uri": "drs://api.service.nhs.uk/genomic-data-access/d6237181-65f8-474d-ba6b-a530b5678c38",
        "size": 1351,
        "mime_type": "application/cram",
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


@patch("requests.get")
def test_get_service_request(mock_server: MagicMock, sr_bundle: dict):
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return sr_bundle

    mock_server.return_value = MockedResponse()

    service_request: ServiceRequest = get_service_request_for_ngis_referral_id(
        ngis_referral_id="1234", api_base_url="url"
    )

    assert service_request == sr_bundle["entry"][0]["resource"]


@patch("requests.get")
def test_get_document_references(
    mock_server: MagicMock,
    doc_ref_bundle: dict,
    service_request: dict,
    document_reference: dict,
):
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return doc_ref_bundle

    mock_server.return_value = MockedResponse()

    request: CGPServiceRequest = CGPServiceRequest.parse_obj(service_request)

    doc_refs: list[CGPDocumentReference] = request.document_references(
        api_base_url="url"
    )

    assert len(doc_refs) == 1
    assert doc_refs[0] == doc_ref_bundle["entry"][0]["resource"]


def test_get_url(document_reference: dict):
    doc_ref: CGPDocumentReference = CGPDocumentReference.parse_obj(document_reference)
    assert doc_ref.url() == document_reference["content"][0]["attachment"]["url"]


@patch("requests.get")
def test_get_object_from_url(mock_server: MagicMock, drs_object: dict):
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return drs_object

    mock_server.return_value = MockedResponse()

    drs_response: DrsObject = get_object_from_url(url="foo")

    assert drs_response.model_dump(exclude_defaults=True) == drs_object


@patch("cgpclient.drs.get_object_from_url")
def test_get_object(mock_get_object: MagicMock, drs_object: dict):
    mock_get_object.return_value = DrsObject.model_validate(drs_object)
    object_id: str = "foo"
    api_base_url: str = "url"
    drs_response: DrsObject = get_object(object_id=object_id, api_base_url=api_base_url)
    assert drs_response.model_dump(exclude_defaults=True) == drs_object
    mock_get_object.assert_called_once_with(
        url=f"https://{api_base_url}/ga4gh/drs/v1.4/objects/{object_id}", headers=None
    )


@patch("cgpclient.drs.get_object_from_url")
def test_get_access_url(mock_get_object: MagicMock, drs_object: dict):
    mock_get_object.return_value = DrsObject.model_validate(drs_object)

    url: str | None = get_access_url(access_type="htsget", object_url="https://foo")
    assert url == drs_object["access_methods"][1]["access_url"]["url"]


def test_map_drs_to_https_url() -> None:
    object_id: str = "1234"
    drs_url: str = f"drs://api.service.nhs.uk/genomic-data-access/{object_id}"
    https_url: str = f"https://api.service.nhs.uk/genomic-data-access/ga4gh/drs/v1.4/objects/{object_id}"
    assert map_drs_to_https_url(drs_url) == https_url

    with pytest.raises(CGPClientException):
        map_drs_to_https_url(
            f"drs://api.service.nhs.uk/unexpected/genomic-data-access/{object_id}"
        )

    with pytest.raises(CGPClientException):
        map_drs_to_https_url(f"drs://api.service.nhs.uk/{object_id}")

    with pytest.raises(CGPClientException):
        map_drs_to_https_url(
            f"drs://api.service.nhs.uk/ga4gh/drs/v1.4/objects/{object_id}"
        )

    with pytest.raises(CGPClientException):
        map_drs_to_https_url(f"drs://{object_id}")


@patch("cgpclient.client.get_service_request_for_ngis_referral_id")
@patch("cgpclient.client.CGPServiceRequest.document_references")
@patch("cgpclient.client.CGPServiceRequest.get_pedigree_roles")
@patch("cgpclient.client.get_access_url")
def test_get_genomic_files(
    mock_get_access_url: MagicMock,
    mock_get_related: MagicMock,
    mock_get_doc_refs: MagicMock,
    mock_get_sr: MagicMock,
    service_request,
    document_reference,
    drs_object: dict,
):
    referral_id: str = "foo"
    participant_id: str = document_reference["subject"]["identifier"]["value"]
    document_category: str = document_reference["category"][0]["coding"][0]["code"]
    htsget_url: str = drs_object["access_methods"][1]["access_url"]["url"]

    mock_get_access_url.return_value = htsget_url

    mock_get_doc_refs.return_value = [
        CGPDocumentReference.parse_obj(document_reference)
    ]

    mock_get_related.return_value = {participant_id: "proband"}

    mock_get_sr.return_value = CGPServiceRequest.parse_obj(service_request)

    api_key: str = "secret"

    client: CGPClient = CGPClient(api_key=api_key, api_host="host")

    expected: GenomicFiles = GenomicFiles(
        files=[
            GenomicFile(
                ngis_referral_id=referral_id,
                ngis_participant_id=participant_id,
                ngis_document_category=document_category,
                htsget_url=htsget_url,
                pedigree_role=PedigreeRole.PROBAND,
            )
        ]
    )

    files: GenomicFiles = client.get_genomic_files(ngis_referral_id=referral_id)

    mock_get_access_url.assert_called_once()

    mock_get_doc_refs.assert_called_once_with(
        api_base_url="host",
        headers={"apikey": api_key},
    )

    assert files.model_dump_json() == expected.model_dump_json()


@patch("cgpclient.client.time")
@patch("requests.post")
@patch("cgpclient.client.CGPClient.get_jwt")
def test_get_oauth_token(
    mock_jwt: MagicMock, mock_post: MagicMock, mock_time: MagicMock
):
    mock_jwt.return_value = "NOTAJWT"

    expires_in: int = 10
    issued_at: int = 20
    time_now: int = 20

    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return {
                "access_token": "token",
                "expires_in": f"{expires_in}",
                "issued_at": f"{issued_at}",
                "token_type": "type",
            }

    mock_post.return_value = MockedResponse()
    mock_time.return_value = time_now
    client: CGPClient = CGPClient(api_host="host", api_key="secret")
    assert client._oauth_token is None

    response: NHSOAuthToken = client.get_oauth_token()
    assert client._oauth_token is not None
    assert response.model_dump_json() == response.model_dump_json()
    mock_time.assert_not_called()

    class MockedResponse2:
        def ok(self):
            return True

        def json(self):
            return {
                "access_token": "new_token",
                "expires_in": f"{expires_in}",
                "issued_at": f"{issued_at}",
                "token_type": "type",
            }

    mock_post.return_value = MockedResponse2()

    # check the new token isn't used before it expires
    mock_time.return_value = time_now + expires_in - 1
    assert client._oauth_token is not None
    response = client.get_oauth_token()
    assert (response.access_token) != "new_token"
    mock_time.assert_called_once()

    # check the new token is used after the first expires
    mock_time.return_value = time_now + expires_in + 1
    assert client._oauth_token is not None
    response = client.get_oauth_token()
    assert (response.access_token) == "new_token"


@patch("cgpclient.client.CGPClient.get_access_token")
def test_get_headers(mock_token: MagicMock) -> None:
    mock_token.return_value = "token"
    client: CGPClient = CGPClient(api_host="host", api_key="secret")
    assert "apikey" in client.headers()
    assert client.headers()["apikey"] == "secret"
    client = CGPClient(
        api_host="host",
        api_key="secret",
        private_key_pem=Path("pem"),
        apim_kid="kid",
    )
    assert "Authorization" in client.headers()
    assert client.headers()["Authorization"] == "Bearer token"
    client = CGPClient(
        api_host="host",
        api_key="secret",
        private_key_pem=Path("pem"),
        apim_kid="kid",
    )
    assert "Authorization" in client.headers()
