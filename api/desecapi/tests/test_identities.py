from desecapi import models
from desecapi.tests.base import DesecTestCase

CERTIFICATE = r"""-----BEGIN CERTIFICATE-----
MIIFXzCCBEegAwIBAgISBCpjR1Aco6QfGqTdBrLb3uFZMA0GCSqGSIb3DQEBCwUA
MDIxCzAJBgNVBAYTAlVTMRYwFAYDVQQKEw1MZXQncyBFbmNyeXB0MQswCQYDVQQD
EwJSMzAeFw0yMTAxMTQwNzQyMDlaFw0yMTA0MTQwNzQyMDlaMB0xGzAZBgNVBAMM
EiouZXhhbXBsZS5kZWR5bi5pbzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoC
ggEBAMn/csv0cxjfsDZQvbkAm+owpSaRKob+bsaBNCKsP79XetMdebL7Qp7uFaQp
gcYAD08HMtCv85JoA8N4HFPWQB+ppjXHaDqG6fQkDUPhP+IglqLKhiFNHrcZwNVq
3OLxT/Sjg7TP0zWKPQRaflz/hMpqYCsXvpdsfeSHcCOBOb8d7gjmmhpaghhsWE12
jKEHVLHjotc8nRHp3ufxXIHu5Z0XblP/ohnDWKT/eg8lDD/lE95PAgsxpuKQUP8W
eihOyg2GBRmlCaSadyKslOpK8Bhve5utPTYkWP7dshpzprL/gponuI44h+KXe9Se
58u0acqqYEPrPPk6bIpIcHvG1o0CAwEAAaOCAoIwggJ+MA4GA1UdDwEB/wQEAwIF
oDAdBgNVHSUEFjAUBggrBgEFBQcDAQYIKwYBBQUHAwIwDAYDVR0TAQH/BAIwADAd
BgNVHQ4EFgQUf1fUPkIolo4+mV11XDLl6R499y4wHwYDVR0jBBgwFoAUFC6zF7dY
VsuuUAlA5h+vnYsUwsYwVQYIKwYBBQUHAQEESTBHMCEGCCsGAQUFBzABhhVodHRw
Oi8vcjMuby5sZW5jci5vcmcwIgYIKwYBBQUHMAKGFmh0dHA6Ly9yMy5pLmxlbmNy
Lm9yZy8wUQYDVR0RBEowSIIYKi5kZWR5bi5leGFtcGxlLmRlZHluLmlvghgqLmRl
c2VjLmV4YW1wbGUuZGVkeW4uaW+CEiouZXhhbXBsZS5kZWR5bi5pbzBMBgNVHSAE
RTBDMAgGBmeBDAECATA3BgsrBgEEAYLfEwEBATAoMCYGCCsGAQUFBwIBFhpodHRw
Oi8vY3BzLmxldHNlbmNyeXB0Lm9yZzCCAQUGCisGAQQB1nkCBAIEgfYEgfMA8QB2
APZclC/RdzAiFFQYCDCUVo7jTRMZM7/fDC8gC8xO8WTjAAABdwAPKecAAAQDAEcw
RQIgMTqvW5jK+wy/77A7G+8ty4bjAMcqTSVA11cbYoBjx2gCIQD9KYwutem+G/Vu
nrTAMzIhoK4ckyOFft5nszGaBwgcTgB3AG9Tdqwx8DEZ2JkApFEV/3cVHBHZAsEA
KQaNsgiaN9kTAAABdwAPKrIAAAQDAEgwRgIhAMChRP6aIpAgK/0RhxJy5BHwxINO
rI5aH606hLqr1adwAiEAhxxBTD8hI/X73E6f/dWgPeBXIodH3WFnTtpG6+Ex0L0w
DQYJKoZIhvcNAQELBQADggEBADbPwMfqA3wd5iFBFtppEIgqPVdyA3rIci1DDo2D
NwF4gjfJQEWPkSEAbgl/EpeDQzDOLwwHMYAqupqf9RfteN38i00fSNcGVPSExdcU
/9bzGxHpXmoCMKsgoM0rgnlLNXPK9WlRCyun4VsJzsT2g/CDrYm+qysMXjUg5BWV
GHsBo84w0KXj3TvpWOSMlBZyORdugu3Bix4R8F/A5jv9gh2LT5Nc0hzhQn1g7r2x
qWiksTqmAMBtBKY7CaGXevaygr42XMp8FhIt7bU3ndr0yHu/gxPJB0qLHn/hvz5F
VqgFUBTfxglKMUZ09W+6rBYqEKplpOhKgjXdrnChWgc/5ZM=
-----END CERTIFICATE-----"""
SUBJECT_NAMES = {'*.dedyn.example.dedyn.io', '*.desec.example.dedyn.io', '*.example.dedyn.io'}


