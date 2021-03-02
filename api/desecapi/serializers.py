import binascii
import copy
import json
import re
from base64 import b64encode

import django.core.exceptions
from captcha.audio import AudioCaptcha
from captcha.image import ImageCaptcha
from django.contrib.auth.password_validation import validate_password
from django.core.validators import MinValueValidator
from django.db.models import Model, Q
from django.utils import timezone
from netfields import rest_framework as netfields_rf
from rest_framework import fields, serializers
from rest_framework.settings import api_settings
from rest_framework.validators import UniqueTogetherValidator, UniqueValidator, qs_filter

from api import settings
from desecapi import crypto, metrics, models, validators


class CaptchaSerializer(serializers.ModelSerializer):
    challenge = serializers.SerializerMethodField()

    class Meta:
        model = models.Captcha
        fields = ('id', 'challenge', 'kind') if not settings.DEBUG else ('id', 'challenge', 'kind', 'content')

    def get_challenge(self, obj: models.Captcha):
        # TODO Does this need to be stored in the object instance, in case this method gets called twice?
        if obj.kind == models.Captcha.Kind.IMAGE:
            challenge = ImageCaptcha().generate(obj.content).getvalue()
        elif obj.kind == models.Captcha.Kind.AUDIO:
            challenge = AudioCaptcha().generate(obj.content)
        else:
            raise ValueError(f'Unknown captcha type {obj.kind}')
        return b64encode(challenge)


class CaptchaSolutionSerializer(serializers.Serializer):
    id = serializers.PrimaryKeyRelatedField(
        queryset=models.Captcha.objects.all(),
        error_messages={'does_not_exist': 'CAPTCHA does not exist.'}
    )
    solution = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        captcha = attrs['id']  # Note that this already is the Captcha object
        if not captcha.verify(attrs['solution']):
            raise serializers.ValidationError('CAPTCHA could not be validated. Please obtain a new one and try again.')

        return attrs


class TokenSerializer(serializers.ModelSerializer):
    allowed_subnets = serializers.ListField(child=netfields_rf.CidrAddressField(), required=False)
    token = serializers.ReadOnlyField(source='plain')
    is_valid = serializers.ReadOnlyField()

    class Meta:
        model = models.Token
        fields = ('id', 'created', 'last_used', 'max_age', 'max_unused_period', 'name', 'perm_manage_tokens',
                  'allowed_subnets', 'is_valid', 'token',)
        read_only_fields = ('id', 'created', 'last_used', 'token')

    def __init__(self, *args, include_plain=False, **kwargs):
        self.include_plain = include_plain
        return super().__init__(*args, **kwargs)

    def get_fields(self):
        fields = super().get_fields()
        if not self.include_plain:
            fields.pop('token')
        return fields


class TokenDomainPolicySerializer(serializers.ModelSerializer):

    class Meta:
        model = models.TokenDomainPolicy
        fields = ('domain', 'perm_dyndns', 'perm_other',)
        read_only_fields = ('domain',)


class RequiredOnPartialUpdateCharField(serializers.CharField):
    """
    This field is always required, even for partial updates (e.g. using PATCH).
    """
    def validate_empty_values(self, data):
        if data is serializers.empty:
            self.fail('required')

        return super().validate_empty_values(data)


class Validator:

    message = 'This field did not pass validation.'

    def __init__(self, message=None):
        self.field_name = None
        self.message = message or self.message
        self.instance = None

    def __call__(self, value):
        raise NotImplementedError

    def __repr__(self):
        return '<%s>' % self.__class__.__name__


class ReadOnlyOnUpdateValidator(Validator):

    message = 'Can only be written on create.'
    requires_context = True

    def __call__(self, value, serializer_field):
        field_name = serializer_field.source_attrs[-1]
        instance = getattr(serializer_field.parent, 'instance', None)
        if isinstance(instance, Model) and value != getattr(instance, field_name):
            raise serializers.ValidationError(self.message, code='read-only-on-update')


