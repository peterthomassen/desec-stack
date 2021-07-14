from typing import List, Tuple

import pytest

from conftest import DeSECAPIV1Client, query_replication, NSLordClient, assert_eventually


def generate_params(dict_value_lists_by_type: dict) -> List[Tuple[str, str]]:
    return [
        (rr_type, value)
        for rr_type in dict_value_lists_by_type.keys()
        for value in dict_value_lists_by_type[rr_type]
    ]


VALID_RECORDS_CANONICAL = {
    'A': ['127.0.0.1', '127.0.0.2'],
    'AAAA': ['::1', '::2'],
    'AFSDB': ['2 turquoise.femto.edu.'],
    'APL': [
        # from RFC 3123 Sec. 4
        '1:192.168.32.0/21 !1:192.168.38.0/28',
        '1:192.168.42.0/26 1:192.168.42.64/26 1:192.168.42.128/25',
        '1:127.0.0.1/32 1:172.16.64.0/22',
        '1:224.0.0.0/4 2:ff00::/8',
    ],
    'CAA': [
        '128 issue "letsencrypt.org"', '128 iodef "mailto:desec@example.com"',
        '1 issue "letsencrypt.org"'
    ],
    'CDNSKEY': [
        None,
        '256 3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5O fv4akjQGN2zY5AgB/2jmdR/+1PvXFqzK CAGJv4wjABEBNWLLFm7ew1hHMDZEKVL1 7aml0EBKI6Dsz6Mxt6n7ScvLtHaFRKax T4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0 P+2F+TLKl3D0L/cD',
        '257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy 9mvL5qGQTuaG5TSrNqEAR6b/qvxDx6my 4JmEmjUPA1JeEI9YfTUieMr2UZflu7aI bZFLw0vqiYrywCGrCHXLalOrEOmrvAxL vq4vHtuTlH7JIszzYBSes8g1vle6KG7x XiP3U5Ll96Qiu6bZ31rlMQSPB20xbqJJ h6psNSrQs41QvdcXAej+K2Hl1Wd8kPri ec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFa W2m7N/Wy4qcFU13roWKDEAstbxH5CHPo BfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lv u9TAiZPc0oysY6aslO7jXv16Gws=',
        '257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iD SFZNORnQuHKtJ9Wpyz+kNryquB78Pyk/ NTEoai5bxoipVQQXzHlzyg==',
    ],
    'CDS': [
        None,
        '6454 8 1 24396e17e36d031f71c354b06a979a67a01f503e',
    ],
    'CERT': ['6 0 0 sadfdQ=='],
    'CNAME': ['example.com.'],
    'DHCID': ['aaaaaaaaaaaa', 'xxxx'],
    'DLV': ['6454 8 1 24396e17e36d031f71c354b06a979a67a01f503e'],
    'DNAME': ['example.com.'],
    'DNSKEY': [
        None,
        '256 3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5O fv4akjQGN2zY5AgB/2jmdR/+1PvXFqzK CAGJv4wjABEBNWLLFm7ew1hHMDZEKVL1 7aml0EBKI6Dsz6Mxt6n7ScvLtHaFRKax T4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0 P+2F+TLKl3D0L/cD',
        '257 3 8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy 9mvL5qGQTuaG5TSrNqEAR6b/qvxDx6my 4JmEmjUPA1JeEI9YfTUieMr2UZflu7aI bZFLw0vqiYrywCGrCHXLalOrEOmrvAxL vq4vHtuTlH7JIszzYBSes8g1vle6KG7x XiP3U5Ll96Qiu6bZ31rlMQSPB20xbqJJ h6psNSrQs41QvdcXAej+K2Hl1Wd8kPri ec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFa W2m7N/Wy4qcFU13roWKDEAstbxH5CHPo BfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lv u9TAiZPc0oysY6aslO7jXv16Gws=',
        '257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iD SFZNORnQuHKtJ9Wpyz+kNryquB78Pyk/ NTEoai5bxoipVQQXzHlzyg==',
    ],
    'DS': ['6454 8 1 24396e17e36d031f71c354b06a979a67a01f503e'],
    'EUI48': ['aa-bb-cc-dd-ee-ff'],
    'EUI64': ['aa-bb-cc-dd-ee-ff-00-11'],
    'HINFO': ['"ARMv8-A" "Linux"'],
    'HTTPS': ['1 h3POOL.exaMPLe. alpn=h2,h3 echconfig="MTIzLi4uCg=="'],
    # 'IPSECKEY': ['12 0 2 . asdfdf==', '03 1 1 127.0.00.1 asdfdf==', '12 3 1 example.com. asdfdf==',],
    'KX': ['4 example.com.', '28 io.', '0 .'],
    'LOC': [
        '23 12 59.000 N 42 22 48.500 W 65.00m 20.00m 10.00m 10.00m',
    ],
    'MX': ['10 example.com.', '20 1.1.1.1.'],
    'NAPTR': [
        '100 50 "s" "z3950+I2L+I2C" "" _z3950._tcp.gatech.edu.',
    ],
    'NS': ['ns1.example.com.'],
    'OPENPGPKEY': [
        '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',
    ],
    'PTR': ['example.com.', '*.example.com.'],
    'RP': ['hostmaster.example.com. .'],
    'SMIMEA': ['3 1 0 aabbccddeeff'],
    'SPF': [
        '"v=spf1 ip4:10.1" ".1.1 ip4:127" ".0.0.0/16 ip4:192.168.0.0/27 include:example.com -all"',
        '"v=spf1 include:example.com ~all"',
        '"v=spf1 ip4:10.1.1.1 ip4:127.0.0.0/16 ip4:192.168.0.0/27 include:example.com -all"',
        '"spf2.0/pra,mfrom ip6:2001:558:fe14:76:68:87:28:0/120 -all"',
    ],
    'SRV': ['0 0 0 .', '100 1 5061 example.com.'],
    'SSHFP': ['2 2 aabbcceeddff'],
    'SVCB': ['2 sVc2.example.NET. port=1234 echconfig="MjIyLi4uCg==" ipv6hint=2001:db8::2'],
    'TLSA': ['3 0 2 696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd 696b8f6b92a913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd',],
    'TXT': [
        '"foobar"',
        '"foo" "bar"',
        '"foo" "" "bar"',
        '"" "" "foo" "" "bar"',
        r'"new\010line"',
        r'"\000" "NUL byte yo"',
        r'"\130\164name\164Boss\164type\1611"',  # binary stuff with first bit 1
        f'"{"a" * 255}" "{"a" * 243}"',  # 500 byte total wire length
        r'"\000\001\002\003\004\005\006\007\008\009\010\011\012\013\014\015\016\017\018\019\020\021\022\023\024\025\026\027\028\029\030\031 !\"#$%&' + "'" + r'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\127\128\129\130\131\132\133\134\135\136\137\138\139\140\141\142\143\144\145\146\147\148\149\150\151\152\153\154\155\156\157\158\159\160\161\162\163\164\165\166\167\168\169\170\171\172\173\174\175\176\177\178\179\180\181\182\183\184\185\186\187\188\189\190\191\192\193\194\195\196\197\198\199\200\201\202\203\204\205\206\207\208\209\210\211\212\213\214\215\216\217\218\219\220\221\222\223\224\225\226\227\228\229\230\231\232\233\234\235\236\237\238\239\240\241\242\243\244\245\246\247\248\249\250\251\252\253\254" "\255"',
    ],
    'URI': ['10 1 "ftp://ftp1.example.com/public"'],
}


