from __future__ import annotations

import binascii
import ipaddress
import json
import logging
import re
import secrets
import string
import time
import uuid
from datetime import timedelta
from functools import cached_property
from hashlib import sha256
from typing import Set, List, Optional, Tuple, Dict

import dns
import psl_dns
import rest_framework.authtoken.models
from cryptography import x509, hazmat
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser, BaseUserManager
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, CIEmailField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, get_connection
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import CharField, F, Manager, Q, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Concat, Length
from django.template.loader import get_template
from django.utils import timezone
from django_prometheus.models import ExportModelOperationsMixin
from dns import rdataclass, rdatatype
from dns.exception import Timeout
from dns.rdtypes import ANY, IN
from dns.resolver import NoNameservers
from netfields import CidrAddressField, NetManager
from rest_framework.exceptions import APIException

from desecapi import metrics
from desecapi import pdns
from desecapi.dns import CDS, DLV, DS, LongQuotedTXT

logger = logging.getLogger(__name__)
psl = psl_dns.PSL(resolver=settings.PSL_RESOLVER, timeout=.5)


def validate_lower(value):
    if value != value.lower():
        raise ValidationError('Invalid value (not lowercase): %(value)s',
                              code='invalid',
                              params={'value': value})


def validate_upper(value):
    if value != value.upper():
        raise ValidationError('Invalid value (not uppercase): %(value)s',
                              code='invalid',
                              params={'value': value})


class MyUserManager(BaseUserManager):
    def create_user(self, email, password, **extra_fields):
        """
        Creates and saves a User with the given email, date of
        birth and password.
        """
        if not email:
            raise ValueError('Users must have an email address')

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password):
        """
        Creates and saves a superuser with the given email, date of
        birth and password.
        """
        user = self.create_user(email, password=password)
        user.is_admin = True
        user.save(using=self._db)
        return user


class User(ExportModelOperationsMixin('User'), AbstractBaseUser):
    @staticmethod
    def _limit_domains_default():
        return settings.LIMIT_USER_DOMAIN_COUNT_DEFAULT

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = CIEmailField(
        verbose_name='email address',
        unique=True,
    )
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    limit_domains = models.IntegerField(default=_limit_domains_default.__func__, null=True, blank=True)
    needs_captcha = models.BooleanField(default=True)

    objects = MyUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def get_full_name(self):
        return self.email

    def get_short_name(self):
        return self.email

    def __str__(self):
        return self.email

    # noinspection PyMethodMayBeStatic
    def has_perm(self, *_):
        """Does the user have a specific permission?"""
        # Simplest possible answer: Yes, always
        return True

    # noinspection PyMethodMayBeStatic
    def has_module_perms(self, *_):
        """Does the user have permissions to view the app `app_label`?"""
        # Simplest possible answer: Yes, always
        return True

    @property
    def is_staff(self):
        """Is the user a member of staff?"""
        # Simplest possible answer: All admins are staff
        return self.is_admin

    def activate(self):
        self.is_active = True
        self.needs_captcha = False
        self.save()

    def change_email(self, email):
        old_email = self.email
        self.email = email
        self.validate_unique()
        self.save()

        self.send_email('change-email-confirmation-old-email', recipient=old_email)

    def change_password(self, raw_password):
        self.set_password(raw_password)
        self.save()
        self.send_email('password-change-confirmation')

    def delete(self):
        pk = self.pk
        ret = super().delete()
        logger.warning(f'User {pk} deleted')
        return ret

    def send_email(self, reason, context=None, recipient=None):
        fast_lane = 'email_fast_lane'
        slow_lane = 'email_slow_lane'
        immediate_lane = 'email_immediate_lane'
        lanes = {
            'activate': slow_lane,
            'activate-with-domain': slow_lane,
            'change-email': slow_lane,
            'change-email-confirmation-old-email': fast_lane,
            'password-change-confirmation': fast_lane,
            'reset-password': fast_lane,
            'delete-user': fast_lane,
            'domain-dyndns': fast_lane,
            'renew-domain': immediate_lane,
        }
        if reason not in lanes:
            raise ValueError(f'Cannot send email to user {self.pk} without a good reason: {reason}')

        context = context or {}
        content = get_template(f'emails/{reason}/content.txt').render(context)
        content += f'\nSupport Reference: user_id = {self.pk}\n'
        footer = get_template('emails/footer.txt').render()

        logger.warning(f'Queuing email for user account {self.pk} (reason: {reason}, lane: {lanes[reason]})')
        num_queued = EmailMessage(
            subject=get_template(f'emails/{reason}/subject.txt').render(context).strip(),
            body=content + footer,
            from_email=get_template('emails/from.txt').render(),
            to=[recipient or self.email],
            connection=get_connection(lane=lanes[reason], debug={'user': self.pk, 'reason': reason})
        ).send()
        metrics.get('desecapi_messages_queued').labels(reason, self.pk, lanes[reason]).observe(num_queued)
        return num_queued