class ConditionalExistenceModelSerializer(serializers.ModelSerializer):
    """
    Only considers data with certain condition as existing data.
    If the existence condition does not hold, given instances are deleted, and no new instances are created,
    respectively. Also, to_representation and data will return None.
    Contrary, if the existence condition holds, the behavior is the same as DRF's ModelSerializer.
    """

    def exists(self, arg):
        """
        Determine if arg is to be considered existing.
        :param arg: Either a model instance or (possibly invalid!) data object.
        :return: Whether we treat this as non-existing instance.
        """
        raise NotImplementedError

    def to_representation(self, instance):
        return None if not self.exists(instance) else super().to_representation(instance)

    @property
    def data(self):
        try:
            return super().data
        except TypeError:
            return None

    def save(self, **kwargs):
        validated_data = {}
        validated_data.update(self.validated_data)
        validated_data.update(kwargs)

        known_instance = self.instance is not None
        data_exists = self.exists(validated_data)

        if known_instance and data_exists:
            self.instance = self.update(self.instance, validated_data)
        elif known_instance and not data_exists:
            self.delete()
        elif not known_instance and data_exists:
            self.instance = self.create(validated_data)
        elif not known_instance and not data_exists:
            pass  # nothing to do

        return self.instance

    def delete(self):
        self.instance.delete()


class NonBulkOnlyDefault:
    """
    This class may be used to provide default values that are only used
    for non-bulk operations, but that do not return any value for bulk
    operations.
    Implementation inspired by CreateOnlyDefault.
    """
    requires_context = True

    def __init__(self, default):
        self.default = default

    def __call__(self, serializer_field):
        is_many = getattr(serializer_field.root, 'many', False)
        if is_many:
            raise serializers.SkipField()
        if callable(self.default):
            if getattr(self.default, 'requires_context', False):
                return self.default(serializer_field)
            else:
                return self.default()
        return self.default

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, repr(self.default))


class RRSerializer(serializers.ModelSerializer):

    class Meta:
        model = models.RR
        fields = ('content',)

    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError('Must be a string.', code='must-be-a-string')
        return super().to_internal_value({'content': data})

    def to_representation(self, instance):
        return instance.content


