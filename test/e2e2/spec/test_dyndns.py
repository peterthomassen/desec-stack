import ipaddress
import os

from conftest import DeSECAPIV1Client, query_replication, NSLordClient, assert_eventually

import base64
import pytest


ipv4_net = os.environ['DESECSTACK_IPV4_REAR_PREFIX16'] + '.0.127'
ipv6_net = os.environ['DESECSTACK_IPV6_SUBNET']
update_url = "https://update.dedyn." + os.environ["DESECSTACK_DOMAIN"] + "/"
update6_url = "https://update6.dedyn." + os.environ["DESECSTACK_DOMAIN"] + "/"


@pytest.mark.parametrize("subname", [None, '', 'foo', '*.bar'])
@pytest.mark.parametrize("base_url", [update_url, update6_url])
@pytest.mark.parametrize("auth_method", ['basic', 'token', 'query'])
def test(api_user_lps_domain: DeSECAPIV1Client, auth_method, base_url, subname):
    domain = api_user_lps_domain.domain
    api_headers = api_user_lps_domain.headers.copy()

    def _ips_in_network(ip_set, network):
        return all(ipaddress.ip_address(ip) in ipaddress.ip_network(network) for ip in ip_set)

    def do_test(url, headers, params, expected_ipv4, expected_ipv6, subname):
        subname = subname or ''
        api_user_lps_domain.headers = headers.copy()
        response = api_user_lps_domain.get(url, params=params)
        assert response.status_code == 200
        assert response.text == 'good'

        api_user_lps_domain.headers = api_headers.copy()
        rrs_api = {
            qtype: {
                record
                for rrset in api_user_lps_domain.get(f'/domains/{domain}/rrsets/?subname={subname}&type={qtype}').json()
                for record in rrset['records']
            }
            for qtype in ['A', 'AAAA']
        }
        rrs_dns = {qtype: NSLordClient.query(params.get('hostname', domain), qtype)[1] for qtype in ['A', 'AAAA']}

        for expected_net, qtype in [(expected_ipv4, 'A'), (expected_ipv6, 'AAAA')]:
            assert len(rrs_api[qtype]) == (1 if expected_net else 0)
            assert len(rrs_dns[qtype]) == (1 if expected_net else 0)
            assert _ips_in_network(rrs_api[qtype], expected_net)
            assert _ips_in_network(rrs_dns[qtype], expected_net)
            assert_eventually(lambda: _ips_in_network(query_replication(domain, '', qtype), expected_net))

    headers = {}
    params = {}
    if auth_method == 'token':
        headers['Authorization'] = api_user_lps_domain.headers["Authorization"]
    elif auth_method == 'basic':
        credentials = base64.b64encode(f'{api_user_lps_domain.domain}:{api_user_lps_domain.token}'.encode()).decode()
        headers["Authorization"] = f'Basic {credentials}'
    elif auth_method == 'query':
        params = {'username': api_user_lps_domain.domain, 'password': api_user_lps_domain.token}
    else:
        raise ValueError

    if subname is not None:
        params['hostname'] = f'{subname}.{domain}'.lstrip('.')

    update6 = base_url.startswith('https://update6.')
    do_test(base_url, headers, params, expected_ipv4=None if update6 else ipv4_net,
            expected_ipv6=ipv6_net if update6 else None, subname=subname)

    for extra_params, expected_ipv4, expected_ipv6 in [
        [dict(ip='1.2.3.4'), '1.2.3.4', ipv6_net if update6 else None],
        [dict(ip='', ipv6='bade::affe'), None, 'bade::affe'],
        [dict(ipv6='dead::beef'), None if update6 else ipv4_net, 'dead::beef'],
        [dict(ip='1.3.3.7', ipv6=''), '1.3.3.7', None],
        [dict(ip='192.168.1.1', ipv6='::1'), '192.168.1.1', '::1'],
    ]:
        do_test(base_url + 'update/', headers, dict(params, **extra_params), expected_ipv4, expected_ipv6, subname)
