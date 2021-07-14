import glob
import json
import os
import random
import re
import string
import time
import warnings
from datetime import datetime
from json import JSONDecodeError
from typing import Optional, Tuple, Iterable

import dns
import dns.name
import dns.query
import dns.rdtypes.svcbbase
import dns.zone
import pytest
import requests
from requests.exceptions import SSLError
from urllib3.exceptions import InsecureRequestWarning


def pytest_addoption(parser):
    parser.addoption(
        "--skip-performance-tests", action="store_true", default=False, help="skip expensive performance tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "performance: mark test as expensive performance test")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--skip-performance-tests"):
        skip_mark = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "performance" in item.keywords:
                item.add_marker(skip_mark)


def tsprint(s, *args, **kwargs):
    print(f"{datetime.now().strftime('%d-%b (%H:%M:%S)')} {s}", *args, **kwargs)


def _strip_quotes_decorator(func):
    return lambda *args, **kwargs: func(*args, **kwargs)[1:-1]


# Ensure that dnspython agrees with pdns' expectations for SVCB / HTTPS parameters.
# WARNING: This is a global side-effect. It can't be done by extending a class, because dnspython hardcodes the use of
# their dns.rdtypes.svcbbase.*Param classes in the global dns.rdtypes.svcbbase._class_for_key dictionary. We either have
# to globally mess with that dict and insert our custom class, or we just mess with their classes directly.
dns.rdtypes.svcbbase.ALPNParam.to_text = _strip_quotes_decorator(dns.rdtypes.svcbbase.ALPNParam.to_text)
dns.rdtypes.svcbbase.IPv4HintParam.to_text = _strip_quotes_decorator(dns.rdtypes.svcbbase.IPv4HintParam.to_text)
dns.rdtypes.svcbbase.IPv6HintParam.to_text = _strip_quotes_decorator(dns.rdtypes.svcbbase.IPv6HintParam.to_text)
dns.rdtypes.svcbbase.MandatoryParam.to_text = _strip_quotes_decorator(dns.rdtypes.svcbbase.MandatoryParam.to_text)
dns.rdtypes.svcbbase.PortParam.to_text = _strip_quotes_decorator(dns.rdtypes.svcbbase.PortParam.to_text)


def random_mixed_case_string(n):
    k = random.randint(1, n-1)
    s = random.choices(string.ascii_lowercase, k=k) + random.choices(string.ascii_uppercase, k=n-k)
    random.shuffle(s)
    return ''.join(s)


def random_email() -> str:
    return f'{random_mixed_case_string(10)}@{random_mixed_case_string(10)}.desec.test'


def random_password() -> str:
    return "".join(random.choice(string.ascii_letters) for _ in range(16))


def random_domainname(suffix='test') -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(16)) + f'.{suffix}'


