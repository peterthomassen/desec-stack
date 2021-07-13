import base64
import operator
import random
import re
import string
from contextlib import nullcontext
from functools import partial, reduce
from json import JSONDecodeError
from typing import Union, List, Dict
from unittest import mock

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import connection
from httpretty import httpretty, core as hr_core
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework.utils import json

from desecapi import replication
from desecapi.models import User, Domain, Token, RRset, RR, psl, RR_SET_TYPES_AUTOMATIC, RR_SET_TYPES_UNSUPPORTED, \
    RR_SET_TYPES_MANAGEABLE


class DesecAPIClient(APIClient):

    @staticmethod
    def _http_header_base64_conversion(content):
        return base64.b64encode(content.encode()).decode()

    def set_credentials(self, authorization):
        self.credentials(HTTP_AUTHORIZATION=authorization)

    def set_credentials_basic_auth(self, part_1, part_2=None):
        if not part_1 and not part_2:
            self.set_credentials('')
        else:
            s = part_1 if not part_2 else '%s:%s' % (part_1, part_2)
            self.set_credentials('Basic ' + self._http_header_base64_conversion(s))

    def set_credentials_token_auth(self, token):
        if token is None:
            self.set_credentials('')
        else:
            self.set_credentials('Token ' + token)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reverse = DesecTestCase.reverse

    def bulk_patch_rr_sets(self, domain_name, payload):
        return self.patch(
            self.reverse('v1:rrsets', name=domain_name),
            payload,
        )

    def bulk_post_rr_sets(self, domain_name, payload):
        return self.post(
            self.reverse('v1:rrsets', name=domain_name),
            payload,
        )

    def bulk_put_rr_sets(self, domain_name, payload):
        return self.put(
            self.reverse('v1:rrsets', name=domain_name),
            payload,
        )

    def post_rr_set(self, domain_name, **kwargs):
        data = kwargs or None
        if data:
            data.setdefault('ttl', 60)
        return self.post(
            self.reverse('v1:rrsets', name=domain_name),
            data=data,
        )

    def get_rr_sets(self, domain_name, **kwargs):
        return self.get(
            self.reverse('v1:rrsets', name=domain_name) + kwargs.pop('query', ''),
            kwargs
        )

    def get_rr_set(self, domain_name, subname, type_):
        return self.get(
            self.reverse('v1:rrset@', name=domain_name, subname=subname, type=type_)
        )

    def put_rr_set(self, domain_name, subname, type_, data):
        return self.put(
            self.reverse('v1:rrset@', name=domain_name, subname=subname, type=type_),
            data
        )

    def patch_rr_set(self, domain_name, subname, type_, data):
        return self.patch(
            self.reverse('v1:rrset@', name=domain_name, subname=subname, type=type_),
            data
        )

    def delete_rr_set(self, domain_name, subname, type_):
        return self.delete(
            self.reverse('v1:rrset@', name=domain_name, subname=subname, type=type_)
        )

    # TODO add and use {post,get,delete,...}_domain


class SQLiteReadUncommitted:

    def __init__(self):
        self.read_uncommitted = None

    def __enter__(self):
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA read_uncommitted;')
            self.read_uncommitted = True if cursor.fetchone()[0] else False
            cursor.execute('PRAGMA read_uncommitted = true;')

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.read_uncommitted is None:
            return

        with connection.cursor() as cursor:
            if self.read_uncommitted:
                cursor.execute('PRAGMA read_uncommitted = true;')
            else:
                cursor.execute('PRAGMA read_uncommitted = false;')