validate_domain_name = [
    validate_lower,
    RegexValidator(
        regex=r'^(([a-z0-9_-]{1,63})\.)*[a-z0-9-]{1,63}$',
        message='Domain names must be labels separated by dots. Labels may consist of up to 63 letters, digits, '
                'hyphens, and underscores. The last label may not contain an underscore.',
        code='invalid_domain_name',
        flags=re.IGNORECASE
    )
]


class DomainManager(Manager):
    def filter_qname(self, qname: str, **kwargs) -> models.query.QuerySet:
        try:
            Domain._meta.get_field('name').run_validators(qname)
        except ValidationError:
            raise ValueError
        return self.annotate(
            dotted_name=Concat(Value('.'), 'name', output_field=CharField()),
            dotted_qname=Value(f'.{qname}', output_field=CharField()),
            name_length=Length('name'),
        ).filter(dotted_qname__endswith=F('dotted_name'), **kwargs)


class Domain(ExportModelOperationsMixin('Domain'), models.Model):
    @staticmethod
    def _minimum_ttl_default():
        return settings.MINIMUM_TTL_DEFAULT

    class RenewalState(models.IntegerChoices):
        IMMORTAL = 0
        FRESH = 1
        NOTIFIED = 2
        WARNED = 3

    created = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=191,
                            unique=True,
                            validators=validate_domain_name)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='domains')
    published = models.DateTimeField(null=True, blank=True)
    replicated = models.DateTimeField(null=True, blank=True)
    replication_duration = models.DurationField(null=True, blank=True)
    minimum_ttl = models.PositiveIntegerField(default=_minimum_ttl_default.__func__)
    renewal_state = models.IntegerField(choices=RenewalState.choices, default=RenewalState.IMMORTAL)
    renewal_changed = models.DateTimeField(auto_now_add=True)

    _keys = None
    objects = DomainManager()

    def __init__(self, *args, **kwargs):
        if isinstance(kwargs.get('owner'), AnonymousUser):
            kwargs = {**kwargs, 'owner': None}  # make a copy and override
        # Avoid super().__init__(owner=None, ...) to not mess up *values instantiation in django.db.models.Model.from_db
        super().__init__(*args, **kwargs)
        if self.pk is None and kwargs.get('renewal_state') is None and self.is_locally_registrable:
            self.renewal_state = Domain.RenewalState.FRESH

    @cached_property
    def public_suffix(self):
        try:
            public_suffix = psl.get_public_suffix(self.name)
            is_public_suffix = psl.is_public_suffix(self.name)
        except (Timeout, NoNameservers):
            public_suffix = self.name.rpartition('.')[2]
            is_public_suffix = ('.' not in self.name)  # TLDs are public suffixes
        except psl_dns.exceptions.UnsupportedRule as e:
            # It would probably be fine to treat this as a non-public suffix (with the TLD acting as the
            # public suffix and setting both public_suffix and is_public_suffix accordingly).
            # However, in order to allow to investigate the situation, it's better not catch
            # this exception. For web requests, our error handler turns it into a 503 error
            # and makes sure admins are notified.
            raise e

        if is_public_suffix:
            return public_suffix

        # Take into account that any of the parent domains could be a local public suffix. To that
        # end, identify the longest local public suffix that is actually a suffix of domain_name.
        for local_public_suffix in settings.LOCAL_PUBLIC_SUFFIXES:
            has_local_public_suffix_parent = ('.' + self.name).endswith('.' + local_public_suffix)
            if has_local_public_suffix_parent and len(local_public_suffix) > len(public_suffix):
                public_suffix = local_public_suffix

        return public_suffix

    def is_covered_by_foreign_zone(self):
        # Generate a list of all domains connecting this one and its public suffix.
        # If another user owns a zone with one of these names, then the requested
        # domain is unavailable because it is part of the other user's zone.
        private_components = self.name.rsplit(self.public_suffix, 1)[0].rstrip('.')
        private_components = private_components.split('.') if private_components else []
        private_domains = ['.'.join(private_components[i:]) for i in range(0, len(private_components))]
        private_domains = [f'{private_domain}.{self.public_suffix}' for private_domain in private_domains]
        assert self.name == next(iter(private_domains), self.public_suffix)

        # Determine whether domain is covered by other users' zones
        return Domain.objects.filter(Q(name__in=private_domains) & ~Q(owner=self._owner_or_none)).exists()

    def covers_foreign_zone(self):
        # Note: This is not completely accurate: Ideally, we should only consider zones with identical public suffix.
        # (If a public suffix lies in between, it's ok.) However, as there could be many descendant zones, the accurate
        # check is expensive, so currently not implemented (PSL lookups for each of them).
        return Domain.objects.filter(Q(name__endswith=f'.{self.name}') & ~Q(owner=self._owner_or_none)).exists()

    def is_registrable(self):
        """
        Returns False if the domain name is reserved, a public suffix, or covered by / covers another user's domain.
        Otherwise, True is returned.
        """
        self.clean()  # ensure .name is a domain name
        private_generation = self.name.count('.') - self.public_suffix.count('.')
        assert private_generation >= 0

        # .internal is reserved
        if f'.{self.name}'.endswith('.internal'):
            return False

        # Public suffixes can only be registered if they are local
        if private_generation == 0 and self.name not in settings.LOCAL_PUBLIC_SUFFIXES:
            return False

        # Disallow _acme-challenge.dedyn.io and the like. Rejects reserved direct children of public suffixes.
        reserved_prefixes = ('_', 'autoconfig.', 'autodiscover.',)
        if private_generation == 1 and any(self.name.startswith(prefix) for prefix in reserved_prefixes):
            return False

        # Domains covered by another user's zone can't be registered
        if self.is_covered_by_foreign_zone():
            return False

        # Domains that would cover another user's zone can't be registered
        if self.covers_foreign_zone():
            return False

        return True

    @property
    def keys(self):
        if not self._keys:
            self._keys = pdns.get_keys(self)
        return self._keys

    @property
    def touched(self):
        try:
            rrset_touched = max(updated for updated in self.rrset_set.values_list('touched', flat=True))
            # If the domain has not been published yet, self.published is None and max() would fail
            return rrset_touched if not self.published else max(rrset_touched, self.published)
        except ValueError:
            # This can be none if the domain was never published and has no records (but there should be at least NS)
            return self.published

    @property
    def is_locally_registrable(self):
        return self.parent_domain_name in settings.LOCAL_PUBLIC_SUFFIXES

    @property
    def _owner_or_none(self):
        try:
            return self.owner
        except Domain.owner.RelatedObjectDoesNotExist:
            return None

    @property
    def parent_domain_name(self):
        return self._partitioned_name[1]

    @property
    def _partitioned_name(self):
        subname, _, parent_name = self.name.partition('.')
        return subname, parent_name or None

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False)
        super().save(*args, **kwargs)

    def update_delegation(self, child_domain: Domain):
        child_subname, child_domain_name = child_domain._partitioned_name
        if self.name != child_domain_name:
            raise ValueError('Cannot update delegation of %s as it is not an immediate child domain of %s.' %
                             (child_domain.name, self.name))

        # Always remove delegation so that we con properly recreate it
        for rrset in self.rrset_set.filter(subname=child_subname, type__in=['NS', 'DS']):
            rrset.delete()

        if child_domain.pk:
            # Domain real: (re-)set delegation
            child_keys = child_domain.keys
            if not child_keys:
                raise APIException('Cannot delegate %s, as it currently has no keys.' % child_domain.name)

            RRset.objects.create(domain=self, subname=child_subname, type='NS', ttl=3600, contents=settings.DEFAULT_NS)
            RRset.objects.create(domain=self, subname=child_subname, type='DS', ttl=300,
                                 contents=[ds for k in child_keys for ds in k['ds']])
            metrics.get('desecapi_autodelegation_created').inc()
        else:
            # Domain not real: that's it
            metrics.get('desecapi_autodelegation_deleted').inc()

    def delete(self):
        ret = super().delete()
        logger.warning(f'Domain {self.name} deleted (owner: {self.owner.pk})')
        return ret

    def __str__(self):
        return self.name

    class Meta:
        ordering = ('created',)


