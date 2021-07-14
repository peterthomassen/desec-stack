.. _`manage-rrsets`:

Retrieving and Creating DNS Records
-----------------------------------

All DNS information is composed of so-called *Resource Record Sets*
(*RRsets*).  An RRset is the set of all Resource Records of a given record
type for a given name.  For example, the name ``example.com`` may have an
RRset of type ``A``, denoting the set of IPv4 addresses associated with this
name.  In the traditional Bind zone file format, the RRset would be written
as::

    <name>  IN  A 127.0.0.1
    <name>  IN  A 127.0.0.2
    ...

Each of these lines is a Resource Record, and together they form an RRset.

The basic units accessible through the API are RRsets, each represented by a
JSON object.  The object structure is detailed in the next section.

The relevant endpoints all reside under ``/api/v1/domains/{name}/rrsets/``,
where ``{name}`` is the name of a domain you own.  When operating on domains
that don't exist or you don't own, the API responds with a ``404 Not Found``
status code.  For a quick overview of the available endpoints, methods, and
operations, see :ref:`endpoint-reference`.

All operations are subject to rate limiting.  For details, see
:ref:`rate-limits`.


.. _`RRset object`:

RRset Field Reference
~~~~~~~~~~~~~~~~~~~~~

A JSON object representing an RRset has the following structure::

    {
        "created": "2019-09-18T16:32:16.510368Z",
        "domain": "example.com",
        "subname": "www",
        "name": "www.example.com.",
        "type": "A",
        "records": [
            "127.0.0.1",
            "127.0.0.2"
        ],
        "ttl": 3600,
        "touched": "2020-04-06T09:24:09.987436Z"
    }

Field details:

``created``
    :Access mode: read-only

    Timestamp of RRset creation, in ISO 8601 format (e.g.
    ``2019-09-18T16:32:16.510368Z``).

``domain``
    :Access mode: read-only

    Name of the zone to which the RRset belongs.

    Note that the zone name does not follow immediately from the RRset name.
    For example, the ``com`` zone contains an RRset of type ``NS`` for the
    name ``example.com.``, in order to set up the delegation to
    ``example.com``'s DNS operator.  The DNS operator's nameserver again
    has a similar ``NS`` RRset which, this time however, belongs to the
    ``example.com`` zone.

``name``
    :Access mode: read-only

    The full DNS name of the RRset.  If ``subname`` is empty, this is equal to
    ``{name}.``, otherwise it is equal to ``{subname}.{name}.``.

``records``
    :Access mode: read, write

    Array of record content strings.  Please note that when a record value
    contains a domain name, it is in almost all cases required to add a final
    dot after the domain name.  This applies, for example, to the ``CNAME``,
    ``MX``, and ``SRV`` record types.  A typical ``MX`` value would thus be
    be ``10 mx.example.com.`` (note the trailing dot).

    Please also consider the `caveat on the priority field`_.

    The maximum number of array elements is 4091, and the maximum length of
    the array is 64,000 (after JSON encoding).

    Records must be given in presentation format (a.k.a. "BIND" or zone file
    format).  Record values that are not given in canonical form, such as
    ``0:0000::1`` for an IPv6 address, will be converted by the API into
    canonical form (here: ``::1``).  Exact validation and canonicalization
    depend on the record type.

``subname``
    :Access mode: read, write-once (upon RRset creation)

    Subdomain string which, together with ``domain``, defines the RRset name.
    Typical examples are ``www`` or ``_443._tcp``.  In general, a subname
    consists of lowercase alphanumeric characters as well as hyphens ``-``,
    underscores ``_``, and dots ``.``.  Wildcard name components are
    denoted by ``*``; this is allowed only once at the beginning of the name
    (see RFC 4592 for details).  The maximum length is 178.  Further
    restrictions may apply on a per-user basis.

    Note that for subnames to be created, they must be explicitly stated.  In 
    particular, the ``www`` name is not automatically created when assigning
    an IP address to your domain name (by creating an ``A`` or ``AAAA``
    record).  The same applies for the catch-all mechanism:  If you would like
    a record to apply to all otherwise undefined subdomains, the wildcard
    subdomain ``*`` must be explicitly given.

``ttl``
    :Access mode: read, write

    TTL (time-to-live) value, which dictates for how long resolvers may cache
    this RRset, measured in seconds.  The smallest acceptable value is given by
    the domain's :ref:`minimum TTL <domain object>` setting.  The maximum value
    is 86400 (one day).