class AssertRequestsContextManager:
    """
    Checks that in its context, certain expected requests are made.
    """

    @classmethod
    def _flatten_nested_lists(cls, l):
        for i in l:
            if isinstance(i, list) or isinstance(i, tuple):
                yield from cls._flatten_nested_lists(i)
            else:
                yield i

    def __init__(self, test_case, expected_requests, single_expectation_single_request=True, expect_order=True,
                 exit_hook=None):
        """
        Initialize a context that checks for made HTTP requests.

        Args:
            test_case: Test case in which this context lives. Used to fail test if observed requests do not meet
            expectations.
            expected_requests: (Possibly nested) list of requests, represented by kwarg-dictionaries for
            `httpretty.register_uri`.
            single_expectation_single_request: If True (default), each expected request needs to be matched by exactly
            one observed request.
            expect_order: If True (default), requests made are expected in order of expectations given.
        """
        self.test_case = test_case
        self.expected_requests = list(self._flatten_nested_lists(expected_requests))
        self.single_expectation_single_request = single_expectation_single_request
        self.expect_order = expect_order
        self.old_httpretty_entries = None
        self.exit_hook = exit_hook

    def __enter__(self):
        hr_core.POTENTIAL_HTTP_PORTS.add(8081)  # FIXME should depend on self.expected_requests
        # noinspection PyProtectedMember
        self.old_httpretty_entries = httpretty._entries.copy()  # FIXME accessing private properties of httpretty
        for request in self.expected_requests:
            httpretty.register_uri(**request)

    @staticmethod
    def _find_matching_request(pattern, requests):
        for request in requests:
            if pattern['method'] == request[0] and pattern['uri'].match(request[1]):
                if pattern.get('payload') and pattern['payload'] not in request[2]:
                    continue
                return request
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        # call exit hook
        if callable(self.exit_hook):
            self.exit_hook()

        # organize seen requests in a primitive data structure
        seen_requests = [
            (r.command, 'http://%s%s' % (r.headers['Host'], r.path), r.parsed_body) for r in httpretty.latest_requests
        ]
        httpretty.reset()
        hr_core.POTENTIAL_HTTP_PORTS.add(8081)  # FIXME should depend on self.expected_requests
        httpretty._entries = self.old_httpretty_entries
        unmatched_requests = seen_requests[:]

        # go through expected requests one by one
        requests_to_check = list(self.expected_requests)[:]
        while requests_to_check:
            request = requests_to_check.pop(0)

            # match request
            match = None
            if self.expect_order:
                if not self.single_expectation_single_request:
                    raise ValueError(
                        'Checking of multiple (possibly zero) requests per expectation and checking of request '
                        'order simultaneously is not implemented, sorry.')
                if unmatched_requests:
                    match = self._find_matching_request(request, [unmatched_requests[0]])
            else:
                match = self._find_matching_request(
                    request, unmatched_requests if self.single_expectation_single_request else seen_requests)

            # check match
            if not match and self.single_expectation_single_request:
                self.test_case.fail(('Expected to see a %s request on\n\n%s,\n\nbut only saw these %i '
                                     'requests:\n\n%s\n\nAll expected requests:\n\n%s\n\n'
                                     'Hint: check for possible duplicates in your expectation.\n' +
                                     ('Hint: Is the expectation order correct?' if self.expect_order else '')) % (
                                        request['method'], request['uri'], len(seen_requests),
                                        '\n'.join(map(str, seen_requests)),
                                        '\n'.join(map(str, [(r['method'], r['uri']) for r in self.expected_requests])),
                                     ))
            if match:
                unmatched_requests.remove(match)

        # see if any requests were unexpected
        if unmatched_requests and self.single_expectation_single_request:
            self.test_case.fail('While waiting for %i request(s), we saw %i unexpected request(s). The unexpected '
                                'request(s) was/were:\n\n%s\n\nAll recorded requests:\n\n%s\n\nAll expected requests:'
                                '\n\n%s' % (
                                    len(self.expected_requests),
                                    len(unmatched_requests),
                                    '\n'.join(map(str, unmatched_requests)),
                                    '\n'.join(map(str, seen_requests)),
                                    '\n'.join(map(str, [(r['method'], r['uri']) for r in self.expected_requests])),
                                ))