class Token(ExportModelOperationsMixin('Token'), rest_framework.authtoken.models.Token):
    @staticmethod
    def _allowed_subnets_default():
        return [ipaddress.IPv4Network('0.0.0.0/0'), ipaddress.IPv6Network('::/0')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField("Key", max_length=128, db_index=True, unique=True)
    user = models.ForeignKey(
        User, related_name='auth_tokens',
        on_delete=models.CASCADE, verbose_name="User"
    )
    name = models.CharField('Name', blank=True, max_length=64)
    last_used = models.DateTimeField(null=True, blank=True)
    perm_manage_tokens = models.BooleanField(default=False)
    allowed_subnets = ArrayField(CidrAddressField(), default=_allowed_subnets_default.__func__)
    max_age = models.DurationField(null=True, default=None, validators=[MinValueValidator(timedelta(0))])
    max_unused_period = models.DurationField(null=True, default=None, validators=[MinValueValidator(timedelta(0))])

    plain = None
    objects = NetManager()

    @property
    def is_valid(self):
        now = timezone.now()

        # Check max age
        try:
            if self.created + self.max_age < now:
                return False
        except TypeError:
            pass

        # Check regular usage requirement
        try:
            if (self.last_used or self.created) + self.max_unused_period < now:
                return False
        except TypeError:
            pass

        return True

    def generate_key(self):
        self.plain = secrets.token_urlsafe(21)
        self.key = Token.make_hash(self.plain)
        return self.key

    @staticmethod
    def make_hash(plain):
        return make_password(plain, salt='static', hasher='pbkdf2_sha256_iter1')


class Donation(ExportModelOperationsMixin('Donation'), models.Model):
    @staticmethod
    def _created_default():
        return timezone.now()

    @staticmethod
    def _due_default():
        return timezone.now() + timedelta(days=7)

    @staticmethod
    def _mref_default():
        return "ONDON" + str(time.time())

    created = models.DateTimeField(default=_created_default.__func__)
    name = models.CharField(max_length=255)
    iban = models.CharField(max_length=34)
    bic = models.CharField(max_length=11, blank=True)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    message = models.CharField(max_length=255, blank=True)
    due = models.DateTimeField(default=_due_default.__func__)
    mref = models.CharField(max_length=32, default=_mref_default.__func__)
    email = models.EmailField(max_length=255, blank=True)

    class Meta:
        managed = False


# RR set types: the good, the bad, and the ugly
# known, but unsupported types
RR_SET_TYPES_UNSUPPORTED = {
    'ALIAS',  # Requires signing at the frontend, hence unsupported in desec-stack
    'DNAME',  # "do not combine with DNSSEC", https://doc.powerdns.com/authoritative/settings.html#dname-processing
    'IPSECKEY',  # broken in pdns, https://github.com/PowerDNS/pdns/issues/9055 TODO enable with pdns auth 4.5.0
    'KEY',  # Application use restricted by RFC 3445, DNSSEC use replaced by DNSKEY and handled automatically
    'WKS',  # General usage not recommended, "SHOULD NOT" be used in SMTP (RFC 1123)
}
# restricted types are managed in use by the API, and cannot directly be modified by the API client
RR_SET_TYPES_AUTOMATIC = {
    # corresponding functionality is automatically managed:
    'KEY', 'NSEC', 'NSEC3', 'OPT', 'RRSIG',
    # automatically managed by the API:
    'NSEC3PARAM', 'SOA'
}
# backend types are types that are the types supported by the backend(s)
RR_SET_TYPES_BACKEND = pdns.SUPPORTED_RRSET_TYPES
# validation types are types supported by the validation backend, currently: dnspython
RR_SET_TYPES_VALIDATION = set(ANY.__all__) | set(IN.__all__) \
                          | {'HTTPS', 'SVCB'}  # https://github.com/rthalley/dnspython/pull/624
# manageable types are directly managed by the API client
RR_SET_TYPES_MANAGEABLE = \
        (RR_SET_TYPES_BACKEND & RR_SET_TYPES_VALIDATION) - RR_SET_TYPES_UNSUPPORTED - RR_SET_TYPES_AUTOMATIC


class RRsetManager(Manager):
    def create(self, contents=None, **kwargs):
        rrset = super().create(**kwargs)
        for content in contents or []:
            RR.objects.create(rrset=rrset, content=content)
        return rrset


class RRset(ExportModelOperationsMixin('RRset'), models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True)
    touched = models.DateTimeField(auto_now=True, db_index=True)
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE)
    subname = models.CharField(
        max_length=178,
        blank=True,
        validators=[
            validate_lower,
            RegexValidator(
                regex=r'^([*]|(([*][.])?([a-z0-9_-]{1,63}[.])*[a-z0-9_-]{1,63}))$',
                message='Subname can only use (lowercase) a-z, 0-9, ., -, and _, '
                        'may start with a \'*.\', or just be \'*\'. Components may not exceed 63 characters.',
                code='invalid_subname'
            )
        ]
    )
    type = models.CharField(
        max_length=10,
        validators=[
            validate_upper,
            RegexValidator(
                regex=r'^[A-Z][A-Z0-9]*$',
                message='Type must be uppercase alphanumeric and start with a letter.',
                code='invalid_type'
            )
        ]
    )
    ttl = models.PositiveIntegerField()

    objects = RRsetManager()

    class Meta:
        constraints = [
            ExclusionConstraint(
                name='cname_exclusivity',
                expressions=[
                    ('domain', RangeOperators.EQUAL),
                    ('subname', RangeOperators.EQUAL),
                    (RawSQL("int4(type = 'CNAME')", ()), RangeOperators.NOT_EQUAL),
                ],
            ),
        ]
        unique_together = (("domain", "subname", "type"),)

    @staticmethod
    def construct_name(subname, domain_name):
        return '.'.join(filter(None, [subname, domain_name])) + '.'

    @property
    def name(self):
        return self.construct_name(self.subname, self.domain.name)

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False)
        super().save(*args, **kwargs)

    def clean_records(self, records_presentation_format):
        """
        Validates the records belonging to this set. Validation rules follow the DNS specification; some types may
        incur additional validation rules.

        Raises ValidationError if violation of DNS specification is found.

        Returns a set of records in canonical presentation format.

        :param records_presentation_format: iterable of records in presentation format
        """
        errors = []

        if self.type == 'CNAME':
            if self.subname == '':
                errors.append('CNAME RRset cannot have empty subname.')
            if len(records_presentation_format) > 1:
                errors.append('CNAME RRset cannot have multiple records.')

        def _error_msg(record, detail):
            return f'Record content of {self.type} {self.name} invalid: \'{record}\': {detail}'

        records_canonical_format = set()
        for r in records_presentation_format:
            try:
                r_canonical_format = RR.canonical_presentation_format(r, self.type)
            except ValueError as ex:
                errors.append(_error_msg(r, str(ex)))
            else:
                if r_canonical_format in records_canonical_format:
                    errors.append(_error_msg(r, f'Duplicate record content: this is identical to '
                                                f'\'{r_canonical_format}\''))
                else:
                    records_canonical_format.add(r_canonical_format)

        if any(errors):
            raise ValidationError(errors)

        return records_canonical_format

    def save_records(self, records):
        """
        Updates this RR set's resource records, discarding any old values.

        Records are expected in presentation format and are converted to canonical
        presentation format (e.g., 127.00.0.1 will be converted to 127.0.0.1).
        Raises if a invalid set of records is provided.

        This method triggers the following database queries:
        - one DELETE query
        - one SELECT query for comparison of old with new records
        - one INSERT query, if one or more records were added

        Changes are saved to the database immediately.

        :param records: list of records in presentation format
        """
        new_records = self.clean_records(records)

        # Delete RRs that are not in the new record list from the DB
        self.records.exclude(content__in=new_records).delete()  # one DELETE

        # Retrieve all remaining RRs from the DB
        unchanged_records = set(r.content for r in self.records.all())  # one SELECT

        # Save missing RRs from the new record list to the DB
        added_records = new_records - unchanged_records
        rrs = [RR(rrset=self, content=content) for content in added_records]
        RR.objects.bulk_create(rrs)  # One INSERT

    def __str__(self):
        return '<RRSet %s domain=%s type=%s subname=%s>' % (self.pk, self.domain.name, self.type, self.subname)