``type``
    :Access mode: read, write-once (upon RRset creation)

    RRset type (uppercase).  A broad range of record types is supported, with
    most DNSSEC-related types (and the ``SOA`` type) managed automagically by
    the backend.  For details, check `Supported Types`_ and `Restricted
    Types`_.

``touched``
    :Access mode: read-only

    Timestamp of when the RRset was last touched (same format as ``created``).
    This field reflects the most recent write request to the RRset. It is also
    updated when the write request does not actually change anything (e.g.
    overwriting a DNS record with identical values).


.. _creating-an-rrset:

Creating an RRset
~~~~~~~~~~~~~~~~~

To create a new RRset, simply issue a ``POST`` request to the
``/api/v1/domains/{name}/rrsets/`` endpoint, like this::

    curl -X POST https://desec.io/api/v1/domains/{name}/rrsets/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<< \
        '{"subname": "www", "type": "A", "ttl": 3600, "records": ["127.0.0.1", "127.0.0.2"]}'

``type``, ``records``, and ``ttl`` are mandatory, whereas the ``subname``
field is optional.

Upon success, the response status code will be ``201 Created``, with the RRset
contained in the response body.  If the operation cannot be performed with the
given parameters, the API returns ``400 Bad Request``.  This can happen, for
instance, when there is a conflicting RRset with the same name and type, when
not all required fields were provided correctly (such as, when the ``type``
value was not provided in uppercase), or when the record content is
semantically invalid (e.g. when you provide an unknown record type, or an ``A``
value that is not an IPv4 address).

Note that the values of ``type`` and ``subname`` as well as the ``records``
items are strings, and as such the JSON specification requires them to be
enclosed in double quotes (with the quotes being part of the field value);
your shell or programming language may require another layer of quotes!  By
contrast, ``ttl`` is an integer field, so the JSON value does not contain
quotes.

RRset write operations are subject to rate limiting (see :ref:`rate-limits`).
When creating (or updating) a large number of RRsets, we strongly encourage
you to use `Bulk Operations`_ instead of multiple sequential requests.
(Single requests are much more expensive on the server side, as each request
triggers a DNSSEC signing operation.  With bulk requests, only one signing
operation is performed, covering all changes together.)

Creating a TLSA RRset
`````````````````````

A common use case is the creation of a ``TLSA`` RRset which carries information
about the TLS certificate used by the server that the domain points to.  For
example, to create a ``TLSA`` RRset for ``www.example.com``, you can run::

    curl -X POST https://desec.io/api/v1/domains/{name}/rrsets/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<EOF
        {
          "subname": "_443._tcp.www",
          "type": "TLSA",
          "ttl": 3600,
          "records": ["3 1 1 11501875615d4.....dd122bbf9190"]
        }
    EOF

**Note:** The ``subname`` is prefixed with ``_{port}._{transport_protocol}``.
For a HTTPS server, this will usually be ``_443._tcp`` (for an otherwise empty
``subname``), or ``_443._tcp.www`` for the common ``www`` domain prefix.  For
other use cases, the values have to be adapted accordingly (e.g. ``_993._tcp``
for an IMAPS server).

To generate the ``TLSA`` from your certificate, you can use a tool like
https://www.huque.com/bin/gen_tlsa.  We are planning to provide a tool that is
connected directly to our API in the future.  For full detail on how ``TLSA``
records work, please refer to RFC 6698.

Bulk Creation of RRsets
```````````````````````

It is often desirable to create several RRsets at once.  This is achieved by
sending an array of RRset objects to the ``rrsets/`` endpoint (instead of just
one), like this::

    curl -X POST https://desec.io/api/v1/domains/{name}/rrsets/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<EOF
        [
          {"subname": "www", "type": "A", "ttl": 3600, "records": ["1.2.3.4"]},
          {"subname": "www", "type": "AAAA", "ttl": 3600, "records": ["c0::fefe"]},
          ...
        ]
    EOF

This is especially useful for bootstrapping a new domain.

For details about input validation and return status codes, please refer to
`Bulk Operations`_.


Retrieving all RRsets in a Zone
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``/api/v1/domains/{name}/rrsets/`` endpoint reponds to ``GET`` requests
with an array of `RRset object`_\ s. For example, you may issue the following
command::

    curl -X GET https://desec.io/api/v1/domains/{name}/rrsets/ \
        --header "Authorization: Token {token}"