class MockPDNSTestCase(APITestCase):
    """
    This test case provides a "mocked Internet" environment with a mock pdns API interface. All internet connections,
    HTTP or otherwise, that this test case is unaware of will result in an exception.

    By default, requests are intercepted but unexpected will result in a failed test. To set pdns API request
    expectations, use the `with MockPDNSTestCase.assertPdns*` context managers.

    Subclasses may not touch httpretty.enable() or httpretty.disable(). For 'local' usage, httpretty.register_uri()
    and httpretty.reset() may be used.
    """

    PDNS_ZONES = r'/zones\?rrsets=false'
    PDNS_ZONE_CRYPTO_KEYS = r'/zones/(?P<id>[^/]+)/cryptokeys'
    PDNS_ZONE = r'/zones/(?P<id>[^/]+)'
    PDNS_ZONE_AXFR = r'/zones/(?P<id>[^/]+)/axfr-retrieve'

    @classmethod
    def get_full_pdns_url(cls, path_regex, ns='LORD', **kwargs):
        api = getattr(settings, 'NS%s_PDNS_API' % ns)
        return re.compile('^' + api + cls.fill_regex_groups(path_regex, **kwargs) + '$')

    @classmethod
    def fill_regex_groups(cls, template, **kwargs):
        s = template
        for name, value in kwargs.items():
            if value is None:
                continue
            pattern = r'\(\?P\<%s\>[^\)]+\)' % name
            if not re.search(pattern, s):
                raise ValueError('Tried to fill field %s in template %s, but it does not exist.' % (name, template))
            s = re.sub(
                pattern=pattern,
                repl=value,
                string=s,
            )

        return s

    @classmethod
    def _pdns_zone_id_heuristic(cls, name):
        """
        Returns an educated guess of the pdns zone id for a given zone name.
        """
        if not name:
            return None

        name = cls._normalize_name(name)

        return name.translate(str.maketrans({'/': '=2F', '_': '=5F'}))  # make sure =5F is not lower-cased

    @classmethod
    def _normalize_name(cls, arg):
        if not arg:
            return None

        if not isinstance(arg, list):
            return cls._normalize_name([arg])[0]
        else:
            return [x.rstrip('.') + '.' for x in arg]

    @classmethod
    def request_pdns_zone_create(cls, ns, **kwargs):
        return {
            'method': 'POST',
            'uri': cls.get_full_pdns_url(cls.PDNS_ZONES, ns=ns),
            'status': 201,
            'body': '',
            'match_querystring': True,
            **kwargs
        }

    def request_pdns_zone_create_assert_name(self, ns, name):
        def request_callback(r, _, response_headers):
            body = json.loads(r.parsed_body)
            self.failIf('name' not in body.keys(),
                        'pdns domain creation request malformed: did not contain a domain name.')

            try:  # if an assertion fails, an exception is raised. We want to send a reply anyway!
                self.assertEqual(name, body['name'], 'Expected to see a domain creation request with name %s, '
                                                     'but name %s was sent.' % (name, body['name']))
            finally:
                return [201, response_headers, '']

        request = self.request_pdns_zone_create(ns)
        request.pop('status')
        # noinspection PyTypeChecker
        request['body'] = request_callback
        return request

    @classmethod
    def request_pdns_zone_create_422(cls):
        request = cls.request_pdns_zone_create(ns='LORD')
        request['status'] = 422
        return request

    @classmethod
    def request_pdns_zone_delete(cls, name=None, ns='LORD'):
        return {
            'method': 'DELETE',
            'uri': cls.get_full_pdns_url(cls.PDNS_ZONE, ns=ns, id=cls._pdns_zone_id_heuristic(name)),
            'status': 200,
            'body': '',
        }

    @classmethod
    def request_pdns_zone_update(cls, name=None):
        return {
            'method': 'PATCH',
            'uri': cls.get_full_pdns_url(cls.PDNS_ZONE, id=cls._pdns_zone_id_heuristic(name)),
            'status': 200,
            'body': '',
        }

    def request_pdns_zone_update_assert_body(self, name: str = None, updated_rr_sets: Union[List[RRset], Dict] = None):
        if updated_rr_sets is None:
            updated_rr_sets = []

        def request_callback(r, _, response_headers):
            if not updated_rr_sets:
                # nothing to assert
                return [200, response_headers, '']

            body = json.loads(r.parsed_body)
            self.failIf('rrsets' not in body.keys(),
                        'pdns zone update request malformed: did not contain a list of RR sets.')

            try:  # if an assertion fails, an exception is raised. We want to send a reply anyway!
                with SQLiteReadUncommitted():  # tests are wrapped in uncommitted transactions, so we need to see inside
                    # convert updated_rr_sets into a plain data type, if Django models were given
                    if isinstance(updated_rr_sets, list):
                        updated_rr_sets_dict = {}
                        for rr_set in updated_rr_sets:
                            updated_rr_sets_dict[(rr_set.type, rr_set.subname, rr_set.ttl)] = rrs = []
                            for rr in rr_set.records.all():
                                rrs.append(rr.content)
                    elif isinstance(updated_rr_sets, dict):
                        updated_rr_sets_dict = updated_rr_sets
                    else:
                        raise ValueError('updated_rr_sets must be a list of RRSets or a dict.')

                    # check expectations
                    self.assertEqual(len(updated_rr_sets_dict), len(body['rrsets']),
                                     'Saw an unexpected number of RR set updates: expected %i, intercepted %i.' %
                                     (len(updated_rr_sets_dict), len(body['rrsets'])))
                    for (exp_type, exp_subname, exp_ttl), exp_records in updated_rr_sets_dict.items():
                        expected_name = '.'.join(filter(None, [exp_subname, name])) + '.'
                        for seen_rr_set in body['rrsets']:
                            if (expected_name == seen_rr_set['name'] and
                                    exp_type == seen_rr_set['type']):
                                # TODO replace the following asserts by assertTTL, assertRecords, ... or similar
                                if len(exp_records):
                                    self.assertEqual(exp_ttl, seen_rr_set['ttl'])
                                self.assertEqual(
                                    set(exp_records),
                                    set([rr['content'] for rr in seen_rr_set['records']]),
                                )
                                break
                        else:
                            # we did not break out, i.e. we did not find a matching RR set in body['rrsets']
                            self.fail('Expected to see an pdns zone update request for RR set of domain `%s` with name '
                                      '`%s` and type `%s`, but did not see one. Seen update request on %s for RR sets:'
                                      '\n\n%s'
                                      % (name, expected_name, exp_type, request['uri'],
                                         json.dumps(body['rrsets'], indent=4)))
            finally:
                return [200, response_headers, '']

        request = self.request_pdns_zone_update(name)
        request.pop('status')
        # noinspection PyTypeChecker
        request['body'] = request_callback
        return request

    @classmethod
    def request_pdns_zone_retrieve(cls, name=None):
        return {
            'method': 'GET',
            'uri': cls.get_full_pdns_url(cls.PDNS_ZONE, id=cls._pdns_zone_id_heuristic(name)),
            'status': 200,
            'body': json.dumps({
                'rrsets': [{
                    'comments': [],
                    'name': cls._normalize_name(name) if name else 'test.mock.',
                    'ttl': 60,
                    'type': 'NS',
                    'records': [{'content': ns} for ns in settings.DEFAULT_NS],
                }]
            }),
        }

    @classmethod
    def request_pdns_zone_retrieve_crypto_keys(cls, name=None):
        return {
            'method': 'GET',
            'uri': cls.get_full_pdns_url(cls.PDNS_ZONE_CRYPTO_KEYS, id=cls._pdns_zone_id_heuristic(name)),
            'status': 200,
            'body': json.dumps([
                {
                    'algorithm': 'ECDSAP256SHA256',
                    'bits': 256,
                    'dnskey': '257 3 13 EVBcsqrnOp6RGWtsrr9QW8cUtt/'
                              'WI5C81RcCZDTGNI9elAiMQlxRdnic+7V+b7jJDE2vgY08qAbxiNh5NdzkzA==',
                    'cds': [
                        '62745 13 2 5cddaeaa383e2ea7de49bd1212bf520228f0e3b334626517e5f6a68eb85b48f6',
                        '62745 13 4 b3f2565901ddcb0b78337301cf863d1045774377bca05c7ad69e17a167734b92'
                        '9f0a49b7edcca913eb6f5dfeac4645b8'
                    ],
                    'flags': 257,
                    'id': 179425943,
                    'keytype': key_type,
                    'published': True,
                    'type': 'Cryptokey',
                }
                for key_type in ['csk', 'ksk', 'zsk']
            ])
        }

    @classmethod
    def request_pdns_zone_axfr(cls, name=None):
        return {
            'method': 'PUT',
            'uri': cls.get_full_pdns_url(cls.PDNS_ZONE_AXFR, ns='MASTER', id=cls._pdns_zone_id_heuristic(name)),
            'status': 200,
            'body': '',
        }

    @classmethod
    def request_pdns_update_catalog(cls):
        return {
            'method': 'PATCH',
            'uri': cls.get_full_pdns_url(cls.PDNS_ZONE, ns='MASTER', id=cls._pdns_zone_id_heuristic('catalog.internal')),
            'status': 204,
            'body': '',
            'priority': 1,  # avoid collision with DELETE zones/(?P<id>[^/]+)$ (httpretty does not match the method)
        }

    def __init__(self, methodName: str = ...) -> None:
        super().__init__(methodName)
        self._mock_replication = None

    def assertPdnsRequests(self, *expected_requests, expect_order=True, exit_hook=None):
        """
        Assert the given requests are made. To build requests, use the `MockPDNSTestCase.request_*` functions.
        Unmet expectations will fail the test.
        Args:
            *expected_requests: List of expected requests.
            expect_order: If True (default), the order of observed requests is checked.
            exit_hook: If given a callable, it is called when the context manager exits.
        """
        return AssertRequestsContextManager(
            test_case=self,
            expected_requests=expected_requests,
            expect_order=expect_order,
            exit_hook=exit_hook,
        )

    def assertPdnsNoRequestsBut(self, *expected_requests):
        """
        Assert no requests other than the given ones are made. Each request can be matched more than once, unmatched
        expectations WILL NOT fail the test.
        Args:
            *expected_requests: List of acceptable requests to be made.
        """
        return AssertRequestsContextManager(
            test_case=self,
            expected_requests=expected_requests,
            single_expectation_single_request=False,
            expect_order=False,
        )

    def assertPdnsZoneCreation(self):
        """
        Asserts that nslord is contact and a zone is created.
        """
        return AssertRequestsContextManager(
            test_case=self,
            expected_requests=[
                self.request_pdns_zone_create(ns='LORD'),
                self.request_pdns_zone_create(ns='MASTER')
            ],
        )

    def assertPdnsZoneDeletion(self, name=None):
        """
        Asserts that nslord and nsmaster are contacted to delete a zone.
        Args:
            name: If given, the test is restricted to the name of this zone.
        """
        return AssertRequestsContextManager(
            test_case=self,
            expected_requests=[
                self.request_pdns_zone_delete(ns='LORD', name=name),
                self.request_pdns_zone_delete(ns='MASTER', name=name),
            ],
        )

    def assertStatus(self, response, status):
        if response.status_code != status:
            self.fail((
                'Expected a response with status %i, but saw response with status %i. ' +
                (
                    '\n@@@@@ THE REQUEST CAUSING THIS RESPONSE WAS UNEXPECTED BY THE TEST @@@@@\n'
                    if response.status_code == 599 else ''
                ) +
                'The response was %s.\n'
                'The response body was\n\n%s') % (
                      status,
                      response.status_code,
                      response,
                      str(response.data).replace('\\n', '\n') if hasattr(response, 'data') else '',
                ))

    def assertResponse(self, response, code=None, body=None):
        if code:
            self.assertStatus(response, code)
        if body:
            self.assertJSONEqual(response.content, body)

    def assertToken(self, plain, user=None):
        user = user or self.owner
        self.assertTrue(any(check_password(plain, hashed, preferred='pbkdf2_sha256_iter1')
                            for hashed in Token.objects.filter(user=user).values_list('key', flat=True)))
        self.assertEqual(len(Token.make_hash(plain).split('$')), 4)

    def assertReplication(self, name):
        replication.update.delay.assert_called_with(name)

    @classmethod
    def setUpTestData(cls):
        httpretty.enable(allow_net_connect=False)
        httpretty.reset()
        hr_core.POTENTIAL_HTTP_PORTS.add(8081)  # FIXME static dependency on settings variable
        for request in [
            cls.request_pdns_zone_create(ns='LORD'),
            cls.request_pdns_zone_create(ns='MASTER'),
            cls.request_pdns_zone_axfr(),
            cls.request_pdns_zone_update(),
            cls.request_pdns_zone_retrieve_crypto_keys(),
            cls.request_pdns_zone_retrieve()
        ]:
            httpretty.register_uri(**request)
        cls.setUpTestDataWithPdns()
        httpretty.reset()

    @classmethod
    def setUpTestDataWithPdns(cls):
        """
        Override this method to set up test data. During the run of this method, httpretty is configured to accept
        all pdns API requests.
        """
        pass

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        httpretty.disable()

    def setUp(self):
        # configure mocks for nslord
        def request_callback(r, _, response_headers):
            try:
                request = json.loads(r.parsed_body)
            except JSONDecodeError:
                request = r.parsed_body

            return [
                599,
                response_headers,
                json.dumps(
                    {
                        'MockPDNSTestCase': 'This response was generated upon an unexpected request.',
                        'request': request,
                        'method': str(r.method),
                        'requestline': str(r.raw_requestline),
                        'host': str(r.headers['Host']) if 'Host' in r.headers else None,
                        'headers': {str(key): str(value) for key, value in r.headers.items()},
                    },
                    indent=4
                )
            ]

        super().setUp()
        httpretty.reset()
        hr_core.POTENTIAL_HTTP_PORTS.add(8081)  # FIXME should depend on self.expected_requests
        for method in [
            httpretty.GET, httpretty.PUT, httpretty.POST, httpretty.DELETE, httpretty.HEAD, httpretty.PATCH,
            httpretty.OPTIONS, httpretty.CONNECT
        ]:
            for ns in ['LORD', 'MASTER']:
                httpretty.register_uri(
                    method,
                    self.get_full_pdns_url('.*', ns),
                    body=request_callback,
                    status=599,
                    priority=-100,
                )

        # configure mocks for replication
        self._mock_replication = mock.patch('desecapi.replication.update.delay', return_value=None, wraps=None)
        self._mock_replication.start()

    def tearDown(self) -> None:
        if self._mock_replication:
            self._mock_replication.stop()
        super().tearDown()