class DeSECAPIV1Client:
    base_url = "https://desec." + os.environ["DESECSTACK_DOMAIN"] + "/api/v1"

    def __init__(self) -> None:
        super().__init__()
        self.headers = {  # instance-local
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "e2e2",
        }
        self.email = None
        self.password = None
        self.domains = {}

        # We support two certificate verification methods
        # (1) against self-signed certificates, if /autocert path is present
        # (this is usually the case when run inside a docker container)
        # (2) against the default certificate store, if /autocert is not available
        # (this is usually the case when run outside a docker container)
        self.verify = True
        self.verify_alt = glob.glob('/autocert/*.cer')

    @staticmethod
    def _filter_response_output(output: dict) -> dict:
        try:
            output['challenge'] = output['challenge'][:10] + '...'
        except (KeyError, TypeError):
            pass
        return output

    @property
    def domain(self):
        try:
            return next(iter(self.domains))
        except StopIteration:
            return None

    def _do_request(self, *args, **kwargs):
        if 'verify' in kwargs:
            verify_list = [kwargs.pop('verify')]
        elif faketime_get() != '+0d':
            # do not verify SSL if we're in faketime (cert will be expired!?)
            verify_list = [False]
        else:
            verify_list = [self.verify] + self.verify_alt

        exc = None
        for verify in verify_list:
            try:
                with warnings.catch_warnings():
                    if not verify:
                        # Suppress insecurity warning if we do not want to verify
                        warnings.filterwarnings('ignore', category=InsecureRequestWarning)
                    reply = requests.request(*args, **kwargs, verify=verify)
            except SSLError as e:
                tsprint(f'API <<< SSL could not verify against "{verify}"')
                exc = e
            else:
                # note verification preference for next time
                self.verify = verify
                self.verify_alt = verify_list
                self.verify_alt.remove(self.verify)
                return reply
        tsprint(f'API <<< SSL could not be verified against any verification method')
        raise exc

    def _request(self, method: str, *, path: str, data: Optional[dict] = None, **kwargs) -> requests.Response:
        if data is not None:
            data = json.dumps(data)

        url = self.base_url + path if re.match(r'^https?://', path) is None else path

        tsprint(f"API >>> {method} {url}")
        if data:
            tsprint(f"API >>> {type(data)}: {self._shorten(data)}")

        response = self._do_request(
            method,
            url,
            data=data,
            headers=self.headers,
            **kwargs,
        )

        tsprint(f"API <<< {response.status_code}")
        if response.text:
            try:
                tsprint(f"API <<< {self._shorten(str(self._filter_response_output(response.json())))}")
            except JSONDecodeError:
                tsprint(f"API <<< {response.text}")

        return response

    @staticmethod
    def _shorten(s: str):
        if len(s) < 200:
            return s
        else:
            return s[:50] + '...' + s[-50:]

    def get(self, path: str, **kwargs) -> requests.Response:
        return self._request("GET", path=path, **kwargs)

    def options(self, path: str, **kwargs) -> requests.Response:
        return self._request("OPTIONS", path=path, **kwargs)

    def post(self, path: str, data: Optional[dict] = None, **kwargs) -> requests.Response:
        return self._request("POST", path=path, data=data, **kwargs)

    def patch(self, path: str, data: Optional[dict] = None, **kwargs) -> requests.Response:
        return self._request("PATCH", path=path, data=data, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self._request("DELETE", path=path, **kwargs)

    def register(self, email: str, password: str) -> Tuple[requests.Response, requests.Response]:
        self.email = email
        self.password = password
        captcha = self.post("/captcha/")
        return captcha, self.post(
            "/auth/",
            data={
                "email": email,
                "password": password,
                "captcha": {
                    "id": captcha.json()["id"],
                    "solution": captcha.json()[
                        "content"
                    ],  # available via e2e configuration magic
                },
            },
        )

    def login(self, email: str, password: str) -> requests.Response:
        response = self.post(
            "/auth/login/", data={"email": email, "password": password}
        )
        self.token = response.json().get('token')
        if self.token is not None:
            self.headers["Authorization"] = f'Token {self.token}'
            self.patch(  # make token last forever
                f"/auth/tokens/{response.json().get('id')}/",
                data={'max_unused_period': None, 'max_age': None}
            )

        return response

    def domain_list(self) -> requests.Response:
        return self.get("/domains/").json()

    def domain_create(self, name) -> requests.Response:
        if name in self.domains:
            raise ValueError
        response = self.post("/domains/", data={"name": name})
        self.domains[name] = response.json()
        return response

    def domain_destroy(self, name) -> requests.Response:
        if name not in self.domains:
            raise ValueError
        response = self.delete(f"/domains/{name}/")
        self.domains.pop(name)
        return response

    def rr_set_create(self, domain_name: str, rr_type: str, records: Iterable[str], subname: str = '',
                      ttl: int = 3600) -> requests.Response:
        return self.post(
            f"/domains/{domain_name}/rrsets/",
            data={
                "subname": subname,
                "type": rr_type,
                "ttl": ttl,
                "records": records,
            }
        )

    def rr_set_create_bulk(self, domain_name: str, data: list) -> requests.Response:
        return self.patch(f"/domains/{domain_name}/rrsets/", data=data)

    def rr_set_delete(self, domain_name: str, rr_type: str, subname: str = '') -> requests.Response:
        return self.delete(f"/domains/{domain_name}/rrsets/{subname}.../{rr_type}/")

    def get_key_params(self, domain_name: str, rr_type: str) -> list:
        keys = self.domains[domain_name]['keys']
        if rr_type in ('CDNSKEY', 'DNSKEY'):
            params = {key['dnskey'] for key in keys}
        elif rr_type == 'CDS':
            params = {ds for key in keys for ds in key['ds']}
        else:
            raise ValueError

        # Split into four fields and remove additional spaces
        params = [map(lambda x: x.replace(' ', ''), param.split(' ', 3)) for param in params]

        # For (C)DNSKEY, add spaces every 32 characters
        if rr_type in ('CDNSKEY', 'DNSKEY'):
            params = [[a, b, c, ' '.join(d[i:i + 32] for i in range(0, len(d), 32))] for a, b, c, d in params]

        # Join again
        return {' '.join(param) for param in params}


class DeSECAPIV2Client(DeSECAPIV1Client):
    base_url = "https://desec." + os.environ["DESECSTACK_DOMAIN"] + "/api/v2"


@pytest.fixture
def api_anon() -> DeSECAPIV1Client:
    """
    Anonymous access to the API.
    """
    return DeSECAPIV1Client()


@pytest.fixture
def api_anon_v2() -> DeSECAPIV2Client:
    """
    Anonymous access to the API.
    """
    return DeSECAPIV2Client()


@pytest.fixture()
def api_user() -> DeSECAPIV1Client:
    """
    Access to the API with a fresh user account (zero domains, one token). Authorization header
    is preconfigured, email address and password are randomly chosen.
    """
    api = DeSECAPIV1Client()
    email = random_email()
    password = random_password()
    api.register(email, password)
    api.login(email, password)
    return api


@pytest.fixture()
def api_user_domain(api_user) -> DeSECAPIV1Client:
    """
    Access to the API with a fresh user account that owns a domain with random name. The domain has
    no records other than the default ones.
    """
    api_user.domain_create(random_domainname())
    return api_user


@pytest.fixture()
def api_user_domain_rrsets(api_user_domain, init_rrsets: dict) -> DeSECAPIV1Client:
    """
    Access to the API with a fresh user account that owns a domain with random name. The domain is
    equipped with RRsets from init_rrsets.
    """

    def _normalize_rrset(rrset, qtype):
        if qtype not in ('CDS', 'CDNSKEY', 'DNSKEY'):
            return rrset
        ttl, records = rrset
        return ttl, {' '.join(map(lambda x: x.replace(' ', ''), record.split(' ', 3))) for record in records}

    def _assert_rrsets(self, rrsets):
        rrsets_api = {
            (rrset['subname'], rrset['type']): (rrset['ttl'], set(rrset['records']))
            for rrset in self.get(f'/domains/{self.domain}/rrsets/').json()
        }
        rrsets_dns = {
            (subname, qtype): _normalize_rrset(NSLordClient.query(f'{subname}.{self.domain}'.lstrip('.'), qtype), qtype)
            for subname, qtype in rrsets.keys()
        }

        for k, v in rrsets.items():
            v = v or init_rrsets[k]  # if None, check against init_rrsets
            if not v[1]:
                assert k not in rrsets_api
                assert not rrsets_dns[k][1]
            else:
                assert rrsets_api[k] == v
                assert rrsets_dns[k] == v

    api_user_domain.assert_rrsets = _assert_rrsets.__get__(api_user_domain)  # very hacky way of adding a method

    api_user_domain.post(f"/domains/{api_user_domain.domain}/rrsets/", data=[
        {"subname": k[0], "type": k[1], "ttl": v[0], "records": list(v[1])}
        for k, v in init_rrsets.items()
    ])
    api_user_domain.assert_rrsets(init_rrsets)
    return api_user_domain


api_user_lps = api_user


@pytest.fixture()
def lps(api_user_lps) -> DeSECAPIV1Client:
    """
    Access to the API with a fresh user account that owns a local public suffix.
    """
    lps = "dedyn." + os.environ['DESECSTACK_DOMAIN']
    api_user_lps.domain_create(lps)  # may return 400 if exists, but that's ok
    return lps


@pytest.fixture()
def api_user_lps_domain(api_user, lps) -> DeSECAPIV1Client:
    """
    Access to the API with a fresh user account that owns a domain with random name under a local public suffix.
    The domain has no records other than the default ones.
    """
    api_user.domain_create(random_domainname(suffix=lps))
    return api_user


class NSClient:
    where = None

    @classmethod
    def query(cls, qname: str, qtype: str):
        tsprint(f'DNS >>> {qname}/{qtype} @{cls.where}')
        qname = dns.name.from_text(qname)
        qtype = dns.rdatatype.from_text(qtype)
        answer = dns.query.tcp(
            q=dns.message.make_query(qname, qtype),
            where=cls.where,
            timeout=2
        )
        try:
            section = dns.message.AUTHORITY if qtype == dns.rdatatype.from_text('NS') else dns.message.ANSWER
            response = answer.find_rrset(section, qname, dns.rdataclass.IN, qtype)
            tsprint(f'DNS <<< {response}')
            return response.ttl, {i.to_text() for i in response.items}
        except KeyError:
            tsprint('DNS <<< !!! not found !!! Complete Answer below:\n' + answer.to_text())
            return None, set()


class NSLordClient(NSClient):
    where = os.environ["DESECSTACK_IPV4_REAR_PREFIX16"] + '.0.129'


def query_replication(zone: str, qname: str, qtype: str, covers: str = None):
    if qtype == 'RRSIG':
        assert covers, 'If querying RRSIG, covers parameter must be set to a RR type, e.g. SOA.'
    else:
        assert not covers
        covers = dns.rdatatype.NONE

    zonefile = os.path.join('/zones', zone + '.zone')
    zone = dns.name.from_text(zone, origin=dns.name.root)
    qname = dns.name.from_text(qname, origin=zone)

    if not os.path.exists(zonefile):
        tsprint(f'RPL <<< Zone file for {zone} not found '
                f'(number of zones: {len(list(filter(lambda f: f.endswith(".zone"), os.listdir("/zones"))))})')
        return None

    try:
        tsprint(f'RPL >>> {qname}/{qtype} in {zone}')
        z = dns.zone.from_file(f=zonefile, origin=zone, relativize=False)
        v = {i.to_text() for i in z.find_rrset(qname, qtype, covers=covers).items}
        tsprint(f'RPL <<< {v}')
        return v
    except KeyError:
        tsprint(f'RPL <<< RR Set {qname}/{qtype} not found')
        return {}
    except dns.zone.NoSOA:
        tsprint(f'RPL <<< Zone {zone} not found')
        return None


def return_eventually(expression: callable, min_pause: float = .1, max_pause: float = 2, timeout: float = 5,
                      retry_on: Tuple[type] = (Exception,)):
    if not callable(expression):
        raise ValueError('Expression given not callable. Did you forget "lambda:"?')

    wait = min_pause
    started = datetime.now()
    while True:
        try:
            return expression()
        except retry_on as e:
            if (datetime.now() - started).total_seconds() > timeout:
                tsprint(f'{expression.__code__} failed with {e}, no more retries')
                raise e
            time.sleep(wait)
            wait = min(2 * wait, max_pause)


def assert_eventually(assertion: callable, min_pause: float = .1, max_pause: float = 2, timeout: float = 5,
                      retry_on: Tuple[type] = (AssertionError,)) -> None:
    def _assert():
        assert assertion()
    return_eventually(_assert, min_pause, max_pause, timeout, retry_on=retry_on)


def faketime(t: str):
    print('FAKETIME', t)
    with open('/etc/faketime/faketime.rc', 'w') as f:
        f.write(t + '\n')


def faketime_get():
    try:
        with open('/etc/faketime/faketime.rc', 'r') as f:
            return f.readline().strip()
    except FileNotFoundError:
        return '+0d'


class FaketimeShift:
    def __init__(self, days: int):
        assert days >= 0
        self.days = days

    def __enter__(self):
        self._faketime = faketime_get()
        assert self._faketime[0] == '+'
        assert self._faketime[-1] == 'd'
        current_days = int(self._faketime[1:-1])

        faketime(f'+{current_days + self.days:n}d')

    def __exit__(self, type, value, traceback):
        faketime(self._faketime)