to retrieve the contents of a zone that you own.  RRsets are returned in
reverse chronological order of their creation.

The response status code in case of success is ``200 OK``.  This is true also
if there are no RRsets in the zone; in this case, the response body will be an
empty JSON array.

.. _pagination:

Pagination
``````````
Up to 500 items are returned at a time.  If more than 500 items would match the
query, the use of the ``cursor`` query parameter is required.  The first page
can be retrieved by sending an empty pagination parameter, ``cursor=``.

Once in pagination mode, the URLs to retrieve the next (or previous) page are
given in the ``Link:`` response header.  For example::

    Link: <https://desec.io/api/v1/domains/{domain}/rrsets/?cursor=>; rel="first",
      <https://desec.io/api/v1/domains/{domain}/rrsets/?cursor=:prev_cursor>; rel="prev",
      <https://desec.io/api/v1/domains/{domain}/rrsets/?cursor=:next_cursor>; rel="next"

where ``:prev_cursor`` and ``:next_cursor`` are page identifiers that are to
be treated as opaque by clients.  On the first/last page, the ``Link:`` header
will not contain a ``prev``/``next`` link, respectively.

If no pagination parameter is given although pagination is required, the server
will return ``400 Bad Request``, along with a ``Link:`` header containing the
``first`` link, and human-readable instructions on pagination in the body.


Filtering by Record Type
````````````````````````

To retrieve an array of all RRsets from your zone that have a specific type
(e.g. all ``A`` records, regardless of ``subname``), augment the previous
``GET`` request with a ``type`` query parameter carrying the desired RRset type
like::

    curl https://desec.io/api/v1/domains/{name}/rrsets/?type={type} \
        --header "Authorization: Token {token}"

Query parameters used for filtering are fully compatible with `pagination`_.


Filtering by Subname
````````````````````

To filter the RRsets array by subname (e.g. to retrieve all records in the
``www`` subdomain, regardless of their type), use the ``subname`` query
parameter, like this::

    curl https://desec.io/api/v1/domains/{name}/rrsets/?subname={subname} \
        --header "Authorization: Token {token}"

This approach also allows to retrieve all records associated with the zone
apex (i.e. ``example.com`` where ``subname`` is empty), by querying
``rrsets/?subname=``.

Query parameters used for filtering are fully compatible with `pagination`_.


Retrieving a Specific RRset
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To retrieve an RRset with a specific name and type from your zone (e.g. the
``A`` record for the ``www`` subdomain), issue a ``GET`` request with the
``subname`` information and the type appended to the ``rrsets/`` endpoint,
like this::

    curl https://desec.io/api/v1/domains/{name}/rrsets/{subname}/{type}/ \
        --header "Authorization: Token {token}"

This will return only one RRset (i.e., the response is not a JSON array).  The
response status code is ``200 OK`` if the requested RRset exists, and ``404
Not Found`` otherwise.