class RRsetListSerializer(serializers.ListSerializer):
    default_error_messages = {
        **serializers.Serializer.default_error_messages,
        **serializers.ListSerializer.default_error_messages,
        **{'not_a_list': 'Expected a list of items but got {input_type}.'},
    }

    @staticmethod
    def _key(data_item):
        return data_item.get('subname'), data_item.get('type')

    @staticmethod
    def _types_by_position_string(conflicting_indices_by_type):
        types_by_position = {}
        for type_, conflict_positions in conflicting_indices_by_type.items():
            for position in conflict_positions:
                types_by_position.setdefault(position, []).append(type_)
        # Sort by position, None at the end
        types_by_position = dict(sorted(types_by_position.items(), key=lambda x: (x[0] is None, x)))
        db_conflicts = types_by_position.pop(None, None)
        if db_conflicts: types_by_position['database'] = db_conflicts
        for position, types in types_by_position.items():
            types_by_position[position] = ', '.join(sorted(types))
        types_by_position = [f'{position} ({types})' for position, types in types_by_position.items()]
        return ', '.join(types_by_position)

    def to_internal_value(self, data):
        if not isinstance(data, list):
            message = self.error_messages['not_a_list'].format(input_type=type(data).__name__)
            raise serializers.ValidationError({api_settings.NON_FIELD_ERRORS_KEY: [message]}, code='not_a_list')

        if not self.allow_empty and len(data) == 0:
            if self.parent and self.partial:
                raise serializers.SkipField()
            else:
                self.fail('empty')

        ret = []
        errors = []
        partial = self.partial

        # build look-up objects for instances and data, so we can look them up with their keys
        try:
            known_instances = {(x.subname, x.type): x for x in self.instance}
        except TypeError:  # in case self.instance is None (as during POST)
            known_instances = {}
        indices = {}
        for idx, item in enumerate(data):
            # Validate item type before using anything from it
            if not isinstance(item, dict):
                self.fail('invalid', datatype=type(item).__name__)
            s, t = self._key(item)  # subname, type
            # Construct an index of the RRsets in `data` by `s` and `t`. As (subname, type) may be given multiple times
            # (although invalid), we make indices[s][t] a set to properly keep track. We also check and record RRsets
            # which are known in the database (once per subname), using index `None` (for checking CNAME exclusivity).
            if s not in indices:
                types = self.child.domain.rrset_set.filter(subname=s).values_list('type', flat=True)
                indices[s] = {type_: {None} for type_ in types}
            items = indices[s].setdefault(t, set())
            items.add(idx)

        collapsed_indices = copy.deepcopy(indices)
        for idx, item in enumerate(data):
            if item.get('records') == []:
                s, t = self._key(item)
                collapsed_indices[s][t] -= {idx, None}

        # Iterate over all rows in the data given
        for idx, item in enumerate(data):
            try:
                # see if other rows have the same key
                s, t = self._key(item)
                data_indices = indices[s][t] - {None}
                if len(data_indices) > 1:
                    raise serializers.ValidationError({
                        'non_field_errors': [
                            'Same subname and type as in position(s) %s, but must be unique.' %
                            ', '.join(map(str, data_indices - {idx}))
                        ]
                    })

                # see if other rows violate CNAME exclusivity
                if item.get('records') != []:
                    conflicting_indices_by_type = {k: v for k, v in collapsed_indices[s].items()
                                                   if (k == 'CNAME') != (t == 'CNAME')}
                    if any(conflicting_indices_by_type.values()):
                        types_by_position = self._types_by_position_string(conflicting_indices_by_type)
                        raise serializers.ValidationError({
                            'non_field_errors': [
                                f'RRset with conflicting type present: {types_by_position}.'
                                ' (No other RRsets are allowed alongside CNAME.)'
                            ]
                        })

                # determine if this is a partial update (i.e. PATCH):
                # we allow partial update if a partial update method (i.e. PATCH) is used, as indicated by self.partial,
                # and if this is not actually a create request because it is unknown and nonempty
                unknown = self._key(item) not in known_instances.keys()
                nonempty = item.get('records', None) != []
                self.partial = partial and not (unknown and nonempty)
                self.child.instance = known_instances.get(self._key(item), None)

                # with partial value and instance in place, let the validation begin!
                validated = self.child.run_validation(item)
            except serializers.ValidationError as exc:
                errors.append(exc.detail)
            else:
                ret.append(validated)
                errors.append({})

        self.partial = partial

        if any(errors):
            raise serializers.ValidationError(errors)

        return ret

    def update(self, instance, validated_data):
        """
        Creates, updates and deletes RRsets according to the validated_data given. Relevant instances must be passed as
        a queryset in the `instance` argument.

        RRsets that appear in `instance` are considered "known", other RRsets are considered "unknown". RRsets that
        appear in `validated_data` with records == [] are considered empty, otherwise non-empty.

        The update proceeds as follows:
        1. All unknown, non-empty RRsets are created.
        2. All known, non-empty RRsets are updated.
        3. All known, empty RRsets are deleted.
        4. Unknown, empty RRsets will not cause any action.

        Rationale:
        As both "known"/"unknown" and "empty"/"non-empty" are binary partitions on `everything`, the combination of
        both partitions `everything` in four disjoint subsets. Hence, every RRset in `everything` is taken care of.

                   empty   |  non-empty
        ------- | -------- | -----------
        known   |  delete  |   update
        unknown |  no-op   |   create

        :param instance: QuerySet of relevant RRset objects, i.e. the Django.Model subclass instances. Relevant are all
        instances that are referenced in `validated_data`. If a referenced RRset is missing from instances, it will be
        considered unknown and hence be created. This may cause a database integrity error. If an RRset is given, but
        not relevant (i.e. not referred to by `validated_data`), a ValueError will be raised.
        :param validated_data: List of RRset data objects, i.e. dictionaries.
        :return: List of RRset objects (Django.Model subclass) that have been created or updated.
        """
        def is_empty(data_item):
            return data_item.get('records', None) == []

        query = Q(pk__in=[])  # start out with an always empty query, see https://stackoverflow.com/q/35893867/6867099
        for item in validated_data:
            query |= Q(type=item['type'], subname=item['subname'])  # validation has ensured these fields exist
        instance = instance.filter(query)

        instance_index = {(rrset.subname, rrset.type): rrset for rrset in instance}
        data_index = {self._key(data): data for data in validated_data}

        if data_index.keys() | instance_index.keys() != data_index.keys():
            raise ValueError('Given set of known RRsets (`instance`) is not a subset of RRsets referred to in'
                             ' `validated_data`. While this would produce a correct result, this is illegal due to its'
                             ' inefficiency.')

        everything = instance_index.keys() | data_index.keys()
        known = instance_index.keys()
        unknown = everything - known
        # noinspection PyShadowingNames
        empty = {self._key(data) for data in validated_data if is_empty(data)}
        nonempty = everything - empty

        # noinspection PyUnusedLocal
        noop = unknown & empty
        created = unknown & nonempty
        updated = known & nonempty
        deleted = known & empty

        ret = []

        # The above algorithm makes sure that created, updated, and deleted are disjoint. Thus, no "override cases"
        # (such as: an RRset should be updated and delete, what should be applied last?) need to be considered.
        # We apply deletion first to get any possible CNAME exclusivity collisions out of the way.
        for subname, type_ in deleted:
            instance_index[(subname, type_)].delete()

        for subname, type_ in created:
            ret.append(self.child.create(
                validated_data=data_index[(subname, type_)]
            ))

        for subname, type_ in updated:
            ret.append(self.child.update(
                instance=instance_index[(subname, type_)],
                validated_data=data_index[(subname, type_)]
            ))

        return ret

    def save(self, **kwargs):
        kwargs.setdefault('domain', self.child.domain)
        return super().save(**kwargs)