VALID_RECORDS_NON_CANONICAL = {
    'A': ['127.0.0.3'],
    'AAAA': ['0000::0000:0003', '2001:db8::128.2.129.4'],
    'AFSDB': ['03 turquoise.FEMTO.edu.'],
    'APL': ['2:FF00:0:0:0:0::/8 !1:192.168.38.0/28'],
    'CAA': ['0128 "issue" "letsencrypt.org"'],
    'CDNSKEY': [
        '0256  3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mxt6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLKl3D0L/cD',
        '257 03  8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGrCHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPriec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAstbxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6aslO7jXv16Gws=',
        '257 3 013  aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryquB78Pyk/NTEoai5bxoipVQQXzHlzyg==',
    ],
    'CDS': [
        '06454  08   01    24396e17e36d031f71c354b06a979a67a01f503e',
        '6454 8 2 5C BA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
    ],
    'CERT': ['06 00 00 sadfee=='],
    'CNAME': ['EXAMPLE.TEST.'],
    'DHCID': ['aa aaa  aaaa a a a', 'xxxx'],
    'DLV': [
        '06454  08   01    24396e17e36d031f71c354b06a979a67a01f503e',
        '6454 8 2 5C BA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
    ],
    'DNAME': ['EXAMPLE.TEST.'],
    'DNSKEY': [
        '0256  3 8 AwEAAday3UX323uVzQqtOMQ7EHQYfD5Ofv4akjQGN2zY5AgB/2jmdR/+1PvXFqzKCAGJv4wjABEBNWLLFm7ew1hHMDZEKVL17aml0EBKI6Dsz6Mxt6n7ScvLtHaFRKaxT4i2JxiuVhKdQR9XGMiWAPQKrRM5SLG0P+2F+TLKl3D0L/cD',
        '257 03  8 AwEAAcw5QLr0IjC0wKbGoBPQv4qmeqHy9mvL5qGQTuaG5TSrNqEAR6b/qvxDx6my4JmEmjUPA1JeEI9YfTUieMr2UZflu7aIbZFLw0vqiYrywCGrCHXLalOrEOmrvAxLvq4vHtuTlH7JIszzYBSes8g1vle6KG7xXiP3U5Ll96Qiu6bZ31rlMQSPB20xbqJJh6psNSrQs41QvdcXAej+K2Hl1Wd8kPriec4AgiBEh8sk5Pp8W9ROLQ7PcbqqttFaW2m7N/Wy4qcFU13roWKDEAstbxH5CHPoBfZSbIwK4KM6BK/uDHpSPIbiOvOCW+lvu9TAiZPc0oysY6aslO7jXv16Gws=',
        '257 3 013  aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryquB78Pyk/NTEoai5bxoipVQQXzHlzyg==',
    ],
    'DS': [
        '06454  08   01    24396e17e36d031f71c354b06a979a67a01f503e',
        '6454 8 2 5C BA665A006F6487625C6218522F09BD3673C25FA10F25CB18459AA1 0DF1F520',
    ],
    'EUI48': ['AA-BB-CC-DD-EE-F1'],
    'EUI64': ['AA-BB-CC-DD-EE-FF-00-12'],
    'HINFO': ['cpu os'],
    'HTTPS': [
        # from https://tools.ietf.org/html/draft-ietf-dnsop-svcb-https-02#section-10.3, with echconfig base64'd
        '1 . alpn=h3',
        '0 pool.svc.example.',
        '1 h3pool.example. alpn=h2,h3 echconfig="MTIzLi4uCg=="',
        '2 .      alpn=h2 echconfig="YWJjLi4uCg=="',
        # made-up (not from RFC)
        '1 pool.svc.example. no-default-alpn port=1234 ipv4hint=192.168.123.1',
        '2 . echconfig=... key65333=ex1 key65444=ex2 mandatory=key65444,echconfig',  # see #section-7
    ],
    # 'IPSECKEY': ['12 0 2 . asdfdf==', '03 1 1 127.0.00.1 asdfdf==', '12 3 1 example.com. asdfdf==',],
    'KX': ['012 example.TEST.'],
    'LOC': [
        '023 012 59 N 042 022 48.500 W 65.00m 20.00m 10.00m 10.00m',
    ],
    'MX': ['10 010.1.1.1.'],
    'NAPTR': [
        '100  50  "s"  "z3950+I2L+I2C"     ""  _z3950._tcp.gatech.edu.',
    ],
    'NS': ['EXaMPLE.COM.'],
    'OPENPGPKEY': [
        'mG8EXtVIsRMFK4EEAC==',
        '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',
    ],
    'PTR': ['EXAMPLE.TEST.'],
    'RP': ['hostmaster.EXAMPLE.com. .'],
    'SMIMEA': ['3 01 0 aabbccDDeeff'],
    'SPF': [],
    'SRV': ['100 01 5061 example.com.'],
    'SSHFP': ['02 2 aabbcceeddff'],
    'SVCB': [
        '0 svc4-baz.example.net.',
        '1 . key65333=...',
        '2 svc2.example.net. echconfig="MjIyLi4uCg==" ipv6hint=2001:db8::2 port=1234',
    ],
    'TLSA': ['003 00 002 696B8F6B92A913560b23ef5720c378881faffe74432d04eb35db957c0a93987b47adf26abb5dac10ba482597ae16edb069b511bec3e26010d1927bf6392760dd',],
    'TXT': [
        f'"{"a" * 498}" ',
        '"' + 124 * '🧥' + '==="',  # 501 byte total length
        '"🧥 👚 👕 👖 👔 👗 👙 👘 👠 👡 👢 👞 👟 🥾 🥿  🧦 🧤 🧣 🎩 🧢 👒 🎓 ⛑ 👑 👝 👛 👜 💼 🎒 "',
        '"🧥 👚 👕 👖 👔 👗 👙 👘 👠 👡 👢 👞 👟 🥾 🥿  🧦 🧤 🧣 🎩 🧢 👒 🎓 ⛑ 👑 👝 👛 👜 💼 🎒 👓 🕶 🥽 🥼 🌂 🧵"',
        '"' + ''.join(fr'\{n:03}' for n in range(256)) + '"',  # all bytes
    ],
    'URI': ['10 01 "ftp://ftp1.example.test/public"',],
}