class RRManager(Manager):
    def bulk_create(self, rrs, **kwargs):
        ret = super().bulk_create(rrs, **kwargs)

        # For each rrset, save once to set RRset.updated timestamp and trigger signal for post-save processing
        rrsets = {rr.rrset for rr in rrs}
        for rrset in rrsets:
            rrset.save()

        return ret


class RR(ExportModelOperationsMixin('RR'), models.Model):
    created = models.DateTimeField(auto_now_add=True)
    rrset = models.ForeignKey(RRset, on_delete=models.CASCADE, related_name='records')
    content = models.TextField()

    objects = RRManager()

    _type_map = {
        dns.rdatatype.CDS: CDS,  # TODO remove when https://github.com/rthalley/dnspython/pull/625 is in main codebase
        dns.rdatatype.DLV: DLV,  # TODO remove when https://github.com/rthalley/dnspython/pull/625 is in main codebase
        dns.rdatatype.DS: DS,  # TODO remove when https://github.com/rthalley/dnspython/pull/625 is in main codebase
        dns.rdatatype.TXT: LongQuotedTXT,  # we slightly deviate from RFC 1035 and allow tokens longer than 255 bytes
        dns.rdatatype.SPF: LongQuotedTXT,  # we slightly deviate from RFC 1035 and allow tokens longer than 255 bytes
    }

    @staticmethod
    def canonical_presentation_format(any_presentation_format, type_):
        """
        Converts any valid presentation format for a RR into it's canonical presentation format.
        Raises if provided presentation format is invalid.
        """
        rdtype = rdatatype.from_text(type_)

        try:
            # Convert to wire format, ensuring input validation.
            cls = RR._type_map.get(rdtype, dns.rdata)
            wire = cls.from_text(
                rdclass=rdataclass.IN,
                rdtype=rdtype,
                tok=dns.tokenizer.Tokenizer(any_presentation_format),
                relativize=False
            ).to_digestable()

            if len(wire) > 64000:
                raise ValidationError(f'Ensure this value has no more than 64000 byte in wire format (it has {len(wire)}).')

            parser = dns.wire.Parser(wire, current=0)
            with parser.restrict_to(len(wire)):
                rdata = cls.from_wire_parser(rdclass=rdataclass.IN, rdtype=rdtype, parser=parser)

            # Convert to canonical presentation format, disable chunking of records.
            # Exempt types which have chunksize hardcoded (prevents "got multiple values for keyword argument 'chunksize'").
            chunksize_exception_types = (dns.rdatatype.OPENPGPKEY, dns.rdatatype.EUI48, dns.rdatatype.EUI64)
            if rdtype in chunksize_exception_types:
                return rdata.to_text()
            else:
                return rdata.to_text(chunksize=0)
        except binascii.Error:
            # e.g., odd-length string
            raise ValueError('Cannot parse hexadecimal or base64 record contents')
        except dns.exception.SyntaxError as e:
            # e.g., A/127.0.0.999
            if 'quote' in e.args[0]:
                raise ValueError(f'Data for {type_} records must be given using quotation marks.')
            else:
                raise ValueError(f'Record content for type {type_} malformed: {",".join(e.args)}')
        except dns.name.NeedAbsoluteNameOrOrigin:
            raise ValueError('Hostname must be fully qualified (i.e., end in a dot: "example.com.")')
        except ValueError as ex:
            # e.g., string ("asdf") cannot be parsed into int on base 10
            raise ValueError(f'Cannot parse record contents: {ex}')
        except Exception as e:
            # TODO see what exceptions raise here for faulty input
            raise e

    def __str__(self):
        return '<RR %s %s rr_set=%s>' % (self.pk, self.content, self.rrset.pk)