class RRsetSerializer(ConditionalExistenceModelSerializer):
    domain = serializers.SlugRelatedField(read_only=True, slug_field='name')
    records = RRSerializer(many=True)
    ttl = serializers.IntegerField(max_value=86400)

    class Meta:
        model = models.RRset
        fields = ('created', 'domain', 'subname', 'name', 'records', 'ttl', 'type', 'touched',)
        extra_kwargs = {
            'subname': {'required': False, 'default': NonBulkOnlyDefault('')}
        }
        list_serializer_class = RRsetListSerializer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.domain = self.context['domain']
        except KeyError:
            raise ValueError('RRsetSerializer() must be given a domain object (to validate uniqueness constraints).')
        self.minimum_ttl = self.context.get('minimum_ttl', self.domain.minimum_ttl)

    def get_fields(self):
        fields = super().get_fields()
        fields['subname'].validators.append(ReadOnlyOnUpdateValidator())
        fields['type'].validators.append(ReadOnlyOnUpdateValidator())
        fields['ttl'].validators.append(MinValueValidator(limit_value=self.minimum_ttl))
        return fields

    def get_validators(self):
        return [
            UniqueTogetherValidator(
                self.domain.rrset_set,
                ('subname', 'type'),
                message='Another RRset with the same subdomain and type exists for this domain.',
            ),
            validators.ExclusionConstraintValidator(
                self.domain.rrset_set,
                ('subname',),
                exclusion_condition=('type', 'CNAME',),
                message='RRset with conflicting type present: database ({types}).'
                        ' (No other RRsets are allowed alongside CNAME.)',
            ),
        ]

    @staticmethod
    def validate_type(value):
        if value not in models.RR_SET_TYPES_MANAGEABLE:
            # user cannot manage this type, let's try to tell her the reason
            if value in models.RR_SET_TYPES_AUTOMATIC:
                raise serializers.ValidationError(f'You cannot tinker with the {value} RR set. It is managed '
                                                  f'automatically.')
            elif value.startswith('TYPE'):
                raise serializers.ValidationError('Generic type format is not supported.')
            else:
                raise serializers.ValidationError(f'The {value} RR set type is currently unsupported.')
        return value

    def validate_records(self, value):
        # `records` is usually allowed to be empty (for idempotent delete), except for POST requests which are intended
        # for RRset creation only. We use the fact that DRF generic views pass the request in the serializer context.
        request = self.context.get('request')
        if request and request.method == 'POST' and not value:
            raise serializers.ValidationError('This field must not be empty when using POST.')
        return value

    def validate(self, attrs):
        if 'records' in attrs:
            try:
                type_ = attrs['type']
            except KeyError:  # on the RRsetDetail endpoint, the type is not in attrs
                type_ = self.instance.type

            try:
                attrs['records'] = [{'content': models.RR.canonical_presentation_format(rr['content'], type_)}
                                    for rr in attrs['records']]
            except ValueError as ex:
                raise serializers.ValidationError(str(ex))

            # There is a 12 byte baseline requirement per record, c.f.
            # https://lists.isc.org/pipermail/bind-users/2008-April/070137.html
            # There also seems to be a 32 byte (?) baseline requirement per RRset, plus the qname length, see
            # https://lists.isc.org/pipermail/bind-users/2008-April/070148.html
            # The binary length of the record depends actually on the type, but it's never longer than vanilla len()
            qname = models.RRset.construct_name(attrs.get('subname', ''), self.domain.name)
            conservative_total_length = 32 + len(qname) + sum(12 + len(rr['content']) for rr in attrs['records'])

            # Add some leeway for RRSIG record (really ~110 bytes) and other data we have not thought of
            conservative_total_length += 256

            excess_length = conservative_total_length - 65535  # max response size
            if excess_length > 0:
                raise serializers.ValidationError(f'Total length of RRset exceeds limit by {excess_length} bytes.',
                                                  code='max_length')

        return attrs

    def exists(self, arg):
        if isinstance(arg, models.RRset):
            return arg.records.exists()
        else:
            return bool(arg.get('records')) if 'records' in arg.keys() else True

    def create(self, validated_data):
        rrs_data = validated_data.pop('records')
        rrset = models.RRset.objects.create(**validated_data)
        self._set_all_record_contents(rrset, rrs_data)
        return rrset

    def update(self, instance: models.RRset, validated_data):
        rrs_data = validated_data.pop('records', None)
        if rrs_data is not None:
            self._set_all_record_contents(instance, rrs_data)

        ttl = validated_data.pop('ttl', None)
        if ttl and instance.ttl != ttl:
            instance.ttl = ttl
            instance.save()  # also updates instance.touched
        else:
            # Update instance.touched without triggering post-save signal (no pdns action required)
            models.RRset.objects.filter(pk=instance.pk).update(touched=timezone.now())

        return instance

    def save(self, **kwargs):
        kwargs.setdefault('domain', self.domain)
        return super().save(**kwargs)

    @staticmethod
    def _set_all_record_contents(rrset: models.RRset, rrs):
        """
        Updates this RR set's resource records, discarding any old values.

        :param rrset: the RRset at which we overwrite all RRs
        :param rrs: list of RR representations
        """
        record_contents = [rr['content'] for rr in rrs]
        try:
            rrset.save_records(record_contents)
        except django.core.exceptions.ValidationError as e:
            raise serializers.ValidationError(e.messages, code='record-content')


