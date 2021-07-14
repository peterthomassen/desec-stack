import pytest

from conftest import DeSECAPIV1Client


@pytest.mark.parametrize("init_rrsets", [
    {
        ('www', 'A'): (3600, {'1.2.3.4'}),
        ('www', 'AAAA'): (3600, {'::1'}),
        ('one', 'CNAME'): (3600, {'some.example.net.'}),
        ('other', 'TXT'): (3600, {'"foo" "bar"', '"bar" "foo"'}),
    }
])
@pytest.mark.parametrize("rrsets", [
    {  # create three RRsets
        ('a' * 63, 'A'): (7000, {'4.3.2.1', '7.6.5.4'}),
        ('b', 'PTR'): (7000, {'1.foo.bar.com.', '2.bar.foo.net.'}),
        ('c.' + 'a' * 63, 'MX'): (7000, {'10 mail.something.net.'}),
    },
    {  # update three RRsets
        ('www', 'A'): None,  # ensure value from init_rrset is still there
        ('www', 'AAAA'): (7000, {'6666::6666', '7777::7777'}),
        ('one', 'CNAME'): (7000, {'other.example.net.'}),
        ('other', 'TXT'): (7000, {'"foobar"'}),
    },
    {  # delete three RRsets
        ('www', 'A'): (7000, {}),
        ('www', 'AAAA'): None,  # ensure value from init_rrset is still there
        ('one', 'CNAME'): (7000, {}),
        ('other', 'TXT'): (7000, {}),
    },
    {  # create, update, delete
        ('a' * 63, 'A'): (7000, {'4.3.2.1', '7.6.5.4'}),
        ('www', 'A'): None,  # ensure value from init_rrset is still there
        ('www', 'AAAA'): (7000, {'6666::6666', '7777::7777'}),
        ('one', 'CNAME'): None,  # ensure value from init_rrset is still there
        ('other', 'TXT'): (7000, {}),
    },
    {  # complex usecase
        ('', 'A'): (3600, {'1.2.3.4', '255.254.253.252'}),  # create apex reocrd
        ('*', 'MX'): (3601, {'0 mx.example.net.'}),  # create wildcard record
        ('www', 'AAAA'): (3602, {}),  # remove existing record
        ('www', 'A'): (7000, {'4.3.2.1', '7.6.5.4'}),  # update existing record
        ('one', 'A'): (3603, {'1.1.1.1'}),  # configure A instead of ...
        ('one', 'CNAME'): (3603, {}),  # ... CNAME
        ('other', 'CNAME'): (3603, {'cname.example.com.'}),  # configure CNAME instead of ...
        ('other', 'TXT'): (3600, {}),  # ... TXT
        ('nonexistent', 'DNAME'): (3600, {}),  # delete something that doesn't exist
        ('sub', 'DNSKEY'): (3600, {'257 3 15 l02Woi0iS8Aa25FQkUd9RMzZHJpBoRQwAQEX1SxZJA4='}),  # non-apex DNSSEC
        ('sub', 'CDNSKEY'): (3600, {'257 3 15 l02Woi0iS8Aa25FQkUd9RMzZHJpBoRQwAQEX1SxZJA4='}),  # non-apex DNSSEC
        ('sub', 'CDS'): (3600, {'35217 15 2 401781b934e392de492ec77ae2e15d70f6575a1c0bc59c5275c04ebe80c6614c'}),  # dto.
    },
])
def test(api_user_domain_rrsets: DeSECAPIV1Client, rrsets: dict):
    api_user_domain_rrsets.patch(f"/domains/{api_user_domain_rrsets.domain}/rrsets/", data=[
        {"subname": k[0], "type": k[1], "ttl": v[0], "records": list(v[1])}
        for k, v in rrsets.items()
        if v is not None
    ])
    api_user_domain_rrsets.assert_rrsets(rrsets)