class AuthenticatedAction(models.Model):
    """
    Represents a procedure call on a defined set of arguments.

    Subclasses can define additional arguments by adding Django model fields and must define the action to be taken by
    implementing the `_act` method.

    AuthenticatedAction provides the `state` property which by default is a hash of the action type (defined by the
    action's class path). Other information such as user state can be included in the state hash by (carefully)
    overriding the `_state_fields` property. Instantiation of the model, if given a `state` kwarg, will raise an error
    if the given state argument does not match the state computed from `_state_fields` at the moment of instantiation.
    The same applies to the `act` method: If called on an object that was instantiated without a `state` kwargs, an
    error will be raised.

    This effectively allows hash-authenticated procedure calls by third parties as long as the server-side state is
    unaltered, according to the following protocol:

    (1) Instantiate the AuthenticatedAction subclass representing the action to be taken (no `state` kwarg here),
    (2) provide information on how to instantiate the instance, and the state hash, to a third party,
    (3) when provided with data that allows instantiation and a valid state hash, take the defined action, possibly with
        additional parameters chosen by the third party that do not belong to the verified state.
    """
    _validated = False

    class Meta:
        managed = False

    def __init__(self, *args, **kwargs):
        state = kwargs.pop('state', None)
        super().__init__(*args, **kwargs)

        if state is not None:
            self._validated = self.validate_state(state)
            if not self._validated:
                raise ValueError

    @property
    def _state_fields(self):
        """
        Returns a list that defines the state of this action (used for authentication of this action).

        Return value must be JSON-serializable.

        Values not included in the return value will not be used for authentication, i.e. those values can be varied
        freely and function as unauthenticated action input parameters.

        Use caution when overriding this method. You will usually want to append a value to the list returned by the
        parent. Overriding the behavior altogether could result in reducing the state to fewer variables, resulting
        in valid signatures when they were intended to be invalid. The suggested method for overriding is

            @property
            def _state_fields:
                return super()._state_fields + [self.important_value, self.another_added_value]

        :return: List of values to be signed.
        """
        name = '.'.join([self.__module__, self.__class__.__qualname__])
        return [name]

    @property
    def state(self):
        state = json.dumps(self._state_fields).encode()
        hash = sha256()
        hash.update(state)
        return hash.hexdigest()

    def validate_state(self, value):
        return value == self.state

    def _act(self):
        """
        Conduct the action represented by this class.
        :return: None
        """
        raise NotImplementedError

    def act(self):
        if not self._validated:
            raise RuntimeError('Action state could not be verified.')
        return self._act()