Accessing the Zone Apex
```````````````````````

**Note:** The RRset at the zone apex (the domain root with an empty subname)
*cannot* be queried via ``/api/v1/domains/{name}/rrsets//{type}/``.  This is due
to normalization rules of the HTTP specification which cause the double-slash
``//`` to be replaced with a single slash ``/``, breaking the URL structure.

To access an RRset at the root of your domain, we reserved the special subname
value ``@``.  This is a common placeholder for this use case (see RFC 1035).
As an example, you can retrieve the IPv4 address(es) of your domain root by
running::

    curl https://desec.io/api/v1/domains/{name}/rrsets/@/A/ \
        --header "Authorization: Token {token}"

**Pro tip:** If you like to have the convenience of simple string expansion
in the URL, you can add three dots after ``{subname}``, like so::

    curl https://desec.io/api/v1/domains/{name}/rrsets/{subname}.../{type}/ \
        --header "Authorization: Token {token}"

With this syntax, the above-mentioned normalization problem does not occur,
and no special treatment is needed for accessing the zone apex.  You can
think of the three dots as abbreviating the rest of the DNS name.


Modifying an RRset
~~~~~~~~~~~~~~~~~~

To modify an RRset, use the endpoint that you would also use to retrieve that
specific RRset.  The API allows changing the values of ``records`` and
``ttl``.  When using the ``PATCH`` method, only fields you would like to modify
need to be provided.  In contrast, if you use ``PUT``, the full resource must
be specified (that is, all fields, including ``subname`` and ``type``).
Examples::

    curl -X PUT https://desec.io/api/v1/domains/{name}/rrsets/{subname}/{type}/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<EOF
        {
          "subname": "{subname}",
          "type": "{type}",
          "ttl": 3600,
          "records": ["..."]
        }
    EOF

    curl -X PATCH https://desec.io/api/v1/domains/{name}/rrsets/{subname}/{type}/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<< \
        '{"ttl": 86400}'

If the RRset was updated successfully, the API returns ``200 OK`` with the
updated RRset in the response body.  An exception to this rule is when an
empty array is provided as the ``records`` field, in which case the RRset is
deleted and the return code is ``204 No Content`` (cf. `Deleting an RRset`_).

In case the operation cannot be performed with
the given parameters, the API returns ``400 Bad Request``.  This can happen, for
instance, when there is a conflicting RRset with the same name and type, when
not all required fields were provided correctly (such as, when the ``type``
value was not provided in uppercase), or when the record content is
semantically invalid (e.g. when you provide an unknown record type, or an ``A``
value that is not an IPv4 address).

To modify an RRset at the zone apex (empty subname), use the special subname
value ``@`` in the endpoint URL (read more about `Accessing the Zone Apex`_).

Bulk Modification of RRsets
```````````````````````````

It is sometimes desirable to modify several RRsets at once.  This is achieved
by sending an array of RRset objects to the ``rrsets/`` endpoint (instead of
just one), like this::

    curl -X PUT https://desec.io/api/v1/domains/{name}/rrsets/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<EOF
        [
          {"subname": "www", "type": "A", "ttl": 3600, "records": ["1.2.3.4"]},
          {"subname": "www", "type": "AAAA", "ttl": 3600, "records": ["c0::fefe"]},
          ...
        ]
    EOF

Each given RRset is uniquely identified by its ``subname`` and ``type`` (with
``subname``  defaulting to the empty string if omitted). For ``ttl`` and
``records``, the usual validation rules apply.

For details about input validation and return status codes, please refer to
`Bulk Operations`_.


Deleting an RRset
~~~~~~~~~~~~~~~~~

To delete an RRset, you can send a ``DELETE`` request to the endpoint
representing the RRset. Alternatively, you can modify it and provide an empty
array for the ``records`` field (``[]``).

Upon success or if the RRset did not exist in the first place, the response
status code is ``204 No Content``.

Bulk Deletion of RRsets
```````````````````````

It is sometimes desirable to delete an RRset while creating or modifying
another one.  This is achieved by sending a bulk request with an RRset that
has an empty records list ``[]``, using the ``PATCH`` or ``PUT`` method::

    curl -X PATCH https://desec.io/api/v1/domains/{name}/rrsets/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<EOF
        [
          {"subname": "www", "type": "A", "ttl": 3600, "records": ["1.2.3.4"]},
          {"subname": "www", "type": "AAAA", "records": []}
        ]
    EOF

For details about input validation and return status codes, please refer to
`Bulk Operations`_.


Bulk Operations
~~~~~~~~~~~~~~~

The ``rrsets/`` endpoint supports bulk operations via the ``POST``, ``PATCH``,
and ``PUT`` request methods. You can simply send an array of RRset objects
(instead of just one), like this::

    curl -X PATCH https://desec.io/api/v1/domains/{name}/rrsets/ \
        --header "Authorization: Token {token}" \
        --header "Content-Type: application/json" --data @- <<EOF
        [
          {"subname": "www", "type": "A", "ttl": 3600, "records": ["1.2.3.4"]},
          {"subname": "www", "type": "AAAA", "ttl": 3600, "records": ["c0::fefe"]},
          {"subname": "backup", "type": "MX", "records": []},
          ...
        ]
    EOF

Note that the zone apex is referred to by an empty subname string,
``"subname": ""``. (The special character ``@`` is not accepted as an alias.)
For context, see `Accessing the Zone Apex`_.

Atomicity
`````````
Bulk operations are performed atomically, i.e. either all given RRsets are
accepted and published in (or deleted from) the DNS, or none of them are.

This allows you to smoothly apply large DNS changes to your domain *without*
running into the undesirable situation of an error showing up half-way through
the process when some changes already have been applied.

