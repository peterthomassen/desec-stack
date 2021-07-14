import os

from conftest import DeSECAPIV1Client, DeSECAPIV2Client


def test_homepage(api_anon: DeSECAPIV1Client):
    assert api_anon.get("/").json() == {
        "register": f"{api_anon.base_url}/auth/",
        "login": f"{api_anon.base_url}/auth/login/",
        "reset-password": f"{api_anon.base_url}/auth/account/reset-password/",
    }

def test_homepage_CORS(api_anon: DeSECAPIV1Client):
    api_anon.headers['Origin'] = 'http://foo.example'
    assert api_anon.get("/").headers['access-control-allow-origin'] == '*'

    api_anon.headers['Access-Control-Request-Headers'] = 'Authorization'
    api_anon.headers['Access-Control-Request-Method'] = 'POST'
    assert 'authorization' in api_anon.options("/").headers['access-control-allow-headers'].split(', ')


def test_homepage_v2(api_anon_v2: DeSECAPIV2Client):
    assert api_anon_v2.get("/").json() == {
        "register": f"{api_anon_v2.base_url}/auth/",
        "login": f"{api_anon_v2.base_url}/auth/login/",
        "reset-password": f"{api_anon_v2.base_url}/auth/account/reset-password/",
    }


def test_get_desec_io(api_anon: DeSECAPIV1Client):
    response = api_anon.get("https://get.desec." + os.environ['DESECSTACK_DOMAIN'], allow_redirects=False)
    assert 300 < response.status_code < 400
    assert response.headers['Location'] == f"https://desec.{os.environ['DESECSTACK_DOMAIN']}/"