class AuthenticatedBasicUserAction(AuthenticatedAction):
    """
    Abstract AuthenticatedAction involving a user instance.
    """
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)

    class Meta:
        managed = False

    @property
    def _state_fields(self):
        return super()._state_fields + [str(self.user.id)]


class AuthenticatedUserAction(AuthenticatedBasicUserAction):
    """
    Abstract AuthenticatedBasicUserAction, incorporating the user's id, email, password, and is_active flag into the
    Message Authentication Code state.
    """

    class Meta:
        managed = False

    @property
    def _state_fields(self):
        # TODO consider adding a "last change" attribute of the user to the state to avoid code
        #  re-use after the the state has been changed and changed back.
        return super()._state_fields + [self.user.email, self.user.password, self.user.is_active]


class AuthenticatedActivateUserAction(AuthenticatedUserAction):
    domain = models.CharField(max_length=191)

    class Meta:
        managed = False

    @property
    def _state_fields(self):
        return super()._state_fields + [self.domain]

    def _act(self):
        self.user.activate()


class AuthenticatedChangeEmailUserAction(AuthenticatedUserAction):
    new_email = models.EmailField()

    class Meta:
        managed = False

    @property
    def _state_fields(self):
        return super()._state_fields + [self.new_email]

    def _act(self):
        self.user.change_email(self.new_email)