Field requirements
``````````````````
For the ``POST`` and ``PUT`` methods, all fields are required for each given
RRset.  With ``POST``, only new RRsets are acceptable (i.e. the domain must
not yet have an RRset with the same subname and type), while ``PUT`` allows
both creating new RRsets and modifying existing ones.

For the ``PATCH`` method, only ``subname `` and ``type`` is required; if you
want to modify only ``ttl`` or ``records``, you can skip the other field.  To
create a new RRset using ``PATCH``, all fields but ``subname`` must be
specified.

To delete an RRset during a bulk operation, use ``PATCH`` or ``PUT`` and set
``records`` to ``[]``.

Input validation
````````````````
The API performs various types of validation checks:

- Sanity checks, such as syntax, basic semantics (e.g. negative TTL).

- RRset uniqueness (with respect to subname and type) and ``CNAME``
  exclusivity.  We both check with respect to pre-existing RRsets as well as
  with respect to other RRsets sent in the same request.

- DNS record checks, such as whether the given type is a supported record
  type, and whether the given record contents are consistent with the type.

Error responses have status ``400 Bad Request`` and contain a list of errors
in the response body, with each list item corresponding to one part of the
bulk request, in the same order.  Parts that passed without errors have an
empty error object ``{}``, and parts with errors contain a data structure
explaining the error(s) in a human-readable fashion.

In case of several errors for the same RRset, we sometimes only return one
of them.  For example, if you're creating an RRset that conflicts with an
existing RRset, the API does not perform further validation of the record
contents, and instead only points out the uniqueness conflict.


Notes
~~~~~

Consider the following general remarks that apply to our API as a whole:

- All operations are performed on RRsets, not on the individual Resource
  Records.

- The TTL (time-to-live: time for which resolvers may cache DNS information)
  is a property of an RRset (and not of a record).  Thus, all records in an
  RRset share the record type and also the TTL.


Supported Types
```````````````

Generally, the API supports almost all `RRset types supported by PowerDNS`_,
with a few exceptions for such record types that the backend manages
automatically.

.. _RRset types supported by PowerDNS: https://doc.powerdns.com/authoritative/appendices/types.html

At least the following record types are supported: ``A``, ``AAAA``, ``AFSDB``,
``APL``, ``CAA``, ``CDNSKEY``, ``CDS``, ``CERT``, ``CNAME``, ``DHCID``,
``DNAME``, ``DNSKEY``, ``DLV``, ``DS``, ``EUI48``, ``EUI64``, ``HINFO``,
``HTTPS``, ``KX``, ``LOC``, ``MX``, ``NAPTR``, ``NS``, ``OPENPGPKEY``,
``PTR``, ``RP``, ``SMIMEA``, ``SPF``, ``SRV``, ``SSHFP``, ``SVCB``, ``TLSA``,
``TXT``, ``URI``.  (The ``SOA`` record is managed automatically.)

Special care needs to be taken with some types of records, as explained below.


Restricted Types
````````````````

``ALIAS``/``ANAME``
    Due to conflicts with the security guarantees we would like to give, we do
    not support these record types (`detailed explanation`_).  Attempts to
    create such records will result in a ``400 Bad Request`` response.

    If you need redirect functionality at the zone apex, consider using the
    ``HTTPS`` record type which serves exactly this purpose.  (Note that as of
    06/2021, this record type is not yet supported in all browsers.)

.. _detailed explanation: https://talk.desec.io/t/clarification-on-alias-records/113/2

``DNSKEY``, ``DS``, ``CDNSKEY``, ``CDS``, ``NSEC3PARAM``, ``RRSIG``
    These record types are meant to provide DNSSEC-related information in
    order to secure the data stored in your zones.  RRsets of this type are
    generated and served automatically by our nameservers.  It is currently
    not possible to read or manipulate any automatically generated values
    using the API.

    Note, however, that it is possible to add *additional* values for some
    key-related records types (``DNSKEY``, ``DS``, ``CDNSKEY``) in order to
    publish extra public keys.  For details, see `DNSKEY caveat`_.

    When attempting an unsupported operation, ``403 Forbidden`` or ``400 Bad
    Request`` is returned.

.. _`SOA caveat`:

``SOA`` record
    The ``SOA`` record cannot be read or written through this interface.  When
    attempting to create, modify or otherwise access an ``SOA`` record, ``400
    Bad Request`` or ``403 Forbidden`` is returned, respectively.

    The rationale behind this is that the content of the ``SOA`` record is
    entirely determined by the DNS operator, and users should not have to bother
    with this kind of metadata.  Upon zone changes, the backend automatically
    takes care of updating the ``SOA`` record accordingly.

    If you are interested in the value of the ``SOA`` record, you can retrieve
    it using a standard DNS query.


Caveats
```````