class TLSAIdentityTest(DesecTestCase):

    def read_subject_names(self):
        id = models.TLSIdentity(certificate=CERTIFICATE, owner=self.user)
        self.assertEqual(id.subject_names, SUBJECT_NAMES)

    def test_generated_rrs_many_rrsets(self):
        domain = models.Domain(name='example.dedyn.io', owner=self.user)
        domain.save()

        id = models.TLSIdentity(certificate=CERTIFICATE, owner=self.user, protocol=models.TLSIdentity.Protocol.SCTP)

        self.assertEqual(
            id.domains_subnames(),
            {(domain, '_443._sctp'), (domain, '_443._sctp.desec'), (domain, '_443._sctp.dedyn')},
        )

        rrs = id.get_rrs()
        self.assertEqual(len(rrs), 3)

        for rr in rrs:
            self.assertEqual(rr.rrset.type, "TLSA")
            self.assertEqual(rr.content, "3 1 1 9a3a491fe2dd6e4e0b7bf20a5bb62dd6212337642dcd7f4449d0b43dee4a8642")

        self.assertEqual(
            {rr.rrset.subname for rr in rrs},
            {"_443._sctp", "_443._sctp.desec", "_443._sctp.dedyn"},
        )

    def test_generated_rrs_one_rrset(self):
        domain = models.Domain(name='desec.example.dedyn.io', owner=self.user)
        domain.save()

        id = models.TLSIdentity(certificate=CERTIFICATE, owner=self.user, port=123)
        self.assertEqual(id.domains_subnames(), {(domain, '_123._tcp')})

        rrs = id.get_rrs()
        self.assertEqual(len(rrs), 1)
        rr = rrs[0]

        self.assertEqual(rr.rrset.type, "TLSA")
        self.assertEqual(rr.rrset.subname, '_123._tcp')
        self.assertEqual(rr.content, "3 1 1 9a3a491fe2dd6e4e0b7bf20a5bb62dd6212337642dcd7f4449d0b43dee4a8642")

    def test_generated_rr_params(self):
        domain = models.Domain(name='desec.example.dedyn.io', owner=self.user)
        domain.save()
        rrs = models.TLSIdentity(certificate=CERTIFICATE, owner=self.user, port=123,
                                 tlsa_matching_type=models.TLSIdentity.MatchingType.SHA512,
                                 tlsa_certificate_usage=models.TLSIdentity.CertificateUsage.TRUST_ANCHOR_ASSERTION
                                 ).get_rrs()
        self.assertEqual(
            rrs[0].content,
            "2 1 2 7e0c4276239bae692e17c748a53facf67599c05297ccd139f3b99822891ed"
            "a1278fcd0d2cc5c932e3e3c38e5f5155038bf7135fb41c3afa0bc0abb245c4f2e62"
        )

    def test_create_delete_rrs(self):
        domain = models.Domain(name='desec.example.dedyn.io', owner=self.user)
        domain.save()

        rrset = models.RRset(domain=domain, type='TLSA', subname='_123._tcp', ttl=1234)
        rrset.save()

        custom_rr = models.RR(rrset=rrset, content="3 1 1 deadbeef")
        custom_rr.save()

        id = models.TLSIdentity(
            certificate=CERTIFICATE, owner=self.user, port=123,
            tlsa_matching_type=models.TLSIdentity.MatchingType.SHA512,
            tlsa_certificate_usage=models.TLSIdentity.CertificateUsage.TRUST_ANCHOR_ASSERTION,
        )
        id.save()

        rrset = models.RRset.objects.get(domain__name='desec.example.dedyn.io', type='TLSA', subname='_123._tcp')
        self.assertEqual(len(rrset.records.all()), 2)

        id.delete()
        rrset = models.RRset.objects.get(domain__name='desec.example.dedyn.io', type='TLSA', subname='_123._tcp')
        self.assertEqual(len(rrset.records.all()), 1)