class DomainSerializer(serializers.ModelSerializer):
    default_error_messages = {
        **serializers.Serializer.default_error_messages,
        'name_unavailable': 'This domain name conflicts with an existing zone, or is disallowed by policy.',
    }

    class Meta:
        model = models.Domain
        fields = ('created', 'published', 'name', 'keys', 'minimum_ttl', 'touched',)
        read_only_fields = ('published', 'minimum_ttl',)
        extra_kwargs = {
            'name': {'trim_whitespace': False},
        }

    def __init__(self, *args, include_keys=False, **kwargs):
        self.include_keys = include_keys
        return super().__init__(*args, **kwargs)

    def get_fields(self):
        fields = super().get_fields()
        if not self.include_keys:
            fields.pop('keys')
        fields['name'].validators.append(ReadOnlyOnUpdateValidator())
        return fields

    def validate_name(self, value):
        if not models.Domain(name=value, owner=self.context['request'].user).is_registrable():
            raise serializers.ValidationError(self.default_error_messages['name_unavailable'], code='name_unavailable')
        return value

    def create(self, validated_data):
        if 'minimum_ttl' not in validated_data and models.Domain(name=validated_data['name']).is_locally_registrable:
            validated_data.update(minimum_ttl=60)
        return super().create(validated_data)


