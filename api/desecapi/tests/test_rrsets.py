from ipaddress import IPv4Network
import re
from itertools import product
from math import ceil, floor

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from rest_framework import status

from desecapi.models import Domain, RRset, RR_SET_TYPES_AUTOMATIC, RR_SET_TYPES_UNSUPPORTED
from desecapi.tests.base import DesecTestCase, AuthenticatedRRSetBaseTestCase


class UnauthenticatedRRSetTestCase(DesecTestCase):
    
    def test_unauthorized_access(self):
        url = self.reverse('v1:rrsets', name='example.com')
        for method in [
            self.client.get, 
            self.client.post, 
            self.client.put, 
            self.client.delete, 
            self.client.patch
        ]:
            response = method(url)
            self.assertStatus(response, status.HTTP_401_UNAUTHORIZED)


class AuthenticatedRRSetTestCase(AuthenticatedRRSetBaseTestCase):

    def test_subname_validity(self):
        for subname in [
            'aEroport',
            'AEROPORT',
            'aéroport',
            'a' * 64,
        ]:
            with self.assertRaises(ValidationError):
                RRset(domain=self.my_domain, subname=subname, ttl=60, type='A').save()
        for subname in [
            'aeroport',
            'a' * 63,
        ]:
            RRset(domain=self.my_domain, subname=subname, ttl=60, type='A').save()

    def test_retrieve_my_rr_sets(self):
        for response in [
            self.client.get_rr_sets(self.my_domain.name),
            self.client.get_rr_sets(self.my_domain.name, subname=''),
        ]:
            self.assertStatus(response, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 1, response.data)

    def test_retrieve_my_rr_sets_pagination(self):
        def convert_links(links):
            mapping = {}
            for link in links.split(', '):
                _url, label = link.split('; ')
                label = re.search('rel="(.*)"', label).group(1)
                _url = _url[1:-1]
                assert label not in mapping
                mapping[label] = _url
            return mapping

        def assertPaginationResponse(response, expected_length, expected_directional_links=[]):
            self.assertStatus(response, status.HTTP_200_OK)
            self.assertEqual(len(response.data), expected_length)

            _links = convert_links(response['Link'])
            self.assertEqual(len(_links), len(expected_directional_links) + 1)  # directional links, plus "first"
            self.assertTrue(_links['first'].endswith('/?cursor='))
            for directional_link in expected_directional_links:
                self.assertEqual(_links['first'].find('/?cursor='), _links[directional_link].find('/?cursor='))
                self.assertTrue(len(_links[directional_link]) > len(_links['first']))

        # Prepare extra records so that we get three pages (total: n + 1)
        n = int(settings.REST_FRAMEWORK['PAGE_SIZE'] * 2.5)
        RRset.objects.bulk_create(
            [RRset(domain=self.my_domain, subname=str(i), ttl=123, type='A') for i in range(n)]
        )

        # No pagination
        response = self.client.get_rr_sets(self.my_domain.name)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'],
                         f'Pagination required. You can query up to {settings.REST_FRAMEWORK["PAGE_SIZE"]} items at a time ({n+1} total). '
                         'Please use the `first` page link (see Link header).')
        links = convert_links(response['Link'])
        self.assertEqual(len(links), 1)
        self.assertTrue(links['first'].endswith('/?cursor='))

        # First page
        url = links['first']
        response = self.client.get(url)
        assertPaginationResponse(response, settings.REST_FRAMEWORK['PAGE_SIZE'], ['next'])

        # Next
        url = convert_links(response['Link'])['next']
        response = self.client.get(url)
        assertPaginationResponse(response, settings.REST_FRAMEWORK['PAGE_SIZE'], ['next', 'prev'])
        data_next = response.data.copy()

        # Next-next (last) page
        url = convert_links(response['Link'])['next']
        response = self.client.get(url)
        assertPaginationResponse(response, n/5 + 1, ['prev'])

        # Prev
        url = convert_links(response['Link'])['prev']
        response = self.client.get(url)
        assertPaginationResponse(response, settings.REST_FRAMEWORK['PAGE_SIZE'], ['next', 'prev'])

        # Make sure that one step forward equals two steps forward and one step back
        self.assertEqual(response.data, data_next)

    def test_retrieve_other_rr_sets(self):
        self.assertStatus(self.client.get_rr_sets(self.other_domain.name), status.HTTP_404_NOT_FOUND)
        self.assertStatus(self.client.get_rr_sets(self.other_domain.name, subname='test'), status.HTTP_404_NOT_FOUND)
        self.assertStatus(self.client.get_rr_sets(self.other_domain.name, type='A'), status.HTTP_404_NOT_FOUND)

    def test_retrieve_my_rr_sets_filter(self):
        response = self.client.get_rr_sets(self.my_rr_set_domain.name, query='?cursor=')
        self.assertStatus(response, status.HTTP_200_OK)
        expected_number_of_rrsets = min(len(self._test_rr_sets()), settings.REST_FRAMEWORK['PAGE_SIZE'])
        self.assertEqual(len(response.data), expected_number_of_rrsets)

        for subname in self.SUBNAMES:
            response = self.client.get_rr_sets(self.my_rr_set_domain.name, subname=subname)
            self.assertStatus(response, status.HTTP_200_OK)
            self.assertRRSetsCount(response.data, [dict(subname=subname)],
                                   count=len(self._test_rr_sets(subname=subname)))

        for type_ in self.ALLOWED_TYPES:
            response = self.client.get_rr_sets(self.my_rr_set_domain.name, type=type_)
            self.assertStatus(response, status.HTTP_200_OK)

    def test_create_my_rr_sets(self):
        for subname in [None, 'create-my-rr-sets', 'foo.create-my-rr-sets', 'bar.baz.foo.create-my-rr-sets']:
            for data in [
                {'subname': subname, 'records': ['1.2.3.4'], 'ttl': 3660, 'type': 'A'},
                {'subname': '' if subname is None else subname, 'records': ['desec.io.'], 'ttl': 36900, 'type': 'PTR'},
                {'subname': '' if subname is None else subname, 'ttl': 3650, 'type': 'TXT', 'records': ['"foo"']},
                {'subname': f'{subname}.cname'.lower(), 'ttl': 3600, 'type': 'CNAME', 'records': ['example.com.']},
            ]:
                # Try POST with missing subname
                if data['subname'] is None:
                    data.pop('subname')

                with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
                    response = self.client.post_rr_set(domain_name=self.my_empty_domain.name, **data)
                    self.assertStatus(response, status.HTTP_201_CREATED)
                    self.assertTrue(all(field in response.data for field in
                                        ['created', 'domain', 'subname', 'name', 'records', 'ttl', 'type', 'touched']))
                    self.assertEqual(self.my_empty_domain.touched,
                                     max(rrset.touched for rrset in self.my_empty_domain.rrset_set.all()))

                # Check for uniqueness on second attempt
                response = self.client.post_rr_set(domain_name=self.my_empty_domain.name, **data)
                self.assertContains(response, 'Another RRset with the same subdomain and type exists for this domain.',
                                    status_code=status.HTTP_400_BAD_REQUEST)

                response = self.client.get_rr_sets(self.my_empty_domain.name)
                self.assertStatus(response, status.HTTP_200_OK)
                self.assertRRSetsCount(response.data, [data])

                response = self.client.get_rr_set(self.my_empty_domain.name, data.get('subname', ''), data['type'])
                self.assertStatus(response, status.HTTP_200_OK)
                self.assertRRSet(response.data, **data)

    def test_create_my_rr_sets_type_restriction(self):
        for subname in ['', 'create-my-rr-sets', 'foo.create-my-rr-sets', 'bar.baz.foo.create-my-rr-sets']:
            for data in [
                {'subname': subname, 'ttl': 60, 'type': 'a'},
                {'subname': subname, 'records': ['10 example.com.'], 'ttl': 60, 'type': 'txt'}
            ] + [
                {'subname': subname, 'records': ['10 example.com.'], 'ttl': 60, 'type': type_}
                for type_ in self.UNSUPPORTED_TYPES
            ] + [
                {'subname': subname, 'records': ['get.desec.io. get.desec.io. 2584 10800 3600 604800 60'],
                 'ttl': 60, 'type': type_}
                for type_ in self.AUTOMATIC_TYPES
            ]:
                response = self.client.post_rr_set(self.my_domain.name, **data)
                self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

                response = self.client.get_rr_sets(self.my_domain.name)
                self.assertStatus(response, status.HTTP_200_OK)
                self.assertRRSetsCount(response.data, [data], count=0)

    def test_create_my_rr_sets_cname_at_apex(self):
        data = {'subname': '', 'ttl': 3600, 'type': 'CNAME', 'records': ['foobar.com.']}
        response = self.client.post_rr_set(self.my_empty_domain.name, **data)
        self.assertContains(response, 'CNAME RRset cannot have empty subname', status_code=status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_cname_multiple_records(self):
        for records in (['foobar.com.', 'foobar.com.'], ['foobar.com.', 'foobar.org.']):
            data = {'subname': 'asdf', 'ttl': 3600, 'type': 'CNAME', 'records': records}
            response = self.client.post_rr_set(self.my_empty_domain.name, **data)
            self.assertContains(response, 'CNAME RRset cannot have multiple records',
                                status_code=status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_dname_multiple_records(self):
        for records in (['foobar.com.', 'foobar.com.'], ['foobar.com.', 'foobar.org.']):
            data = {'subname': 'asdf', 'ttl': 3600, 'type': 'DNAME', 'records': records}
            response = self.client.post_rr_set(self.my_empty_domain.name, **data)
            self.assertContains(response, 'DNAME RRset cannot have multiple records',
                                status_code=status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_cname_exclusivity(self):
        self.create_rr_set(self.my_domain, ['1.2.3.4'], type='A', ttl=3600, subname='a')
        self.create_rr_set(self.my_domain, ['example.com.'], type='CNAME', ttl=3600, subname='cname')

        # Can't add a CNAME where something else is
        data = {'subname': 'a', 'ttl': 3600, 'type': 'CNAME', 'records': ['foobar.com.']}
        response = self.client.post_rr_set(self.my_domain.name, **data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

        # Can't add something else where a CNAME is
        data = {'subname': 'cname', 'ttl': 3600, 'type': 'A', 'records': ['4.3.2.1']}
        response = self.client.post_rr_set(self.my_domain.name, **data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_without_records(self):
        for subname in ['', 'create-my-rr-sets', 'foo.create-my-rr-sets', 'bar.baz.foo.create-my-rr-sets']:
            for data in [
                {'subname': subname, 'records': [], 'ttl': 60, 'type': 'A'},
                {'subname': subname, 'ttl': 60, 'type': 'A'},
            ]:
                response = self.client.post_rr_set(self.my_empty_domain.name, **data)
                self.assertStatus(
                    response,
                    status.HTTP_400_BAD_REQUEST
                )

                response = self.client.get_rr_sets(self.my_empty_domain.name)
                self.assertStatus(response, status.HTTP_200_OK)
                self.assertRRSetsCount(response.data, [], count=0)

    def test_create_other_rr_sets(self):
        data = {'records': ['1.2.3.4'], 'ttl': 60, 'type': 'A'}
        response = self.client.post_rr_set(self.other_domain.name, **data)
        self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    @staticmethod
    def _create_test_txt_record(record, type_='TXT'):
        return {'records': [f'{record}'], 'ttl': 3600, 'type': type_, 'subname': f'name{len(record)}'}

    def test_create_my_rr_sets_chunk_too_long(self):
        for l, t in product([1, 255, 256, 498], ['TXT', 'SPF']):
            with self.assertPdnsRequests(self.requests_desec_rr_sets_update(self.my_empty_domain.name)):
                response = self.client.post_rr_set(
                    self.my_empty_domain.name,
                    **self._create_test_txt_record(f'"{"A" * l}"', t)
                )
                self.assertStatus(response, status.HTTP_201_CREATED)
            with self.assertPdnsRequests(self.requests_desec_rr_sets_update(self.my_empty_domain.name)):
                self.client.delete_rr_set(self.my_empty_domain.name, type_=t, subname=f'name{l+2}')

    def test_create_my_rr_sets_too_long_content(self):
        def token(length):
            if length == 0:
                return ''
            if length <= 255:
                return f'"{"A" * length}"'
            return f'{token(255)} ' * (length // 255) + token(length % 255)

        def p2w_length(length):
            return ceil(length / 255 * 256)

        def w2p_length(length):
            return floor(length / 256 * 255)

        max_wirelength = 64000
        max_preslength = w2p_length(max_wirelength)

        assert max_preslength == 63750
        assert p2w_length(max_preslength) == 64000
        assert p2w_length(max_preslength + 1) == 64002

        for t in ['SPF', 'TXT']:
            response = self.client.post_rr_set(
                self.my_empty_domain.name,
                # record of wire length 501 bytes in chunks of max 255 each (RFC 4408)
                **self._create_test_txt_record(token(max_preslength + 1), t)
            )
            self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
            self.assertIn(
                f'Ensure this value has no more than {max_wirelength} byte in wire format (it has {p2w_length(max_preslength + 1)}).',
                str(response.data)
            )

        with self.assertPdnsRequests(self.requests_desec_rr_sets_update(self.my_empty_domain.name)):
            response = self.client.post_rr_set(
                self.my_empty_domain.name,
                # record of wire length 500 bytes in chunks of max 255 each (RFC 4408)
                **self._create_test_txt_record(token(max_preslength))
            )
            self.assertStatus(response, status.HTTP_201_CREATED)

    def test_create_my_rr_sets_too_large_rrset(self):
        network = IPv4Network('127.0.0.0/20')  # size: 4096 IP addresses
        data = {'records': [str(ip) for ip in network], 'ttl': 3600, 'type': 'A', 'subname': 'name'}
        response = self.client.post_rr_set(self.my_empty_domain.name, **data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        excess_length = 28743 + len(self.my_empty_domain.name)
        self.assertIn(f'Total length of RRset exceeds limit by {excess_length} bytes.', str(response.data))

    def test_create_my_rr_sets_twice(self):
        data = {'records': ['1.2.3.4'], 'ttl': 3660, 'type': 'A'}
        with self.assertPdnsRequests(self.requests_desec_rr_sets_update(self.my_empty_domain.name)):
            response = self.client.post_rr_set(self.my_empty_domain.name, **data)
            self.assertStatus(response, status.HTTP_201_CREATED)

        data['records'][0] = '3.2.2.1'
        response = self.client.post_rr_set(self.my_empty_domain.name, **data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_duplicate_content(self):
        for records in [
            ['::1', '0::1'],
            # TODO add more examples
        ]:
            data = {'records': records, 'ttl': 3660, 'type': 'AAAA'}
            response = self.client.post_rr_set(self.my_empty_domain.name, **data)
            self.assertContains(response, 'Duplicate', status_code=status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_upper_case(self):
        for subname in ['asdF', 'cAse', 'asdf.FOO', '--F', 'ALLCAPS']:
            data = {'records': ['1.2.3.4'], 'ttl': 60, 'type': 'A', 'subname': subname}
            response = self.client.post_rr_set(self.my_empty_domain.name, **data)
            self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
            self.assertIn('Subname can only use (lowercase)', str(response.data))

    def test_create_my_rr_sets_subname_too_many_dots(self):
        for subname in ['dottest.', '.dottest', 'dot..test']:
            data = {'subname': subname, 'records': ['10 example.com.'], 'ttl': 3600, 'type': 'MX'}
            response = self.client.post_rr_set(self.my_domain.name, **data)
            self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

        response = self.client.get_rr_sets(self.my_domain.name)
        self.assertStatus(response, status.HTTP_200_OK)
        self.assertRRSetsCount(response.data, [data], count=0)

    def test_create_my_rr_sets_empty_payload(self):
        response = self.client.post_rr_set(self.my_empty_domain.name)
        self.assertContains(response, 'No data provided', status_code=status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_cname_two_records(self):
        data = {'subname': 'sub', 'records': ['example.com.', 'example.org.'], 'ttl': 3600, 'type': 'CNAME'}
        response = self.client.post_rr_set(self.my_domain.name, **data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_canonical_content(self):
        # TODO fill in more examples
        datas = [
            # record type: (non-canonical input, canonical output expectation)
            ('A', ('127.0.0.1', '127.0.0.1')),
            ('AAAA', ('0000::0000:0001', '::1')),
            ('AAAA', ('::ffff:127.0.0.1', '::ffff:7f00:1')),
            ('AAAA', ('2001:db8::128.2.129.4', '2001:db8::8002:8104')),
            ('AFSDB', ('02 turquoise.FEMTO.edu.', '2 turquoise.femto.edu.')),
            ('APL', ('2:FF00:0:0:0:0::/8  !1:192.168.38.0/28', '2:ff00::/8 !1:192.168.38.0/28')),
            ('CAA', ('0128 "issue" "letsencrypt.org"', '128 issue "letsencrypt.org"')),
            ('CDNSKEY', ('0256  03  08  AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+ 1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mx t6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLK l3D0L/cD',
                        '256 3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mxt6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLKl3D0L/cD')),
            ('CDNSKEY', ('257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/ qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGr CHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll 96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPri ec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAst bxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6as lO7jXv16Gws=',
                        '257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGrCHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPriec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAstbxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6aslO7jXv16Gws=')),
            ('CDNSKEY', ('257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg==',
                        '257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryquB78Pyk/NTEoai5bxoipVQQXzHlzyg==')),
            ('CDS', ('047883  013  02  43BD262211B2A748335149408F67BC95B9A4A3174FD86E6A83830380 446E7AFD',
                     '47883 13 2 43BD262211B2A748335149408F67BC95B9A4A3174FD86E6A83830380446E7AFD'.lower())),
            ('CERT', ('06 00 00 sadfdd==', '6 0 0 sadfdQ==')),
            ('CNAME', ('EXAMPLE.COM.', 'example.com.')),
            ('CSYNC', ('066 03  NS  AAAA A', '66 3 A NS AAAA')),
            ('DHCID', ('xxxx', 'xxxx')),
            ('DLV', ('6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
                     '6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA10DF1F520'.lower())),
            ('DLV', ('6454 8 2 5C BA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
                     '6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA10DF1F520'.lower())),
            ('DNAME', ('EXAMPLE.COM.', 'example.com.')),
            ('DNSKEY', ('0256  03  08  AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+ 1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mx t6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLK l3D0L/cD',
                        '256 3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mxt6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLKl3D0L/cD')),
            ('DNSKEY', ('257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/ qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGr CHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll 96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPri ec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAst bxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6as lO7jXv16Gws=',
                        '257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGrCHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPriec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAstbxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6aslO7jXv16Gws=')),
            ('DNSKEY', ('257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg==',
                        '257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryquB78Pyk/NTEoai5bxoipVQQXzHlzyg==')),
            ('DS', ('6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
                    '6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA10DF1F520'.lower())),
            ('DS', ('6454 8 2 5C BA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
                    '6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA10DF1F520'.lower())),
            ('EUI48', ('AA-BB-CC-DD-EE-FF', 'aa-bb-cc-dd-ee-ff')),
            ('EUI64', ('AA-BB-CC-DD-EE-FF-aa-aa', 'aa-bb-cc-dd-ee-ff-aa-aa')),
            ('HINFO', ('cpu os', '"cpu" "os"')),
            ('HINFO', ('"cpu" "os"', '"cpu" "os"')),
            ('HTTPS', ('01 h3POOL.exaMPLe. aLPn=h2,h3',
                       '1 h3POOL.exaMPLe. alpn=h2,h3')),
            # ('HTTPS', ('01 h3POOL.exaMPLe. aLPn=h2,h3 ECH=MTIzLi4uCg==',  # TODO dnspython > 2.1.0
            #            '1 h3POOL.exaMPLe. alpn=h2,h3 ech="MTIzLi4uCg=="')),
            # ('IPSECKEY', ('01 00 02 . ASDFAF==', '1 0 2 . ASDFAA==')),
            # ('IPSECKEY', ('01 00 02 . 000000==', '1 0 2 . 00000w==')),
            ('KX', ('010 example.com.', '10 example.com.')),
            ('LOC', ('023 012 59 N 042 022 48.500 W 65.00m 20.00m 10.00m 10.00m',
                     '23 12 59.000 N 42 22 48.500 W 65.00m 20.00m 10.00m 10.00m')),
            ('MX', ('10 010.1.1.1.', '10 010.1.1.1.')),
            ('MX', ('010 010.1.1.2.', '10 010.1.1.2.')),
            ('MX', ('0 .', '0 .')),
            ('NAPTR', ('100  50  "s"  "z3950+I2L+I2C"     ""  _z3950._tcp.gatech.edu.',
                       '100 50 "s" "z3950+I2L+I2C" "" _z3950._tcp.gatech.edu.')),
            ('NS', ('EXaMPLE.COM.', 'example.com.')),
            ('OPENPGPKEY', ('mG8EXtVIsRMFK4EEACIDAwQSZPNqE4tS xLFJYhX+uabSgMrhOqUizJhkLx82',
                            'mG8EXtVIsRMFK4EEACIDAwQSZPNqE4tSxLFJYhX+uabSgMrhOqUizJhkLx82')),
            ('PTR', ('EXAMPLE.COM.', 'example.com.')),
            ('RP', ('hostmaster.EXAMPLE.com. .', 'hostmaster.example.com. .')),
            ('SMIMEA', ('3 01 0 aaBBccddeeff', '3 1 0 aabbccddeeff')),
            ('SPF', ('"v=spf1 ip4:10.1" ".1.1 ip4:127" ".0.0.0/16 ip4:192.168.0.0/27 include:example.com -all"',
                     '"v=spf1 ip4:10.1" ".1.1 ip4:127" ".0.0.0/16 ip4:192.168.0.0/27 include:example.com -all"')),
            ('SPF', ('"foo" "bar"', '"foo" "bar"')),
            ('SPF', ('"foobar"', '"foobar"')),
            ('SRV', ('0 000 0 .', '0 0 0 .')),
            ('SRV', ('100 1 5061 EXAMPLE.com.', '100 1 5061 example.com.')),
            ('SRV', ('100 1 5061 example.com.', '100 1 5061 example.com.')),
            ('SSHFP', ('2 2 aabbccEEddff', '2 2 aabbcceeddff')),
            ('SVCB', ('2 sVc2.example.NET. IPV6hint=2001:db8:00:0::2 port=01234',
                      '2 sVc2.example.NET. port=1234 ipv6hint=2001:db8::2')),
            # ('SVCB', ('2 sVc2.example.NET. ECH=MjIyLi4uCg== IPV6hint=2001:db8:00:0::2 port=01234',  # TODO dnspython > 2.1.0
            #           '2 sVc2.example.NET. port=1234 ech="MjIyLi4uCg==" ipv6hint=2001:db8::2')),
            ('TLSA', ('3 0001 1 000AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', '3 1 1 000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')),
            ('TLSA', ('003 00 002 696B8F6B92A913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd',
                      '3 0 2 696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd')),
            ('TLSA', ('3 0 2 696B8F6B92A913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd696B8F6B92A913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd',
                      '3 0 2 696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd')),
            ('TXT', ('"foo" "bar"', '"foo" "bar"')),
            ('TXT', ('"foobar"', '"foobar"')),
            ('TXT', ('"foo" "" "bar"', '"foo" "" "bar"')),
            ('TXT', ('"" "" "foo" "" "bar"', '"" "" "foo" "" "bar"')),
            ('TXT', (r'"\130\164name\164Boss\164type\1611"', r'"\130\164name\164Boss\164type\1611"')),
            ('TXT', ('"' + ''.join(fr'\{n:03}' for n in range(256)) + '"',  # all bytes
                     r'"\000\001\002\003\004\005\006\007\008\009\010\011\012\013\014\015\016\017\018\019\020\021\022\023\024\025\026\027\028\029\030\031 !\"#$%&' + "'" + r'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\127\128\129\130\131\132\133\134\135\136\137\138\139\140\141\142\143\144\145\146\147\148\149\150\151\152\153\154\155\156\157\158\159\160\161\162\163\164\165\166\167\168\169\170\171\172\173\174\175\176\177\178\179\180\181\182\183\184\185\186\187\188\189\190\191\192\193\194\195\196\197\198\199\200\201\202\203\204\205\206\207\208\209\210\211\212\213\214\215\216\217\218\219\220\221\222\223\224\225\226\227\228\229\230\231\232\233\234\235\236\237\238\239\240\241\242\243\244\245\246\247\248\249\250\251\252\253\254" "\255"')),
            ('URI', ('10 01 "ftp://ftp1.example.com/public"', '10 1 "ftp://ftp1.example.com/public"')),
        ]
        for t, (record, canonical_record) in datas:
            if not record:
                continue
            data = {'records': [record], 'ttl': 3660, 'type': t, 'subname': 'test'}
            with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
                response = self.client.post_rr_set(self.my_empty_domain.name, **data)
                self.assertStatus(response, status.HTTP_201_CREATED)
                self.assertEqual(canonical_record, response.data['records'][0],
                                 f'For RR set type {t}, expected \'{canonical_record}\' to be the canonical form of '
                                 f'\'{record}\', but saw \'{response.data["records"][0]}\'.')
            with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
                response = self.client.delete_rr_set(self.my_empty_domain.name, subname='test', type_=t)
                self.assertStatus(response, status.HTTP_204_NO_CONTENT)
        self.assertAllSupportedRRSetTypes(set(t for t, _ in datas))

    def test_create_my_rr_sets_known_type_benign(self):
        # TODO fill in more examples
        datas = {
            'A': ['127.0.0.1', '127.0.0.2'],
            'AAAA': ['::1', '::2'],
            'AFSDB': ['2 turquoise.femto.edu.'],
            'APL': [
                # from RFC 3123 Sec. 4
                '1:192.168.32.0/21 !1:192.168.38.0/28',
                '1:192.168.42.0/26 1:192.168.42.64/26 1:192.168.42.128/25',
                '1:127.0.0.1/32 1:172.16.64.0/22',
                '1:224.0.0.0/4  2:FF00:0:0:0:0:0:0:0/8',
                # made-up (not from RFC)
                '1:1.2.3.4/32 2:::/128',
                '2:FF00::/8 !1:192.168.38.0/28',
            ],
            'CAA': ['128 issue "letsencrypt.org"', '128 iodef "mailto:desec@example.com"', '1 issue "letsencrypt.org"'],
            'CERT': ['6 0 0 sadfdd=='],
            'CDNSKEY': [
                '256 3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+ 1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mx t6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLK l3D0L/cD',
                '257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/ qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGr CHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll 96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPri ec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAst bxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6as lO7jXv16Gws=',
                '257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg==',
            ],
            'CDS': [
                '6454 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
                '62703 13 2 085BF1EE0ADBBC99D4D9328229EBDCAEC5FAB20E38610072AD055474 4C7AF4A0',
                '61655 13 4 C838A5C66FCBF83B8B6B50C3CEEC3524777FE4AF8A9FE0172ECAD242 48B0CA1A216DD0D538F20C130DD3059538204B04',
            ],
            'CNAME': ['example.com.'],
            'CSYNC': ['0 0', '66 1 A', '66 2 AAAA', '66 3 A NS AAAA', '66 15 NSEC'],
            'DHCID': ['aaaaaaaaaaaa', 'aa aaa  aaaa a a a'],
            'DLV': [
                '6454 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
                '62703 13 2 085BF1EE0ADBBC99D4D9328229EBDCAEC5FAB20E38610072AD055474 4C7AF4A0',
                '61655 13 4 C838A5C66FCBF83B8B6B50C3CEEC3524777FE4AF8A9FE0172ECAD242 48B0CA1A216DD0D538F20C130DD3059538204B04',
            ],
            'DNAME': ['example.com.'],
            'DNSKEY': [
                '256 3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+ 1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mx t6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLK l3D0L/cD',
                '257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/ qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGr CHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll 96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPri ec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAst bxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6as lO7jXv16Gws=',
                '257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg==',
            ],
            'DS': [
                '6454 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 2 5CBA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
                '62703 13 2 085BF1EE0ADBBC99D4D9328229EBDCAEC5FAB20E38610072AD055474 4C7AF4A0',
                '61655 13 4 C838A5C66FCBF83B8B6B50C3CEEC3524777FE4AF8A9FE0172ECAD242 48B0CA1A216DD0D538F20C130DD3059538204B04',
            ],
            'EUI48': ['aa-bb-cc-dd-ee-ff', 'AA-BB-CC-DD-EE-FF'],
            'EUI64': ['aa-bb-cc-dd-ee-ff-00-11', 'AA-BB-CC-DD-EE-FF-00-11'],
            'HINFO': ['"ARMv8-A" "Linux"'],
            'HTTPS': [
                # from https://www.ietf.org/archive/id/draft-ietf-dnsop-svcb-https-06.html#name-examples, with ech base64'd
                '1 . alpn=h3',
                '0 pool.svc.example.',
                # '1 h3pool.example. alpn=h2,h3 ech="MTIzLi4uCg=="',  # TODO dnspython > 2.1.0
                # '2 .      alpn=h2 ech="YWJjLi4uCg=="',  # TODO dnspython > 2.1.0
                # made-up (not from RFC)
                '1 pool.svc.example. no-default-alpn port=1234 ipv4hint=192.168.123.1',
                # '2 . ech=... key65333=ex1 key65444=ex2 mandatory=key65444,ech',  # see #section-7  # TODO dnspython > 2.1.0
            ],
            # 'IPSECKEY': [
            #     '12 0 2 . asdfdf==',
            #     '03 1 1 127.0.0.1 asdfdf==',
            #     '10 02 2 bade::affe AQNRU3mG7TVTO2BkR47usntb102uFJtugbo6BSGvgqt4AQ==',
            #     '12 3 01 example.com. asdfdf==',
            # ],
            'KX': ['4 example.com.', '28 io.'],
            'LOC': ['23 12 59.000 N 42 22 48.500 W 65.00m 20.00m 10.00m 10.00m'],
            'MX': ['10 example.com.', '20 1.1.1.1.'],
            'NAPTR': ['100  50  "s"  "z3950+I2L+I2C"     ""  _z3950._tcp.gatech.edu.'],
            'NS': ['ns1.example.com.'],
            'OPENPGPKEY': [
                'mG8EXtVIsRMFK4EEACIDAwQSZPNqE4tSxLFJYhX+uabSgMrhOqUizJhkLx82',  # key incomplete
                'YWFh\xf0\x9f\x92\xa9YWFh',  # valid as non-alphabet bytes will be ignored
            ],
            'PTR': ['example.com.', '*.example.com.'],
            'RP': ['hostmaster.example.com. .'],
            'SMIMEA': ['3 1 0 aabbccddeeff'],
            'SPF': ['"v=spf1 include:example.com ~all"',
                    '"v=spf1 ip4:10.1.1.1 ip4:127.0.0.0/16 ip4:192.168.0.0/27 include:example.com -all"',
                    '"spf2.0/pra,mfrom ip6:2001:558:fe14:76:68:87:28:0/120 -all"'],
            'SRV': ['0 0 0 .', '100 1 5061 example.com.'],
            'SSHFP': ['2 2 aabbcceeddff'],
            'SVCB': [
                '0 svc4-baz.example.net.',
                '1 . key65333=...',
                # '2 svc2.example.net. ech="MjIyLi4uCg==" ipv6hint=2001:db8::2 port=1234',  # TODO dnspython > 2.1.0
            ],
            'TLSA': ['3 1 1 AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
                     '3 0 2 696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd',
                     '3 0 2 696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd'],
            'TXT': ['"foobar"', '"foo" "bar"', '"“红色联合”对“四·二八兵团”总部大楼的攻击已持续了两天"', '"new\\010line"'
                    '"🧥 👚 👕 👖 👔 👗 👙 👘 👠 👡 👢 👞 👟 🥾 🥿  🧦 🧤 🧣 🎩 🧢 👒 🎓 ⛑ 👑 👝 👛 👜 💼 🎒 👓 🕶 🥽 🥼 🌂 🧵"'],
            'URI': ['10 1 "ftp://ftp1.example.com/public"'],
        }
        self.assertAllSupportedRRSetTypes(set(datas.keys()))
        for t, records in datas.items():
            for r in records:
                data = {'records': [r], 'ttl': 3660, 'type': t, 'subname': 'test'}
                with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
                    response = self.client.post_rr_set(self.my_empty_domain.name, **data)
                    self.assertStatus(response, status.HTTP_201_CREATED)
                with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
                    response = self.client.delete_rr_set(self.my_empty_domain.name, subname='test', type_=t)
                    self.assertStatus(response, status.HTTP_204_NO_CONTENT)

    def test_create_my_rr_sets_known_type_invalid(self):
        # TODO fill in more examples
        datas = {
            # recordtype: [list of examples expected to be rejected, individually]
            'A': ['127.0.0.999', '127.000.0.01', '127.0.0.256', '::1', 'foobar', '10.0.1', '10!'],
            'AAAA': ['::g', '1:1:1:1:1:1:1:1:', '1:1:1:1:1:1:1:1:1'],
            'AFSDB': ['example.com.', '1 1', '1 de'],
            'APL': [
                '0:192.168.32.0/21 !1:192.168.38.0/28',
                '1:192.168.32.0/21 !!1:192.168.38.0/28',
                '1:192.168.32.0/33',
                '18:12345/2',
                '1:127.0.0.1',
                '2:FF00:0:0:0:0:0:0:0:0/8'
                '2:::/129',
            ],
            'CAA': ['43235 issue "letsencrypt.org"'],
            'CERT': ['6 0 sadfdd=='],
            'CDNSKEY': [
                'a 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='
                '257 b 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='
                '257 3 c aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='
                '257 3 13 d'
            ],
            'CDS': [
                'a 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '-6454 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 b 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 c 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 1 d',
                '6454 8 0 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 5 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 1 aabbccddeeff',
            ],
            'CNAME': ['example.com', '10 example.com.'],
            'CSYNC': ['0 -1 A', '444 65536 A', '0 3 AAA'],
            'DHCID': ['x', 'xx', 'xxx'],
            'DLV': [
                'a 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '-6454 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 b 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 c 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 1 d',
                '6454 8 0 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 5 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 1 aabbccddeeff',
            ],
            'DNAME': ['example.com', '10 example.com.'],
            'DNSKEY': [
                'a 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='
                '257 b 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='
                '257 3 c aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='
                '257 3 13 d'
            ],
            'DS': [
                'a 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '-6454 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 b 1 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 c 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 1 d',
                '6454 8 0 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 5 24396E17E36D031F71C354B06A979A67A01F503E',
                '6454 8 1 aabbccddeeff',
            ],
            'EUI48': ['aa-bb-ccdd-ee-ff', 'AA-BB-CC-DD-EE-GG'],
            'EUI64': ['aa-bb-cc-dd-ee-ff-gg-11', 'AA-BB-C C-DD-EE-FF-00-11'],
            'HINFO': ['"ARMv8-A"', f'"a" "{"b"*256}"'],
            'HTTPS': [
                # from https://tools.ietf.org/html/draft-ietf-dnsop-svcb-https-02#section-10.3, with ech base64'd
                # '1 h3pool alpn=h2,h3 ech="MTIzLi4uCg=="',  # TODO dnspython > 2.1.0
                # made-up (not from RFC)
                '0 pool.svc.example. no-default-alpn port=1234 ipv4hint=192.168.123.1',  # no keys in alias mode
                '1 pool.svc.example. no-default-alpn port=1234 ipv4hint=192.168.123.1 ipv4hint=192.168.123.2',  # dup
            ],
            # 'IPSECKEY': [],
            'KX': ['-1 example.com', '10 example.com'],
            'LOC': ['23 12 61.000 N 42 22 48.500 W 65.00m 20.00m 10.00m 10.00m', 'foo', '1.1.1.1'],
            'MX': ['10 example.com', 'example.com.', '-5 asdf.', '65537 asdf.', '10 _foo.example.com.', '10 $url.'],
            'NAPTR': ['100  50  "s"  "z3950+I2L+I2C"     ""  _z3950._tcp.gatech.edu',
                      '100  50  "s"     ""  _z3950._tcp.gatech.edu.',
                      '100  50  3 2  "z3950+I2L+I2C"     ""  _z3950._tcp.gatech.edu.'],
            'NS': ['ns1.example.com', '127.0.0.1', '_foobar.example.dedyn.io.', '.'],
            'OPENPGPKEY': ['1 2 3'],
            'PTR': ['"example.com."', '10 *.example.com.'],
            'RP': ['hostmaster.example.com.', '10 foo.'],
            'SMIMEA': ['3 1 0 aGVsbG8gd29ybGQh'],
            'SPF': ['"v=spf1', 'v=spf1 include:example.com ~all'],
            'SRV': ['0 0 0 0', '100 5061 example.com.', '0 0 16920 _foo.example.com.', '0 0 16920 $url.'],
            'SSHFP': ['aabbcceeddff'],
            'SVCB': [
                '0 svc4-baz.example.net. keys=val',
                '1 not.fully.qualified key65333=...',
                # '2 duplicate.key. ech="MjIyLi4uCg==" ech="MjIyLi4uCg=="',  # TODO dnspython > 2.1.0
            ],
            'TLSA': ['3 1 1 AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'],
            'TXT': [
                'foob"ar',
                'v=spf1 include:example.com ~all',
                '"foo\nbar"',
                '"\x00" "NUL byte yo"',
                '"' + ''.join(fr'\{n:03}' for n in range(257)) + '"'  # \256 does not exist
            ],
            'URI': ['"1" "2" "3"'],
        }
        self.assertAllSupportedRRSetTypes(set(datas.keys()))
        for t, records in datas.items():
            for r in records:
                data = {'records': [r], 'ttl': 3660, 'type': t, 'subname': ''}
                response = self.client.post_rr_set(self.my_empty_domain.name, **data)
                self.assertNotContains(response, 'Duplicate', status_code=status.HTTP_400_BAD_REQUEST)

    def test_create_my_rr_sets_txt_splitting(self):
        for t in ['TXT', 'SPF']:
            for l in [200, 255, 256, 300, 400]:
                data = {'records': [f'"{"a"*l}"'], 'ttl': 3660, 'type': t, 'subname': f'x{l}'}
                with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
                    response = self.client.post_rr_set(self.my_empty_domain.name, **data)
                    self.assertStatus(response, status.HTTP_201_CREATED)
                response = self.client.get_rr_set(self.my_empty_domain.name, f'x{l}', t)
                num_tokens = response.data['records'][0].count(' ') + 1
                num_tokens_expected = l // 256 + 1
                self.assertEqual(num_tokens, num_tokens_expected,
                                 f'For a {t} record with a token of length of {l}, expected to see '
                                 f'{num_tokens_expected} tokens in the canonical format, but saw {num_tokens}.')
                self.assertEqual("".join(r.strip('" ') for r in response.data['records'][0]), 'a'*l)

    def test_create_my_rr_sets_unknown_type(self):
        for _type in ['AA', 'ASDF'] + list(RR_SET_TYPES_AUTOMATIC | RR_SET_TYPES_UNSUPPORTED):
            response = self.client.post_rr_set(self.my_domain.name, records=['1234'], ttl=3660, type=_type)
            self.assertContains(
                response,
                text='managed automatically' if _type in RR_SET_TYPES_AUTOMATIC else 'type is currently unsupported',
                status_code=status.HTTP_400_BAD_REQUEST
            )


    def test_create_my_rr_sets_ttl_too_small(self):
        ttl = settings.MINIMUM_TTL_DEFAULT - 1
        response = self.client.post_rr_set(self.my_empty_domain.name, records=['1.2.3.4'], ttl=ttl, type='A')
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        detail = f'Ensure this value is greater than or equal to {self.my_empty_domain.minimum_ttl}.'
        self.assertEqual(response.data['ttl'][0], detail)

        ttl += 1
        with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
            response = self.client.post_rr_set(self.my_empty_domain.name, records=['1.2.23.4'], ttl=ttl, type='A')
        self.assertStatus(response, status.HTTP_201_CREATED)

    def test_create_my_rr_sets_ttl_too_large(self):
        max_ttl = 24*3600
        response = self.client.post_rr_set(self.my_empty_domain.name, records=['1.2.3.4'], ttl=max_ttl + 1, type='A')
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        detail = f'Ensure this value is less than or equal to {max_ttl}.'
        self.assertEqual(response.data['ttl'][0], detail)

        with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_empty_domain.name)):
            response = self.client.post_rr_set(self.my_empty_domain.name, records=['1.2.23.4'], ttl=max_ttl, type='A')
        self.assertStatus(response, status.HTTP_201_CREATED)

    def test_retrieve_my_rr_sets_apex(self):
        response = self.client.get_rr_set(self.my_rr_set_domain.name, subname='', type_='A')
        self.assertStatus(response, status.HTTP_200_OK)
        self.assertEqual(response.data['records'][0], '1.2.3.4')
        self.assertEqual(response.data['ttl'], 3620)

    def test_retrieve_my_rr_sets_restricted_types(self):
        for type_ in self.AUTOMATIC_TYPES:
            response = self.client.get_rr_sets(self.my_domain.name, type=type_)
            self.assertStatus(response, status.HTTP_403_FORBIDDEN)
            response = self.client.get_rr_sets(self.my_domain.name, type=type_, subname='')
            self.assertStatus(response, status.HTTP_403_FORBIDDEN)

    def test_update_my_rr_sets(self):
        for subname in self.SUBNAMES:
            with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_rr_set_domain.name)):
                data = {'records': ['2.2.3.4'], 'ttl': 3630, 'type': 'A', 'subname': subname}
                response = self.client.put_rr_set(self.my_rr_set_domain.name, subname, 'A', data)
                self.assertStatus(response, status.HTTP_200_OK)

            response = self.client.get_rr_set(self.my_rr_set_domain.name, subname, 'A')
            self.assertStatus(response, status.HTTP_200_OK)
            self.assertEqual(response.data['records'], ['2.2.3.4'])
            self.assertEqual(response.data['ttl'], 3630)

            response = self.client.put_rr_set(self.my_rr_set_domain.name, subname, 'A', {'records': ['2.2.3.5']})
            self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

            response = self.client.put_rr_set(self.my_rr_set_domain.name, subname, 'A', {'ttl': 3637})
            self.assertStatus(response, status.HTTP_400_BAD_REQUEST)

    def test_update_my_rr_set_with_invalid_payload_type(self):
        for subname in self.SUBNAMES:
            data = [{'records': ['2.2.3.4'], 'ttl': 30, 'type': 'A', 'subname': subname}]
            response = self.client.put_rr_set(self.my_rr_set_domain.name, subname, 'A', data)
            self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
            self.assertEquals(response.data['non_field_errors'][0],
                              'Invalid data. Expected a dictionary, but got list.')

            data = 'foobar'
            response = self.client.put_rr_set(self.my_rr_set_domain.name, subname, 'A', data)
            self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
            self.assertEquals(response.data['non_field_errors'][0],
                              'Invalid data. Expected a dictionary, but got str.')

    def test_partially_update_my_rr_sets(self):
        for subname in self.SUBNAMES:
            current_rr_set = self.client.get_rr_set(self.my_rr_set_domain.name, subname, 'A').data
            for data in [
                {'records': ['2.2.3.4'], 'ttl': 3630},
                {'records': ['3.2.3.4']},
                {'records': ['3.2.3.4', '9.8.8.7']},
                {'ttl': 3637},
            ]:
                with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_rr_set_domain.name)):
                    response = self.client.patch_rr_set(self.my_rr_set_domain.name, subname, 'A', data)
                    self.assertStatus(response, status.HTTP_200_OK)

                response = self.client.get_rr_set(self.my_rr_set_domain.name, subname, 'A')
                self.assertStatus(response, status.HTTP_200_OK)
                current_rr_set.update(data)
                self.assertEqual(set(response.data['records']), set(current_rr_set['records']))
                self.assertEqual(response.data['ttl'], current_rr_set['ttl'])

            response = self.client.patch_rr_set(self.my_rr_set_domain.name, subname, 'A', {})
            self.assertStatus(response, status.HTTP_200_OK)

    def test_rr_sets_touched_if_noop(self):
        for subname in self.SUBNAMES:
            touched_old = RRset.objects.get(domain=self.my_rr_set_domain, type='A', subname=subname).touched
            response = self.client.patch_rr_set(self.my_rr_set_domain.name, subname, 'A', {})
            self.assertStatus(response, status.HTTP_200_OK)

            touched_new = RRset.objects.get(domain=self.my_rr_set_domain, type='A', subname=subname).touched
            self.assertGreater(touched_new, touched_old)
            self.assertEqual(Domain.objects.get(name=self.my_rr_set_domain.name).touched, touched_new)

    def test_partially_update_other_rr_sets(self):
        data = {'records': ['3.2.3.4'], 'ttl': 334}
        for subname in self.SUBNAMES:
            response = self.client.patch_rr_set(self.other_rr_set_domain.name, subname, 'A', data)
            self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    def test_update_other_rr_sets(self):
        data = {'ttl': 305}
        for subname in self.SUBNAMES:
            response = self.client.patch_rr_set(self.other_rr_set_domain.name, subname, 'A', data)
            self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    def test_update_essential_properties(self):
        # Changing the subname is expected to cause an error
        url = self.reverse('v1:rrset', name=self.my_rr_set_domain.name, subname='test', type='A')
        data = {'records': ['3.2.3.4'], 'ttl': 3620, 'subname': 'test2', 'type': 'A'}
        response = self.client.patch(url, data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertEquals(response.data['subname'][0].code, 'read-only-on-update')
        response = self.client.put(url, data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertEquals(response.data['subname'][0].code, 'read-only-on-update')

        # Changing the type is expected to cause an error
        data = {'records': ['3.2.3.4'], 'ttl': 3620, 'subname': 'test', 'type': 'TXT'}
        response = self.client.patch(url, data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertEquals(response.data['type'][0].code, 'read-only-on-update')
        response = self.client.put(url, data)
        self.assertStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertEquals(response.data['type'][0].code, 'read-only-on-update')

        # Changing "created" is no-op
        response = self.client.get(url)
        data = response.data
        created = data['created']
        data['created'] = '2019-07-19T17:22:49.575717Z'
        response = self.client.patch(url, data)
        self.assertStatus(response, status.HTTP_200_OK)
        response = self.client.put(url, data)
        self.assertStatus(response, status.HTTP_200_OK)

        # Check that nothing changed
        response = self.client.get(url)
        self.assertStatus(response, status.HTTP_200_OK)
        self.assertEqual(response.data['records'][0], '2.2.3.4')
        self.assertEqual(response.data['ttl'], 3620)
        self.assertEqual(response.data['name'], 'test.' + self.my_rr_set_domain.name + '.')
        self.assertEqual(response.data['subname'], 'test')
        self.assertEqual(response.data['type'], 'A')
        self.assertEqual(response.data['created'], created)

        # This is expected to work, but the fields are ignored
        data = {'records': ['3.2.3.4'], 'name': 'example.com.', 'domain': 'example.com'}
        with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_rr_set_domain.name)):
            response = self.client.patch(url, data)
            self.assertStatus(response, status.HTTP_200_OK)

        response = self.client.get(url)
        self.assertStatus(response, status.HTTP_200_OK)
        self.assertEqual(response.data['records'][0], '3.2.3.4')
        self.assertEqual(response.data['domain'], self.my_rr_set_domain.name)
        self.assertEqual(response.data['name'], 'test.' + self.my_rr_set_domain.name + '.')

    def test_update_unknown_rrset(self):
        url = self.reverse('v1:rrset', name=self.my_rr_set_domain.name, subname='doesnotexist', type='A')
        data = {'records': ['3.2.3.4'], 'ttl': 3620}

        response = self.client.patch(url, data)
        self.assertStatus(response, status.HTTP_404_NOT_FOUND)

        response = self.client.put(url, data)
        self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    def test_delete_my_rr_sets_with_patch(self):
        data = {'records': []}
        for subname in self.SUBNAMES:
            with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_rr_set_domain.name)):
                response = self.client.patch_rr_set(self.my_rr_set_domain.name, subname, 'A', data)
                self.assertStatus(response, status.HTTP_204_NO_CONTENT)

            # Deletion is only idempotent via DELETE. For PATCH/PUT, the view raises 404 if the instance does not
            # exist. By that time, the view has not parsed the payload yet and does not know it is a deletion.
            response = self.client.patch_rr_set(self.my_rr_set_domain.name, subname, 'A', data)
            self.assertStatus(response, status.HTTP_404_NOT_FOUND)

            response = self.client.get_rr_set(self.my_rr_set_domain.name, subname, 'A')
            self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    def test_delete_my_rr_sets_with_delete(self):
        for subname in self.SUBNAMES:
            with self.assertPdnsRequests(self.requests_desec_rr_sets_update(name=self.my_rr_set_domain.name)):
                response = self.client.delete_rr_set(self.my_rr_set_domain.name, subname=subname, type_='A')
                self.assertStatus(response, status.HTTP_204_NO_CONTENT)
                domain = Domain.objects.get(name=self.my_rr_set_domain.name)
                self.assertEqual(domain.touched, domain.published)

            response = self.client.delete_rr_set(self.my_rr_set_domain.name, subname=subname, type_='A')
            self.assertStatus(response, status.HTTP_204_NO_CONTENT)

            response = self.client.get_rr_set(self.my_rr_set_domain.name, subname=subname, type_='A')
            self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    def test_delete_other_rr_sets(self):
        data = {'records': []}
        for subname in self.SUBNAMES:
            # Try PATCH empty
            response = self.client.patch_rr_set(self.other_rr_set_domain.name, subname, 'A', data)
            self.assertStatus(response, status.HTTP_404_NOT_FOUND)

            # Try DELETE
            response = self.client.delete_rr_set(self.other_rr_set_domain.name, subname, 'A')
            self.assertStatus(response, status.HTTP_404_NOT_FOUND)

            # Make sure it actually is still there
            self.assertGreater(len(self.other_rr_set_domain.rrset_set.filter(subname=subname, type='A')), 0)

    def test_import_rr_sets(self):
        with self.assertPdnsRequests(self.request_pdns_zone_retrieve(name=self.my_domain.name)):
            call_command('sync-from-pdns', self.my_domain.name)
        for response in [
            self.client.get_rr_sets(self.my_domain.name),
            self.client.get_rr_sets(self.my_domain.name, subname=''),
        ]:
            self.assertStatus(response, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 1, response.data)
            self.assertContainsRRSets(response.data, [dict(subname='', records=settings.DEFAULT_NS, type='NS')])