class DesecTestCase(MockPDNSTestCase):
    """
    This test case is run in the "standard" deSEC e.V. setting, i.e. with an API that is aware of the public suffix
    domains AUTO_DELEGATION_DOMAINS.

    The test case aims to be as close to the deployment as possible and may be extended as the deployment evolves.

    The test case provides an admin user and a regular user for testing.
    """
    client_class = DesecAPIClient

    AUTO_DELEGATION_DOMAINS = settings.LOCAL_PUBLIC_SUFFIXES
    PUBLIC_SUFFIXES = {'de', 'com', 'io', 'gov.cd', 'edu.ec', 'xxx', 'pinb.gov.pl', 'valer.ostfold.no',
                       'kota.aichi.jp', 's3.amazonaws.com', 'wildcard.ck'}
    SUPPORTED_RR_SET_TYPES = {
        'A', 'AAAA', 'AFSDB', 'APL', 'CAA', 'CDNSKEY', 'CDS', 'CERT', 'CNAME', 'DHCID', 'DNAME', 'DNSKEY', 'DLV', 'DS',
        'EUI48', 'EUI64', 'HINFO', 'HTTPS', 'KX', 'LOC', 'MX', 'NAPTR', 'NS', 'OPENPGPKEY', 'PTR', 'RP', 'SMIMEA',
        'SPF', 'SRV', 'SSHFP', 'SVCB', 'TLSA', 'TXT', 'URI',
    }

    admin = None
    auto_delegation_domains = None
    user = None

    @classmethod
    def reverse(cls, view_name, **kwargs):
        return reverse(view_name, kwargs=kwargs)

    @classmethod
    def setUpTestDataWithPdns(cls):
        super().setUpTestDataWithPdns()
        random.seed(0xde5ec)
        cls.admin = cls.create_user(is_admin=True)
        cls.auto_delegation_domains = [cls.create_domain(name=name) for name in cls.AUTO_DELEGATION_DOMAINS]
        cls.user = cls.create_user()

    @classmethod
    def random_string(cls, length=6, chars=string.ascii_letters + string.digits):
        return ''.join(random.choice(chars) for _ in range(length))

    @classmethod
    def random_password(cls, length=12):
        return cls.random_string(
            length,
            chars=string.ascii_letters + string.digits + string.punctuation +
            'some 💩🐬 UTF-8: “红色联合”对“四·二八兵团”总部大楼的攻击已持续了两天"'
        )

    @classmethod
    def random_ip(cls, proto=None):
        proto = proto or random.choice([4, 6])
        if proto == 4:
            return '.'.join([str(random.randrange(256)) for _ in range(4)])
        elif proto == 6:
            return '2001:' + ':'.join(['%x' % random.randrange(16**4) for _ in range(7)])
        else:
            raise ValueError('Unknown IP protocol version %s. Expected int 4 or int 6.' % str(proto))

    @classmethod
    def random_username(cls, host=None):
        host = host or cls.random_domain_name(cls.PUBLIC_SUFFIXES)
        return cls.random_string() + '+test@' + host.lower()

    @classmethod
    def random_domain_name(cls, suffix=None):
        if not suffix:
            suffix = cls.PUBLIC_SUFFIXES
        if isinstance(suffix, set):
            suffix = random.sample(suffix, 1)[0]
        return (random.choice(string.ascii_letters) + cls.random_string() + '--test' + '.' + suffix).lower()

    @classmethod
    def has_local_suffix(cls, domain_name: str):
        return any([domain_name.endswith(f'.{suffix}') for suffix in settings.LOCAL_PUBLIC_SUFFIXES])

    @classmethod
    def create_token(cls, user, name=''):
        token = Token.objects.create(user=user, name=name)
        token.save()
        return token

    @classmethod
    def create_user(cls, needs_captcha=False, **kwargs):
        kwargs.setdefault('email', cls.random_username())
        user = User(needs_captcha=needs_captcha, **kwargs)
        user.plain_password = cls.random_string(length=12)
        user.set_password(user.plain_password)
        user.save()
        return user

    @classmethod
    def create_domain(cls, suffix=None, **kwargs):
        kwargs.setdefault('owner', cls.create_user())
        kwargs.setdefault('name', cls.random_domain_name(suffix))
        domain = Domain(**kwargs)
        domain.save()
        return domain

    @classmethod
    def create_rr_set(cls, domain, records, **kwargs):
        if isinstance(domain, str):
            domain = Domain.objects.get(name=domain)
            domain.save()
        rr_set = RRset(domain=domain, **kwargs)
        rr_set.save()
        for r in records:
            RR(content=r, rrset=rr_set).save()
        return rr_set

    @classmethod
    def _find_auto_delegation_zone(cls, name):
        if not name:
            return None
        parents = [parent for parent in cls.AUTO_DELEGATION_DOMAINS if name.endswith('.' + parent)]
        if not parents:
            raise ValueError('Could not find auto delegation zone for zone %s; searched in %s' % (
                name,
                cls.AUTO_DELEGATION_DOMAINS
            ))
        return parents[0]

    @classmethod
    def requests_desec_domain_creation(cls, name=None):
        soa_content = 'get.desec.io. get.desec.io. 1 86400 86400 2419200 3600'
        return [
            cls.request_pdns_zone_create(ns='LORD', payload=soa_content),
            cls.request_pdns_zone_create(ns='MASTER'),
            cls.request_pdns_update_catalog(),
            cls.request_pdns_zone_axfr(name=name),
            cls.request_pdns_zone_retrieve_crypto_keys(name=name),
        ]

    @classmethod
    def requests_desec_domain_deletion(cls, domain):
        requests = [
            cls.request_pdns_zone_delete(name=domain.name, ns='LORD'),
            cls.request_pdns_zone_delete(name=domain.name, ns='MASTER'),
            cls.request_pdns_update_catalog(),
        ]

        if domain.is_locally_registrable:
            delegate_at = cls._find_auto_delegation_zone(domain.name)
            requests += [
                cls.request_pdns_zone_update(name=delegate_at),
                cls.request_pdns_zone_axfr(name=delegate_at),
            ]

        return requests

    @classmethod
    def requests_desec_domain_creation_auto_delegation(cls, name=None):
        delegate_at = cls._find_auto_delegation_zone(name)
        return cls.requests_desec_domain_creation(name=name) + [
            cls.request_pdns_zone_update(name=delegate_at),
            cls.request_pdns_zone_axfr(name=delegate_at),
        ]

    @classmethod
    def requests_desec_rr_sets_update(cls, name=None):
        return [
            cls.request_pdns_zone_update(name=name),
            cls.request_pdns_zone_axfr(name=name),
        ]

    def assertRRSet(self, response_rr, domain=None, subname=None, records=None, type_=None, **kwargs):
        kwargs['domain'] = domain
        kwargs['subname'] = subname
        kwargs['records'] = records
        kwargs['type'] = type_

        for key, value in kwargs.items():
            if value is not None:
                self.assertEqual(
                    response_rr[key], value,
                    'RR set did not have the expected %s: Expected "%s" but was "%s" in %s' % (
                        key, value, response_rr[key], response_rr
                    )
                )

    @staticmethod
    def _count_occurrences_by_mask(rr_sets, masks):
        def _cmp(key, a, b):
            if key == 'records':
                a = sorted(a)
                b = sorted(b)
            return a == b

        def _filter_rr_sets_by_mask(rr_sets_, mask):
            return [
                rr_set for rr_set in rr_sets_
                if reduce(operator.and_, [_cmp(key, rr_set.get(key, None), value) for key, value in mask.items()])
            ]

        return [len(_filter_rr_sets_by_mask(rr_sets, mask)) for mask in masks]

    def assertRRSetsCount(self, rr_sets, masks, count=1):
        actual_counts = self._count_occurrences_by_mask(rr_sets, masks)
        if not all([actual_count == count for actual_count in actual_counts]):
            self.fail('Expected to find %i RR set(s) for each of %s, but distribution is %s in %s.' % (
                count, masks, actual_counts, rr_sets
            ))

    def assertContainsRRSets(self, rr_sets_haystack, rr_sets_needle):
        if not all(self._count_occurrences_by_mask(rr_sets_haystack, rr_sets_needle)):
            self.fail('Expected to find RR sets with %s, but only got %s.' % (
                rr_sets_needle, rr_sets_haystack
            ))

    def assertContains(self, response, text, count=None, status_code=200, msg_prefix='', html=False):
        # convenience method to check the status separately, which yields nicer error messages
        self.assertStatus(response, status_code)
        # same for the substring check
        self.assertIn(text, response.content.decode(response.charset),
                      f'Could not find {text} in the following response:\n{response.content.decode(response.charset)}')
        return super().assertContains(response, text, count, status_code, msg_prefix, html)

    def assertAllSupportedRRSetTypes(self, types):
        self.assertEqual(types, self.SUPPORTED_RR_SET_TYPES, 'Either some RR types given are unsupported, or not all '
                                                             'supported RR types were in the given set.')

