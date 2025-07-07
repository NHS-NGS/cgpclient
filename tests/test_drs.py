# flake8: noqa: E501
# pylint: disable=wrong-import-order, redefined-outer-name, ungrouped-imports, line-too-long, too-many-arguments, protected-access

from unittest.mock import MagicMock, patch

import pytest

from cgpclient.client import CGPClient
from cgpclient.drs import (
    DrsObject,
    _get_drs_object_from_https_url,
    get_drs_object,
    map_drs_to_https_url,
)
from cgpclient.utils import CGPClientException


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


@patch("requests.get")
def test_get_object_from_https_url(
    mock_server: MagicMock, drs_object: dict, client: CGPClient
):
    class MockedResponse:
        def ok(self):
            return True

        def json(self):
            return drs_object

    mock_server.return_value = MockedResponse()

    with pytest.raises(CGPClientException):
        _get_drs_object_from_https_url(https_url="foo", headers=client.headers)

    with pytest.raises(CGPClientException):
        _get_drs_object_from_https_url(https_url="drs://foo", headers=client.headers)

    drs_response: DrsObject = _get_drs_object_from_https_url(
        https_url="https://foo", headers=client.headers
    )

    assert drs_response.model_dump(exclude_defaults=True) == drs_object


@patch("cgpclient.drs._get_drs_object_from_https_url")
def test_get_object(mock_get_object: MagicMock, drs_object: dict, client: CGPClient):
    md5_hash: str = "MD5HASH"
    drs_object["checksums"][0]["checksum"] = md5_hash
    mock_get_object.return_value = DrsObject.model_validate(drs_object)

    with pytest.raises(CGPClientException):
        get_drs_object(
            drs_url=drs_object["id"],
            headers=client.headers,
            api_base_url=client.api_base_url,
            override_api_base_url=client.override_api_base_url,
        )

    with pytest.raises(CGPClientException):
        get_drs_object(
            drs_url=drs_object["self_uri"],
            headers=client.headers,
            api_base_url=client.api_base_url,
            override_api_base_url=client.override_api_base_url,
            expected_hash="foo",
        )

    # test we don't raise with no expected hash
    try:
        get_drs_object(
            drs_url=drs_object["self_uri"],
            headers=client.headers,
            api_base_url=client.api_base_url,
            override_api_base_url=client.override_api_base_url,
        )
    except CGPClientException:
        assert False

    drs_response: DrsObject = get_drs_object(
        drs_url=drs_object["self_uri"],
        api_base_url=client.api_base_url,
        override_api_base_url=client.override_api_base_url,
        headers=client.headers,
    )
    assert drs_response.model_dump(exclude_defaults=True) == drs_object
    mock_get_object.assert_called()


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