class AuthenticatedResetPasswordUserAction(AuthenticatedUserAction):
    new_password = models.CharField(max_length=128)

    class Meta:
        managed = False

    def _act(self):
        self.user.change_password(self.new_password)


class AuthenticatedDeleteUserAction(AuthenticatedUserAction):

    class Meta:
        managed = False

    def _act(self):
        self.user.delete()


class AuthenticatedDomainBasicUserAction(AuthenticatedBasicUserAction):
    """
    Abstract AuthenticatedUserAction involving an domain instance, incorporating the domain's id, name as well as the
    owner ID into the Message Authentication Code state.
    """
    domain = models.ForeignKey(Domain, on_delete=models.DO_NOTHING)

    class Meta:
        managed = False

    @property
    def _state_fields(self):
        return super()._state_fields + [
            str(self.domain.id),  # ensures the domain object is identical
            self.domain.name,  # exclude renamed domains
            str(self.domain.owner.id),  # exclude transferred domains
        ]


class AuthenticatedRenewDomainBasicUserAction(AuthenticatedDomainBasicUserAction):

    class Meta:
        managed = False

    @property
    def _state_fields(self):
        return super()._state_fields + [str(self.domain.renewal_changed)]

    def _act(self):
        self.domain.renewal_state = Domain.RenewalState.FRESH
        self.domain.renewal_changed = timezone.now()
        self.domain.save(update_fields=['renewal_state', 'renewal_changed'])


def captcha_default_content(kind: str) -> str:
    if kind == Captcha.Kind.IMAGE:
        alphabet = (string.ascii_uppercase + string.digits).translate({ord(c): None for c in 'IO0'})
        length = 5
    elif kind == Captcha.Kind.AUDIO:
        alphabet = string.digits
        length = 8
    else:
        raise ValueError(f'Unknown Captcha kind: {kind}')

    content = ''.join([secrets.choice(alphabet) for _ in range(length)])
    metrics.get('desecapi_captcha_content_created').labels(kind).inc()
    return content


class Captcha(ExportModelOperationsMixin('Captcha'), models.Model):

    class Kind(models.TextChoices):
        IMAGE = 'image'
        AUDIO = 'audio'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True)
    content = models.CharField(max_length=24, default="")
    kind = models.CharField(choices=Kind.choices, default=Kind.IMAGE, max_length=24)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.content:
            self.content = captcha_default_content(self.kind)

    def verify(self, solution: str):
        age = timezone.now() - self.created
        self.delete()
        return (
            str(solution).upper().strip() == self.content  # solution correct
            and
            age <= settings.CAPTCHA_VALIDITY_PERIOD  # not expired
        )


class Identity(models.Model):
    rr_type = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=24, default="")
    created = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='identities')
    default_ttl = models.PositiveIntegerField(default=300)

    class Meta:
        abstract = True

    def get_record_contents(self) -> List[str]:
        raise NotImplementedError

    def save_rrs(self):
        raise NotImplementedError

    def save(self, *args, **kwargs):
        self.save_rrs()
        return super().save(*args, **kwargs)

    def delete_rrs(self):
        raise NotImplementedError

    def delete(self, using=None, keep_parents=False):
        # TODO this will delete also RRs that may be covered by other identities
        self.delete_rrs()
        return super().delete(using, keep_parents)

    def get_or_create_rr_set(self, domain: Domain, subname: str) -> RRset:
        try:
            return RRset.objects.get(domain=domain, subname=subname, type=self.rr_type)
        except RRset.DoesNotExist:
            # TODO save this RRset?
            return RRset(domain=domain, subname=subname, type=self.rr_type, ttl=self.default_ttl)

    @staticmethod
    def get_or_create_rr(rrset: RRset, content: str) -> RR:
        try:
            return RR.objects.get(rrset=rrset, content=content)
        except RR.DoesNotExist:
            return RR(rrset=rrset, content=content)