INVALID_RECORDS = {
    'A': ['127.0.0.999', '127.000.0.01', '127.0.0.256', '::1', 'foobar', '10.0.1', '10!'],
    'AAAA': ['::g', '1:1:1:1:1:1:1:1:', '1:1:1:1:1:1:1:1:1'],
    'AFSDB': ['example.com.', '1 1', '1 de'],
    'APL': [
        '0:192.168.32.0/21 !1:192.168.38.0/28',
        '1:192.168.32.0/21 !!1:192.168.38.0/28',
        '1:192.168.32.0/33',
        '18:12345/2',
        '1:127.0.0.1',
        '2:::/129',
    ],
    'CAA': ['43235 issue "letsencrypt.org"'],
    'CDNSKEY': ['a 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='],
    'CDS': [
        'a 8 1 24396E17E36D031F71C354B06A979A67A01F503E',
        '6454 8 1 aabbccddeeff',
    ],
    'CERT': ['6 0 sadfdd=='],
    'CNAME': ['example.com', '10 example.com.'],
    'DHCID': ['x', 'xx', 'xxx'],
    'DLV': ['-34 13 1 aabbccddeeff'],
    'DNAME': ['example.com', '10 example.com.'],
    'DNSKEY': ['a 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iDSFZNORnQuHKtJ9Wpyz+kNryq uB78Pyk/NTEoai5bxoipVQQXzHlzyg=='],
    'DS': [
        '-34 13 1 24396E17E36D031F71C354B06A979A67A01F503E',
        '6454 8 1 aabbccddeeff',
    ],
    'EUI48': ['aa-bb-ccdd-ee-ff', 'AA-BB-CC-DD-EE-GG'],
    'EUI64': ['aa-bb-cc-dd-ee-ff-gg-11', 'AA-BB-C C-DD-EE-FF-00-11'],
    'HINFO': ['"ARMv8-A"', f'"a" "{"b" * 256}"'],
    'HTTPS': [
        # from https://tools.ietf.org/html/draft-ietf-dnsop-svcb-https-02#section-10.3, with echconfig base64'd
        '1 h3pool alpn=h2,h3 echconfig="MTIzLi4uCg=="',
        # made-up (not from RFC)
        '0 pool.svc.example. no-default-alpn port=1234 ipv4hint=192.168.123.1',  # no keys in alias mode
        '1 pool.svc.example. no-default-alpn port=1234 ipv4hint=192.168.123.1 ipv4hint=192.168.123.2',  # dup
    ],
    # 'IPSECKEY': [],
    'KX': ['-1 example.com', '10 example.com'],
    'LOC': ['23 12 61.000 N 42 22 48.500 W 65.00m 20.00m 10.00m 10.00m', 'foo', '1.1.1.1'],
    'MX': ['10 example.com', 'example.com.', '-5 asdf.', '65537 asdf.' '10 _foo.example.com.', '10 $url.'],
    'NAPTR': ['100  50  "s"  "z3950+I2L+I2C"     ""  _z3950._tcp.gatech.edu',
              '100  50  "s"     ""  _z3950._tcp.gatech.edu.',
              '100  50  3 2  "z3950+I2L+I2C"     ""  _z3950._tcp.gatech.edu.'],
    'NS': ['ns1.example.com', '127.0.0.1'],
    'OPENPGPKEY': ['1 2 3'],
    'PTR': ['"example.com."', '10 *.example.com.'],
    'RP': ['hostmaster.example.com.', '10 foo.'],
    'SMIMEA': ['3 1 0 aGVsbG8gd29ybGQh', 'x 0 0 aabbccddeeff'],
    'SPF': ['"v=spf1', 'v=spf1 include:example.com ~all'],
    'SRV': ['0 0 0 0', '100 5061 example.com.', '0 0 16920 _foo.example.com.', '0 0 16920 $url.'],
    'SSHFP': ['aabbcceeddff'],
    'SVCB': [
        '0 svc4-baz.example.net. keys=val',
        '1 not.fully.qualified key65333=...',
        '2 duplicate.key. echconfig="MjIyLi4uCg==" echconfig="MjIyLi4uCg=="',
    ],
    'TLSA': ['3 1 1 AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'],
    'TXT': [
        'foob"ar',
        'v=spf1 include:example.com ~all',
        '"foo\nbar"',
        '"\x00" "Django rejects literal NUL byte"',
    ],
    'URI': ['"1" "2" "3"'],
}
INVALID_RECORDS_PARAMS = [(rr_type, value) for rr_type in INVALID_RECORDS.keys() for value in INVALID_RECORDS[rr_type]]