class PublicSuffixMockMixin():
    def _mock_get_public_suffix(self, domain_name, public_suffixes=None):
        if public_suffixes is None:
            public_suffixes = settings.LOCAL_PUBLIC_SUFFIXES | self.PUBLIC_SUFFIXES
        # Poor man's PSL interpreter. First, find all known suffixes covering the domain.
        suffixes = [suffix for suffix in public_suffixes
                    if '.{}'.format(domain_name).endswith('.{}'.format(suffix))]
        # Also, consider TLD.
        suffixes += [domain_name.rsplit('.')[-1]]
        # Select the candidate with the most labels.
        return max(suffixes, key=lambda suffix: suffix.count('.'))

    @staticmethod
    def _mock_is_public_suffix(name):
        return name == psl.get_public_suffix(name)

    def get_psl_context_manager(self, side_effect_parameter):
        if side_effect_parameter is None:
            return nullcontext()

        if callable(side_effect_parameter):
            side_effect = side_effect_parameter
        else:
            side_effect = partial(
                self._mock_get_public_suffix,
                public_suffixes=[side_effect_parameter] if not isinstance(side_effect_parameter, list) else list(side_effect_parameter)
            )

        return mock.patch.object(psl, 'get_public_suffix', side_effect=side_effect)

    def setUpMockPatch(self):
        mock.patch.object(psl, 'get_public_suffix', side_effect=self._mock_get_public_suffix).start()
        mock.patch.object(psl, 'is_public_suffix', side_effect=self._mock_is_public_suffix).start()
        self.addCleanup(mock.patch.stopall)