class TLSIdentity(Identity):
    rr_type = 'TLSA'

    class CertificateUsage(models.IntegerChoices):
        CA_CONSTRAINT = 0
        SERVICE_CERTIFICATE_CONSTRAINT = 1
        TRUST_ANCHOR_ASSERTION = 2
        DOMAIN_ISSUED_CERTIFICATE = 3

    class Selector(models.IntegerChoices):
        FULL_CERTIFICATE = 0
        SUBJECT_PUBLIC_KEY_INFO = 1

    class MatchingType(models.IntegerChoices):
        NO_HASH_USED = 0
        SHA256 = 1
        SHA512 = 2

    class Protocol(models.TextChoices):
        TCP = 'tcp'
        UDP = 'udp'
        SCTP = 'sctp'

    certificate = models.TextField()

    tlsa_selector = models.IntegerField(choices=Selector.choices, default=Selector.SUBJECT_PUBLIC_KEY_INFO)
    tlsa_matching_type = models.IntegerField(choices=MatchingType.choices, default=MatchingType.SHA256)
    tlsa_certificate_usage = models.IntegerField(choices=CertificateUsage.choices,
                                                 default=CertificateUsage.DOMAIN_ISSUED_CERTIFICATE)

    port = models.IntegerField(default=443)
    protocol = models.TextField(choices=Protocol.choices, default=Protocol.TCP)

    scheduled_removal = models.DateTimeField(null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'not_valid_after' not in kwargs:
            self.scheduled_removal = self.not_valid_after

    def get_record_contents(self) -> List[str]:
        # choose hash function
        if self.tlsa_matching_type == self.MatchingType.SHA256:
            hash_function = hazmat.primitives.hashes.SHA256()
        elif self.tlsa_matching_type == self.MatchingType.SHA512:
            hash_function = hazmat.primitives.hashes.SHA512()
        else:
            raise NotImplementedError

        # choose data to hash
        if self.tlsa_selector == self.Selector.SUBJECT_PUBLIC_KEY_INFO:
            to_be_hashed = self._cert.public_key().public_bytes(
                hazmat.primitives.serialization.Encoding.DER,
                hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo
            )
        else:
            raise NotImplementedError

        # compute the hash
        h = hazmat.primitives.hashes.Hash(hash_function)
        h.update(to_be_hashed)
        hash = h.finalize().hex()

        # create TLSA record content
        return [f"{self.tlsa_certificate_usage} {self.tlsa_selector} {self.tlsa_matching_type} {hash}"]

    @property
    def _cert(self) -> x509.Certificate:
        return x509.load_pem_x509_certificate(self.certificate.encode())

    @property
    def fingerprint(self) -> str:
        return self._cert.fingerprint(hazmat.primitives.hashes.SHA256()).hex()

    @property
    def subject_names(self) -> Set[str]:
        subject_names = {
            x.value for x in
            self._cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        }

        try:
            subject_alternative_names = {
                x for x in
                self._cert.extensions.get_extension_for_oid(
                    x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value.get_values_for_type(x509.DNSName)
            }
        except x509.extensions.ExtensionNotFound:
            subject_alternative_names = set()

        return subject_names | subject_alternative_names

    @staticmethod
    def get_closest_ancestor(domain_name, owner: User) -> Optional[Domain]:
        # TODO move to Domain?
        labels = domain_name.split('.')
        ancestor_names = ['.'.join(labels[i:]) for i in range(len(labels))]
        for ancestor_name in ancestor_names:  # TODO do this with one query
            try:
                return Domain.objects.get(name=ancestor_name, owner=owner)
            except Domain.DoesNotExist:
                continue
        return None

    def domains_subnames(self) -> Set[Tuple[Domain, str]]:
        domains_subnames = set()
        for name in self.subject_names:
            # cut off any wildcard prefix
            name = name.lstrip('*').lstrip('.')

            # filter names for valid domain names
            try:
                validate_domain_name[1](name)
            except ValidationError:
                continue

            # find user-owned parent domain
            domain = self.get_closest_ancestor(name, self.owner)
            if not domain:
                continue
            subname = name[:-len(domain.name)].rstrip('.')

            # return subname, domain pair
            domains_subnames.add((domain, f"_{self.port:n}._{self.protocol}.{subname}".rstrip('.')))
        return domains_subnames

    def get_rrsets(self) -> List[RRset]:
        rrsets = []
        for domain, subname in self.domains_subnames():
            rrsets.append(self.get_or_create_rr_set(domain, subname))
        return rrsets

    def get_rrs(self) -> List[RR]:
        rrs = []
        for domain, subname in self.domains_subnames():
            rrset = self.get_or_create_rr_set(domain, subname)
            for content in self.get_record_contents():
                rrs.append(self.get_or_create_rr(rrset=rrset, content=content))
        return rrs

    def save_rrs(self):
        for rr in self.get_rrs():
            rr.rrset.save()
            rr.save()

    def delete_rrs(self):
        for domain, subname in self.domains_subnames():
            rrset = self.get_or_create_rr_set(domain, subname)
            rrset.records.filter(content__in=self.get_record_contents()).delete()
            if not len(rrset.records.all()):
                rrset.delete()

    @property
    def not_valid_before(self):
        return self._cert.not_valid_before

    @property
    def not_valid_after(self):
        return self._cert.not_valid_after