.. _`caveat on the priority field`:

Record types with priority field
    The deSEC DNS API does not explicitly support structured records fields
    (such as the priority field used for ``MX``, ``SRV`` and the like).

    Instead, those fields are expected to be concatenated in the conventional
    order used for zone files, with spaces in between them. For ``MX`` RRsets,
    that means that the priority is located at the beginning of the record
    content, separated from the rest of it by a space (e.g.
    ``10 mx.example.com.``).

.. _`DNSKEY caveat`:

``CDNSKEY``, ``CDS``, ``DNSKEY`` record
    These records are managed automatically by deSEC.  However, our API allows
    adding additional values for specialized purposes.  Regular, automatic
    DNSSEC operation does not require deSEC users to touch these records.

    Using these record types inappropriately may break proper functioning of
    your domain.  If you know what you're doing, you can use these record
    types for announcing extra DNSSEC public keys, for example in order to
    orchestrate keys when your zone is signed by several DNSSEC operators
    independently ("multi-signer setup", see also RFC 8901).

    **Note:** Manually provided records are published **in addition** to the
    ones managed automatically by deSEC.  As a consequence, the TTL values of
    extra records configured at the zone apex are ignored by the API, and
    manually provided records are published with the same TTL as automatic
    ones.

``CNAME`` record
    - The record value (target) must be terminated by a dot ``.`` (as in
      ``example.com.``).  Only one value is allowed.

    - A ``CNAME`` record is not allowed when other records exist at the same
      subname.  This is a limitation of the DNS specification.

    - Due to the previous limitation, a CNAME is not allowed at the zone apex
      (empty subname), as it would always collide with the NS record (and the
      internally managed SOA record).

      If you need redirect functionality at the zone apex, consider using the
      ``HTTPS`` record type which serves exactly this purpose.  (Note that as
      of 06/2021, this record type is not yet supported in all browsers.)

``DNSKEY`` record
    See notes on the ``CDNSKEY``, ``CDS``, and ``DNSKEY`` record types.

``MX`` record
    The ``MX`` record value consists of the priority value and a mail server
    name, which must be terminated by a dot ``.``.  Example: ``10
    mail.a4a.de.``

``NS`` record
    - The record value must be terminated by a dot ``.`` (as in
      ``ns1.desec.io.``).

    - The use of wildcard RRsets (with one component of ``subname`` being equal
      to ``*``) of type ``NS`` is **discouraged**.  This is because the
      behavior of wildcard ``NS`` records in conjunction with DNSSEC is
      undefined, per RFC 4592, Sec. 4.2.

``TXT`` record
    - The contents of the ``TXT`` record must be enclosed in double quotes.
      Thus, when ``POST``\ ing to the API, make sure to do proper escaping
      etc. as required by the client you are using.  Here's an example of how
      to create a ``TXT`` RRset::

          curl -X POST https://desec.io/api/v1/domains/{name}/rrsets/ \
              --header "Authorization: Token {token}" \
              --header "Content-Type: application/json" --data @- <<< \
              '{"type": "TXT", "records": ["\"test value1\"","\"value2\""], "ttl": 3600}'

    - Record values consisting of several token strings separated by
      whitespace are permitted, for example:
      ``["\"token 1 of record 1\" \"token 2 of record 1\"", "\"record 2\""]``

      Token strings longer than 255 characters are automatically split into
      several token strings.  (This maximum length is given by the DNS
      specification.)

    - Binary record contents are supported, but subject to various escaping
      rules (both JSON and ``TXT`` record syntax; in addition, certain
      non-printable characters are not accepted even when unicode-escaped, like
      ``\u0000``).  Still, you can store any binary data by using DNS-style
      ``\DDD`` encoding for your binary data (see RFC 1035 Sec. 3.3.14 and 5.1).
      For example, a carriage return (``\r``) can be stored as ``\013``.  (Note
      that JSON encoding needs to be applied on top of that, so a valid
      ``records`` field would be ``["\"\\013\""]``.)
