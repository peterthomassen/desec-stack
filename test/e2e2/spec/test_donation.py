from conftest import DeSECAPIV1Client

import pytest
from pytest_schema import schema, Optional


donation = {
    'name': str,
    'iban': str,
    'bic': str,
    'amount': str,
    'mref': str,
    'interval': int,
    'message': str,
    'email': str,
}


@pytest.mark.parametrize("data", [
    {
        "name": "Drama Queen",
        "iban": "DE89 3704 0044 0532 0130 00",
        "bic": "MARKDEF1100",
        "amount": "3.14",
        "message": "foobar",
        "email": "drama@queen.world",
    },
    {
        "name": "Drama Queen",
        "iban": "DE89370400440532013000",
        "bic": "MARKDEF1100",
        "amount": "3.14",
    },
])
def test_response(api_anon: DeSECAPIV1Client, data):
    response = api_anon.post("/donation/", data=data)
    assert response.status_code == 201
    assert schema(donation, ignore_extra_keys=False) == response.json()


@pytest.mark.skip(reason="not sure how to test")
def test_confirmation_email():
    pass