def test_soundness():
    assert INVALID_RECORDS.keys() == VALID_RECORDS_CANONICAL.keys() == VALID_RECORDS_NON_CANONICAL.keys()


@pytest.mark.parametrize("rr_type,value", generate_params(VALID_RECORDS_CANONICAL))
def test_create_valid_canonical(api_user_domain: DeSECAPIV1Client, rr_type: str, value: str):
    domain_name = api_user_domain.domain
    expected = set()
    subname = 'a'
    if rr_type in ('CDNSKEY', 'CDS', 'DNSKEY'):
        expected |= api_user_domain.get_key_params(domain_name, rr_type)
        subname = ''
    if value is not None:
        assert api_user_domain.rr_set_create(domain_name, rr_type, [value], subname=subname).status_code == 201
        expected.add(value)
    _, rrset = NSLordClient.query(f'{subname}.{domain_name}'.strip('.'), rr_type)
    assert rrset == expected
    assert_eventually(lambda: query_replication(domain_name, subname, rr_type) == expected)


@pytest.mark.parametrize("rr_type,value", generate_params(VALID_RECORDS_NON_CANONICAL))
def test_create_valid_non_canonical(api_user_domain: DeSECAPIV1Client, rr_type: str, value: str):
    domain_name = api_user_domain.domain
    expected = set()
    subname = 'a'
    if rr_type in ('CDNSKEY', 'CDS', 'DNSKEY'):
        expected |= api_user_domain.get_key_params(domain_name, rr_type)
        subname = ''
    if value is not None:
        assert api_user_domain.rr_set_create(domain_name, rr_type, [value], subname=subname).status_code == 201
        expected.add(value)
    _, rrset = NSLordClient.query(f'{subname}.{domain_name}'.strip('.'), rr_type)
    assert len(rrset) == len(expected)
    assert_eventually(lambda: len(query_replication(domain_name, subname, rr_type)) == len(expected))