class DomainOwnerTestCase(DesecTestCase, PublicSuffixMockMixin):
    """
    This test case creates a domain owner, some domains for her and some domains that are owned by other users.
    DomainOwnerTestCase.client is authenticated with the owner's token.
    """
    DYN = False
    NUM_OWNED_DOMAINS = 2
    NUM_OTHER_DOMAINS = 20

    owner = None
    my_domains = None
    other_domains = None
    my_domain = None
    other_domain = None
    token = None

    @classmethod
    def setUpTestDataWithPdns(cls):
        super().setUpTestDataWithPdns()

        cls.owner = cls.create_user()

        domain_kwargs = {'suffix': cls.AUTO_DELEGATION_DOMAINS if cls.DYN else None}
        if cls.DYN:
            domain_kwargs['minimum_ttl'] = 60
        cls.my_domains = [
            cls.create_domain(owner=cls.owner, **domain_kwargs)
            for _ in range(cls.NUM_OWNED_DOMAINS)
        ]
        cls.other_domains = [
            cls.create_domain(**domain_kwargs)
            for _ in range(cls.NUM_OTHER_DOMAINS)
        ]

        if cls.DYN:
            for domain in cls.my_domains + cls.other_domains:
                parent_domain = Domain.objects.get(name=domain.parent_domain_name)
                parent_domain.update_delegation(domain)

        cls.my_domain = cls.my_domains[0]
        cls.other_domain = cls.other_domains[0]

        cls.create_rr_set(cls.my_domain, ['127.0.0.1', '127.0.1.1'], type='A', ttl=123)
        cls.create_rr_set(cls.other_domain, ['40.1.1.1', '40.2.2.2'], type='A', ttl=456)

        cls.token = cls.create_token(user=cls.owner)

    def setUp(self):
        super().setUp()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.plain)
        self.setUpMockPatch()