class DonationSerializer(serializers.ModelSerializer):

    class Meta:
        model = models.Donation
        fields = ('name', 'iban', 'bic', 'amount', 'message', 'email', 'mref', 'interval')
        read_only_fields = ('mref',)


    @staticmethod
    def validate_bic(value):
        return re.sub(r'[\s]', '', value)

    @staticmethod
    def validate_iban(value):
        return re.sub(r'[\s]', '', value)

    def create(self, validated_data):
        return self.Meta.model(**validated_data)


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = models.User
        fields = ('created', 'email', 'id', 'limit_domains', 'password',)
        extra_kwargs = {
            'password': {
                'write_only': True,  # Do not expose password field
                'allow_null': True,
            }
        }

    def validate_password(self, value):
        if value is not None:
            validate_password(value)
        return value

    def create(self, validated_data):
        return models.User.objects.create_user(**validated_data)


class RegisterAccountSerializer(UserSerializer):
    domain = serializers.CharField(required=False, validators=models.validate_domain_name)
    captcha = CaptchaSolutionSerializer(required=False)

    class Meta:
        model = UserSerializer.Meta.model
        fields = ('email', 'password', 'domain', 'captcha')
        extra_kwargs = UserSerializer.Meta.extra_kwargs

    def validate_domain(self, value):
        serializer = DomainSerializer(data=dict(name=value), context=self.context)
        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError:
            raise serializers.ValidationError(serializer.default_error_messages['name_unavailable'],
                                              code='name_unavailable')
        return value

    def create(self, validated_data):
        validated_data.pop('domain', None)
        # If validated_data['captcha'] exists, the captcha was also validated, so we can set the user to verified
        if 'captcha' in validated_data:
            validated_data.pop('captcha')
            validated_data['needs_captcha'] = False
        return super().create(validated_data)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class EmailPasswordSerializer(EmailSerializer):
    password = serializers.CharField()


class ChangeEmailSerializer(serializers.Serializer):
    new_email = serializers.EmailField()

    def validate_new_email(self, value):
        if value == self.context['request'].user.email:
            raise serializers.ValidationError('Email address unchanged.')
        return value


class ResetPasswordSerializer(EmailSerializer):
    captcha = CaptchaSolutionSerializer(required=True)


class CustomFieldNameUniqueValidator(UniqueValidator):
    """
    Does exactly what rest_framework's UniqueValidator does, however allows to further customize the
    query that is used to determine the uniqueness.
    More specifically, we allow that the field name the value is queried against is passed when initializing
    this validator. (At the time of writing, UniqueValidator insists that the field's name is used for the
    database query field; only how the lookup must match is allowed to be changed.)
    """

    def __init__(self, queryset, message=None, lookup='exact', lookup_field=None):
        self.lookup_field = lookup_field
        super().__init__(queryset, message, lookup)

    def filter_queryset(self, value, queryset, field_name):
        """
        Filter the queryset to all instances matching the given value on the specified lookup field.
        """
        filter_kwargs = {'%s__%s' % (self.lookup_field or field_name, self.lookup): value}
        return qs_filter(queryset, **filter_kwargs)


class AuthenticatedActionSerializer(serializers.ModelSerializer):
    state = serializers.CharField()  # serializer read-write, but model read-only field
    validity_period = settings.VALIDITY_PERIOD_VERIFICATION_SIGNATURE

    class Meta:
        model = models.AuthenticatedAction
        fields = ('state',)

    @classmethod
    def _pack_code(cls, data):
        payload = json.dumps(data).encode()
        code = crypto.encrypt(payload, context='desecapi.serializers.AuthenticatedActionSerializer').decode()
        return code.rstrip('=')

    @classmethod
    def _unpack_code(cls, code, *, ttl):
        code += -len(code) % 4 * '='
        try:
            payload = crypto.decrypt(code.encode(), context='desecapi.serializers.AuthenticatedActionSerializer',
                                     ttl=ttl)
            return json.loads(payload.decode())
        except (TypeError, UnicodeDecodeError, UnicodeEncodeError, json.JSONDecodeError, binascii.Error):
            raise ValueError

    def to_representation(self, instance: models.AuthenticatedUserAction):
        # do the regular business
        data = super().to_representation(instance)

        # encode into single string
        return {'code': self._pack_code(data)}

    def to_internal_value(self, data):
        data = data.copy()  # avoid side effect from .pop

        # calculate code TTL
        validity_period = self.context.get('validity_period', self.validity_period)
        try:
            ttl = validity_period.total_seconds()
        except AttributeError:
            ttl = None  # infinite

        # decode from single string
        try:
            unpacked_data = self._unpack_code(self.context['code'], ttl=ttl)
        except KeyError:
            raise serializers.ValidationError({'code': ['This field is required.']})
        except ValueError:
            if ttl is None:
                msg = 'This code is invalid.'
            else:
                msg = f'This code is invalid, possibly because it expired (validity: {validity_period}).'
            raise serializers.ValidationError({api_settings.NON_FIELD_ERRORS_KEY: msg})

        # add extra fields added by the user
        unpacked_data.update(**data)

        # do the regular business
        return super().to_internal_value(unpacked_data)

    def act(self):
        self.instance.act()
        return self.instance

    def save(self, **kwargs):
        raise ValueError


