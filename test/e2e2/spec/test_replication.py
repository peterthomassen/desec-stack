import pytest

from conftest import DeSECAPIV1Client, return_eventually, query_replication, random_domainname, assert_eventually, \
    FaketimeShift


some_ds_records = [
    '60604 8 1 ef66f772935b412376c8445c4442b802b0322814',
    '60604 8 2 c2739629145faaf464ff1bc65612fd1eb5766e80c96932d808edfb55d1e1f2ce',
    '60604 8 4 5943dac4fc4aad637445f483b0f43bd4152fab19250fd26df82bf12020a7f7101caa17e723cf433f43d2bbed11231e03',
]


def test_signature_rotation(api_user_domain: DeSECAPIV1Client):
    name = random_domainname()
    api_user_domain.domain_create(name)
    rrsig = return_eventually(lambda: query_replication(name, "", 'RRSIG', covers='SOA'), timeout=20)
    with FaketimeShift(days=7):
        assert_eventually(lambda: rrsig != query_replication(name, "", 'RRSIG', covers='SOA'), timeout=60)


def test_zone_deletion(api_user_domain: DeSECAPIV1Client):
    name = api_user_domain.domain
    assert_eventually(lambda: query_replication(name, "", 'SOA') is not None, timeout=20)
    api_user_domain.domain_destroy(name)
    assert_eventually(lambda: query_replication(name, "", 'SOA') is None, timeout=20)


@pytest.mark.performance
def test_signature_rotation_performance(api_user_domain: DeSECAPIV1Client):
    root_domain = api_user_domain.domain

    # test configuration
    bulk_block_size = 500
    domain_sizes = {
        # number of delegations: number of zones
        2000: 1,
        1000: 2,
        10: 10,
    }

    # create test domains
    domain_names = {
        num_delegations: [random_domainname() + f'.num-ds-{num_delegations}.' + root_domain for _ in range(num_zones)]
        for num_delegations, num_zones in domain_sizes.items()
    }
    for num_delegations, names in domain_names.items():
        for name in names:
            # create a domain with name `name` and `num_delegations` delegations
            api_user_domain.domain_create(name)
            for a in range(0, num_delegations, bulk_block_size):  # run block-wise to avoid exceeding max request size
                r = api_user_domain.rr_set_create_bulk(
                    name,
                    [
                        {"subname": f'x{i}', "type": "DS", "ttl": 3600, "records": some_ds_records}
                        for i in range(a, a + bulk_block_size)
                    ] + [
                        {"subname": f'x{i}', "type": "NS", "ttl": 3600, "records": ['ns1.test.', 'ns2.test.']}
                        for i in range(a, a + bulk_block_size)
                    ]
                )
                assert r.status_code == 200

    # retrieve all SOA RRSIGs
    soa_rrsig = {}
    for names in domain_names.values():
        for name in names:
            soa_rrsig[name] = return_eventually(lambda: query_replication(name, "", 'RRSIG', covers='SOA'), timeout=20)

    # rotate signatures
    with FaketimeShift(days=7):
        # assert SOA RRSIG has been updated
        for names in domain_names.values():
            for name in names:
                assert_eventually(
                    lambda: soa_rrsig[name] != query_replication(name, "", 'RRSIG', covers='SOA'),
                    timeout=600,  # depending on number of domains in the database, this value requires increase
                )