class DynDomainOwnerTestCase(DomainOwnerTestCase):
    DYN = True

    @classmethod
    def request_pdns_zone_axfr(cls, name=None):
        return super().request_pdns_zone_axfr(name.lower() if name else None)

    @classmethod
    def request_pdns_zone_update(cls, name=None):
        return super().request_pdns_zone_update(name.lower() if name else None)

    def _assertDynDNS12Update(self, requests, mock_remote_addr='', **kwargs):
        with self.assertPdnsRequests(requests):
            if mock_remote_addr:
                return self.client.get(self.reverse('v1:dyndns12update'), kwargs, REMOTE_ADDR=mock_remote_addr)
            else:
                return self.client.get(self.reverse('v1:dyndns12update'), kwargs)

    def assertDynDNS12Update(self, domain_name=None, mock_remote_addr='', **kwargs):
        pdns_name = self._normalize_name(domain_name).lower() if domain_name else None
        return self._assertDynDNS12Update(
            [self.request_pdns_zone_update(name=pdns_name), self.request_pdns_zone_axfr(name=pdns_name)],
            mock_remote_addr,
            **kwargs
        )

    def assertDynDNS12NoUpdate(self, mock_remote_addr='', **kwargs):
        return self._assertDynDNS12Update([], mock_remote_addr, **kwargs)

    def setUp(self):
        super().setUp()
        self.client_token_authorized = self.client_class()
        self.client.set_credentials_basic_auth(self.my_domain.name.lower(), self.token.plain)
        self.client_token_authorized.set_credentials_token_auth(self.token.plain)