class AuthenticatedBasicUserActionSerializer(AuthenticatedActionSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=models.User.objects.all(),
        error_messages={'does_not_exist': 'This user does not exist.'},
        pk_field=serializers.UUIDField()
    )

    class Meta:
        model = models.AuthenticatedBasicUserAction
        fields = AuthenticatedActionSerializer.Meta.fields + ('user',)


class AuthenticatedActivateUserActionSerializer(AuthenticatedBasicUserActionSerializer):
    captcha = CaptchaSolutionSerializer(required=False)

    class Meta(AuthenticatedBasicUserActionSerializer.Meta):
        model = models.AuthenticatedActivateUserAction
        fields = AuthenticatedBasicUserActionSerializer.Meta.fields + ('captcha', 'domain',)
        extra_kwargs = {
            'domain': {'default': None, 'allow_null': True}
        }

    def validate(self, attrs):
        try:
            attrs.pop('captcha')  # remove captcha from internal value to avoid passing to Meta.model(**kwargs)
        except KeyError:
            if attrs['user'].needs_captcha:
                raise serializers.ValidationError({'captcha': fields.Field.default_error_messages['required']})
        return attrs


class AuthenticatedChangeEmailUserActionSerializer(AuthenticatedBasicUserActionSerializer):
    new_email = serializers.EmailField(
        validators=[
            CustomFieldNameUniqueValidator(
                queryset=models.User.objects.all(),
                lookup_field='email',
                message='You already have another account with this email address.',
            )
        ],
        required=True,
    )

    class Meta(AuthenticatedBasicUserActionSerializer.Meta):
        model = models.AuthenticatedChangeEmailUserAction
        fields = AuthenticatedBasicUserActionSerializer.Meta.fields + ('new_email',)


class AuthenticatedResetPasswordUserActionSerializer(AuthenticatedBasicUserActionSerializer):
    new_password = serializers.CharField(write_only=True)

    class Meta(AuthenticatedBasicUserActionSerializer.Meta):
        model = models.AuthenticatedResetPasswordUserAction
        fields = AuthenticatedBasicUserActionSerializer.Meta.fields + ('new_password',)


class AuthenticatedDeleteUserActionSerializer(AuthenticatedBasicUserActionSerializer):

    class Meta(AuthenticatedBasicUserActionSerializer.Meta):
        model = models.AuthenticatedDeleteUserAction


class AuthenticatedDomainBasicUserActionSerializer(AuthenticatedBasicUserActionSerializer):
    domain = serializers.PrimaryKeyRelatedField(
        queryset=models.Domain.objects.all(),
        error_messages={'does_not_exist': 'This domain does not exist.'},
    )

    class Meta:
        model = models.AuthenticatedDomainBasicUserAction
        fields = AuthenticatedBasicUserActionSerializer.Meta.fields + ('domain',)


class AuthenticatedRenewDomainBasicUserActionSerializer(AuthenticatedDomainBasicUserActionSerializer):
    validity_period = None

    class Meta(AuthenticatedDomainBasicUserActionSerializer.Meta):
        model = models.AuthenticatedRenewDomainBasicUserAction
