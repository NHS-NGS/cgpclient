# flake8: noqa: E501
# pylint: disable=wrong-import-order, redefined-outer-name, ungrouped-imports, line-too-long, too-many-arguments, protected-access

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cgpclient.auth import NHSOAuthToken, OAuthProvider
from cgpclient.client import CGPClient, CGPFile, CGPFiles
from cgpclient.drs import DrsObject
from cgpclient.drsupload import AccessURL
from cgpclient.fhir import DocumentReference, FHIRConfig  # type: ignore


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


@patch("cgpclient.auth.time")
@patch("requests.post")
def test_get_oauth_token(mock_post: MagicMock, mock_time: MagicMock):
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

    provider = OAuthProvider(
        api_key="api_key",
        private_key_pem=Path("fake_key.pem"),
        apim_kid="kid",
        api_host="host",
    )

    with patch("cgpclient.auth.OAuthProvider._get_jwt", return_value="NOTAJWT"):
        response: NHSOAuthToken = provider._get_oauth_token()
        assert response.access_token == "token"


def test_get_headers() -> None:
    client: CGPClient = CGPClient(api_host="api.service.nhs.uk", api_key="secret")
    assert "apikey" in client.headers
    assert client.headers["apikey"] == "secret"

    with patch("cgpclient.auth.OAuthProvider.get_access_token", return_value="token"):
        client = CGPClient(
            api_host="host",
            api_key="secret",
            private_key_pem=Path("pem"),
            apim_kid="kid",
        )
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "Bearer token"


@patch("cgpclient.fhir.CGPFHIRClient.search_for_document_references")
def test_list_files(mock_search: MagicMock, document_reference: dict, tmp_path) -> None:
    client: CGPClient = CGPClient(api_host="host", api_key="key")
    mock_search.return_value = [DocumentReference.parse_obj(document_reference)]
    files: CGPFiles = client.get_files()
    assert len(files) == 1
    file: CGPFile = files[0]
    assert file.participant_id == document_reference["subject"]["identifier"]["value"]
    output: Path = tmp_path / "out.txt"
    files.print_table(output=output.open(mode="w"))
    with open(output, encoding="utf-8") as out:
        lines = out.read().splitlines()
        assert len(lines) == 2


@patch("cgpclient.drsupload.DrsUploader.upload_files")
@patch("cgpclient.fhir.CGPFHIRClient.post_fhir_resource")
def test_upload_file(
    mock_post: MagicMock, mock_drs_upload: MagicMock, drs_object: dict
) -> None:
    config: FHIRConfig = FHIRConfig(ods_code="ODS", participant_id="p123")
    client: CGPClient = CGPClient(api_host="host", api_key="key", fhir_config=config)
    mock_drs_upload.return_value = [DrsObject.model_validate(drs_object)]
    mock_post.return_value = None
    client.upload_files(filenames=[Path("foo.csv")])
    mock_drs_upload.assert_called_once()
    mock_post.assert_called_once()


@patch("cgpclient.drsupload.DrsUploader.upload_files")
@patch("cgpclient.fhir.CGPFHIRClient.post_fhir_resource")
def test_upload_dragen(
    mock_post: MagicMock, mock_drs_upload: MagicMock, drs_object: dict, tmp_path
) -> None:
    config: FHIRConfig = FHIRConfig(
        ods_code="ODS",
        participant_id="p123",
        sample_id="s123",
        referral_id="r123",
        run_id="run123",
    )
    client: CGPClient = CGPClient(api_host="host", api_key="key", fhir_config=config)
    drs_obj: DrsObject = DrsObject.model_validate(drs_object)
    mock_drs_upload.return_value = [drs_obj, drs_obj]
    mock_post.return_value = None
    fastq_list: Path = tmp_path / "list.csv"
    with open(fastq_list, "w", encoding="utf-8") as o:
        o.write("RGID,RGSM,RGLB,Lane,Read1File,Read2File\n")
        o.write("rgid,s123,rglb,1,file1.fastq.gz,file2.fastq.gz\n")
    client.upload_dragen_run(fastq_list_csv=fastq_list)
    mock_drs_upload.assert_called_once()
    mock_post.assert_called_once()


@patch("cgpclient.drs.md5sum")
@patch("cgpclient.drs.CGPDrsClient.get_drs_object")
@patch("cgpclient.fhir.CGPFHIRClient.search_for_document_references")
@patch("cgpclient.drs.requests.get")
def test_download_file(
    mock_get: MagicMock,
    mock_search: MagicMock,
    mock_get_drs: MagicMock,
    mock_md5: MagicMock,
    document_reference: dict,
    drs_object: dict,
    tmp_path,
) -> None:
    # this is dodgy! there are 2 calls to requests.get, one uses json and the
    # other iter_content so we can use the same mock for both
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            # get for presigned URL
            return AccessURL(url="https://not-a-url", headers=[]).model_dump()

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size: int):
            # get of actual data from presigned URL
            assert chunk_size > 0
            return [b"data"]

    mock_get.return_value = MockedResponse()
    mock_search.return_value = [DocumentReference.parse_obj(document_reference)]
    mock_get_drs.return_value = DrsObject.model_validate(drs_object)
    mock_md5.return_value = "NOTAHASH"

    config: FHIRConfig = FHIRConfig(
        ods_code="ODS",
        participant_id="p123",
        sample_id="s123",
        referral_id="r123",
        run_id="run123",
    )
    client: CGPClient = CGPClient(api_host="host", api_key="key", fhir_config=config)
    out: Path = tmp_path / Path("out.txt")
    client.download_file(output=out)
    with open(out, encoding="utf-8") as outfile:
        assert outfile.read() == "data"