class AuthenticatedRRSetBaseTestCase(DomainOwnerTestCase):
    UNSUPPORTED_TYPES = RR_SET_TYPES_UNSUPPORTED
    AUTOMATIC_TYPES = RR_SET_TYPES_AUTOMATIC
    ALLOWED_TYPES = RR_SET_TYPES_MANAGEABLE

    SUBNAMES = ['foo', 'bar.baz', 'q.w.e.r.t', '*', '*.foobar', '_', '-foo.test', '_bar']

    @classmethod
    def _test_rr_sets(cls, subname=None, type_=None, records=None, ttl=None):
        """
        Gives a list of example RR sets for testing.
        Args:
            subname: Filter by subname. None to allow any.
            type_: Filter by type. None to allow any.
            records: Filter by records. Must match exactly. None to allow any.
            ttl: Filter by ttl. None to allow any.

        Returns: Returns a list of tuples that represents example RR sets represented as 4-tuples consisting of
        subname, type_, records, ttl
        """
        # TODO add more examples of cls.ALLOWED_TYPES
        # NOTE The validity of the RRset contents it *not* verified. We currently leave this task to pdns.
        rr_sets = [
            ('', 'A', ['1.2.3.4'], 3620),
            ('test', 'A', ['2.2.3.4'], 3620),
            ('test', 'TXT', ['"foobar"'], 3620),
        ] + [
            (subname_, 'TXT', ['"hey ho, let\'s go!"'], 134)
            for subname_ in cls.SUBNAMES
        ] + [
            (subname_, type_, ['10 mx1.example.com.'], 101)
            for subname_ in cls.SUBNAMES
            for type_ in ['MX', 'SPF']
        ] + [
            (subname_, 'A', ['1.2.3.4'], 187)
            for subname_ in cls.SUBNAMES
        ]

        if subname or type_ or records or ttl:
            rr_sets = [
                rr_set for rr_set in rr_sets
                if (
                    (subname is None or subname == rr_set[0]) and
                    (type_ is None or type_ == rr_set[1]) and
                    (records is None or records == rr_set[2]) and
                    (ttl is None or ttl == rr_set[3])
                )
            ]
        return rr_sets

    @classmethod
    def setUpTestDataWithPdns(cls):
        super().setUpTestDataWithPdns()
        # TODO this test does not cover "dyn" / auto delegation domains
        cls.my_empty_domain = cls.create_domain(suffix='', owner=cls.owner)
        cls.my_rr_set_domain = cls.create_domain(suffix='', owner=cls.owner)
        cls.other_rr_set_domain = cls.create_domain(suffix='')
        for domain in [cls.my_rr_set_domain, cls.other_rr_set_domain]:
            for (subname, type_, records, ttl) in cls._test_rr_sets():
                cls.create_rr_set(domain, subname=subname, type=type_, records=records, ttl=ttl)