@pytest.mark.parametrize("rr_type,value", INVALID_RECORDS_PARAMS)
def test_create_invalid(api_user_domain: DeSECAPIV1Client, rr_type: str, value: str):
    assert api_user_domain.rr_set_create(api_user_domain.domain, rr_type, [value]).status_code == 400


def test_create_long_subname(api_user_domain: DeSECAPIV1Client):
    subname = 'a' * 63
    assert api_user_domain.rr_set_create(api_user_domain.domain, "AAAA", ["::1"], subname=subname).status_code == 201
    assert NSLordClient.query(f"{subname}.{api_user_domain.domain}", "AAAA")[1] == {"::1"}
    assert_eventually(lambda: query_replication(api_user_domain.domain, subname, "AAAA") == {"::1"})


def test_add_remove_DNSKEY(api_user_domain: DeSECAPIV1Client):
    domain_name = api_user_domain.domain
    auto_dnskeys = api_user_domain.get_key_params(domain_name, 'DNSKEY')

    # After adding another DNSKEY, we expect it to be part of the nameserver's response (along with the automatic ones)
    value = '257 3 13 aCoEWYBBVsP9Fek2oC8yqU8ocKmnS1iD SFZNORnQuHKtJ9Wpyz+kNryquB78Pyk/ NTEoai5bxoipVQQXzHlzyg=='
    assert api_user_domain.rr_set_create(domain_name, 'DNSKEY', [value], subname='').status_code == 201
    assert NSLordClient.query(domain_name, 'DNSKEY')[1] == auto_dnskeys | {value}
    assert_eventually(lambda: query_replication(domain_name, '', 'DNSKEY') == auto_dnskeys | {value})

    # After deleting it, we expect that the automatically managed ones are still there
    assert api_user_domain.rr_set_delete(domain_name, "DNSKEY", subname='').status_code == 204
    assert NSLordClient.query(domain_name, 'DNSKEY')[1] == auto_dnskeys
    assert_eventually(lambda: query_replication(domain_name, '', 'DNSKEY') == auto_dnskeys)
