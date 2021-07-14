deSEC Stack
===========

This is a docker-compose application providing the basic stack for deSEC name services. It consists of

- `nslord`: Eventually authoritative DNS server (PowerDNS). DNSSEC keying material is generated here.
- `nsmaster`: Stealth authoritative DNS server (PowerDNS). Receives fully signed AXFR zone transfers from `nslord`. No access to keys.
- `api`: RESTful API to create deSEC users and domains, see [documentation](https://desec.readthedocs.io/).
- `dbapi`, `dblord`, `dbmaster`: Postgres database for `api`, MariaDB databases for `nslord` and `nsmaster`, respectively.
- `www`: nginx instance serving static web site content and proxying to `api`
- `celery`: A shadow instance of the `api` code for performing asynchronous tasks (email delivery).
- `rabbitmq`: `celery`'s queue
- `memcached`: `api`-wide in-memory cache, currently used to keep API throttling state
- `openvpn-server`: OpenVPN server used to tunnel replication traffic between this stack and frontend DNS secondaries
- `prometheus`: Prometheus server for monitoring

Requirements
------------

Although most configuration is contained in this repository, some external dependencies need to be met before the application can be run. Dependencies are:

1.  We run this software with the `--userland-proxy=false` flag of the `dockerd` daemon, and recommend you do the same.

2.  Also, configure certificates for `openvpn-server`:

    - [Get easy-rsa](https://github.com/OpenVPN/easy-rsa) and follow [this tutorial](https://github.com/OpenVPN/easy-rsa/blob/master/README.quickstart.md).
    - Then, copy `ca.crt`, `server.crt`, and `server.key` to `openvpn-server/secrets/`.
    - Create a preshared secret using `openvpn --genkey --secret ta.key` inside `openvpn-server/secrets/`.

    For provisioning a secondary, use the same `easy-rsa` PKI and create a new `client.key` and `client.crt` pair. Transfer these securely onto the secondary, along with `ca.crt` and `ta.key`.
    (You can also create the key on the secondary and only transfer a certificate signing request and the certificate.)

3.  Set sensitive information and network topology using environment variables or an `.env` file. You need (you can use the `.env.default` file as a template):
    - global
      - `DESECSTACK_DOMAIN`: domain name under which the entire system will be running. The API will be reachable at https://desec.$DESECSTACK_DOMAIN/api/. For development setup, we recommend using `yourname.dedyn.io`
      - `DESECSTACK_NS`: the names of the authoritative name servers, i.e. names pointing to your secondary name servers. Minimum 2.
    - network
      - `DESECSTACK_IPV4_REAR_PREFIX16`: IPv4 net, size /16, for assignment of internal container IPv4 addresses. **NOTE:** If you change this in an existing setup, you 
        need to manually update persisted data structures such as the MySQL grant tables! Better don't do it.
      - `DESECSTACK_IPV6_SUBNET`: IPv6 net, ideally /80 (see below)
      - `DESECSTACK_IPV6_ADDRESS`: IPv6 address of frontend container, ideally 0642:ac10:0080 in within the above subnet (see below)
    - certificates
      - `DESECSTACK_WWW_CERTS`: `./path/to/certificates` for `www` container. This directory is monitored for changes so that nginx can reload when new keys/certificates are provided. **Note:** The reload is done any time something changes in the directory. The relevant files are **not** watched individually.
    - API-related
      - `DESECSTACK_API_ADMIN`: white-space separated list of Django admin email addresses
      - `DESECSTACK_API_AUTHACTION_VALIDITY`: number of hours for which authenticated action links (e.g. email verification) should be considered valid (default: 0)
      - `DESECSTACK_API_DEBUG`: Django debug setting. Must be True (default in `docker-compose.dev.yml`) or False (default otherwise)
      - `DESECSTACK_API_SEPA_CREDITOR_ID`: SEPA creditor ID for donations
      - `DESECSTACK_API_EMAIL_HOST`: when sending email, use this mail server
      - `DESECSTACK_API_EMAIL_HOST_USER`: username for sending email
      - `DESECSTACK_API_EMAIL_HOST_PASSWORD`: password for sending email
      - `DESECSTACK_API_EMAIL_PORT`: port for sending email
      - `DESECSTACK_API_SECRETKEY`: Django secret
      - `DESECSTACK_API_PSL_RESOLVER`: Resolver IP address to use for PSL lookups. If empty, the system's default resolver is used.
      - `DESECSTACK_DBAPI_PASSWORD_desec`: database password for desecapi
      - `DESECSTACK_MINIMUM_TTL_DEFAULT`: minimum TTL users can set for RRsets. The setting is per domain, and the default defined here is used on domain creation.
    - nslord-related
      - `DESECSTACK_DBLORD_PASSWORD_pdns`: mysql password for pdns on nslord
      - `DESECSTACK_NSLORD_APIKEY`: pdns API key on nslord
      - `DESECSTACK_NSLORD_CARBONSERVER`: pdns `carbon-server` setting on nslord (optional)
      - `DESECSTACK_NSLORD_CARBONOURNAME`: pdns `carbon-ourname` setting on nslord (optional)
      - `DESECSTACK_NSLORD_DEFAULT_TTL`: TTL to use by default, including for default NS records
    - nsmaster-related
      - `DESECSTACK_DBMASTER_PASSWORD_pdns`: mysql password for pdns on nsmaster
      - `DESECSTACK_NSMASTER_APIKEY`: pdns API key on nsmaster (required so that we can execute zone deletions on nsmaster, which replicates to the secondaries)
      - `DESECSTACK_NSMASTER_CARBONSERVER`: pdns `carbon-server` setting on nsmaster (optional)
      - `DESECSTACK_NSMASTER_CARBONOURNAME`: pdns `carbon-ourname` setting on nsmaster (optional)
    - monitoring-related
      - `DESECSTACK_WATCHDOG_SECONDARIES`: space-separated list of secondary hostnames; used to check correct replication of recent DNS changes
      - `DESECSTACK_PROMETHEUS_PASSWORD`: basic auth password for user `prometheus` at `https://${DESECSTACK_DOMAIN}/prometheus/`

How to Run
----------

Development:

    $ ./dev

Production:

    $ docker-compose build && docker-compose up

Storage
-------
All important data is stored in the databases managed by the `db*` containers. They use Docker volumes which, by default, reside in `/var/lib/docker/volumes/desec-stack_{dbapi_postgres,dblord_mysql,dbmaster_mysql}`.
This is the location you will want to back up. (Be sure to follow standard MySQL/Postgres backup practices, i.e. make sure things are consistent.)

API Versions and Roadmap
------------------------

deSEC currently maintains the following API versions:

API Version | URL Prefix | Status    | Support Ends
----------- | ---------- | --------- | ------------
Version 1   | `/api/v1/` |  stable   | earliest 6 months after v2 is declared stable
Version 2   | `/api/v2/` |  unstable

You can find our documentation for all API versions at https://desec.readthedocs.io/. (Select the version of interest in the navigation bar.)

Notes on IPv6
-------------

This stack is IPv6-capable. Caveats:

  - It is not necessary to start the Docker daemon with `--ipv6` or `--fixed-cidr-v6`. However, it is recommended to run `dockerd` with `--userland-proxy=false` to avoid 
    exposing ports on the host IPv6 address through `docker-proxy`.

  - Topology: Assuming 2a01:4f8:a0:12eb::/64 is the host network, and we reserve 2a01:4f8:a0:12eb:deec::/80 for the deSEC stack. Docker has more or less established that 
    IPv6  addresses be composed of the /80 prefix and the container MAC address. We choose the private 06:42:ac MAC prefix, defining a /104 subnet. For the remaining 24 
    bits of the MAC and IPv6 address, the convention seems to be to use the last 24 bits from the internally assigned IPv4 address. However, the first 8 of these are 
    configurable through the `DESECSTACK_IPV4_REAR_PREFIX16` variable. Since we don't want public IPv6 addresses to change if the internal IPv4 net prefix changes, we use 
    `0x10` for bits at position 24--17. We thus arrive at the subnet 2a01:4f8:a0:12eb:deec:642:ac10:0/108 for our public IPv6-enabled Docker containers. The last 16 bits 
    of the IPv6 address we indeed take from the internally assigned IP address. The same procedure is used to set the MAC address of IPv6 containers (they begin with 
    `06:42:ac:10:`).

    All other traffic in the /80 subnet is unexpected and therefore rejected. This includes traffic for IPv6 addresses that Docker assigns. (If Docker uses the MAC address 
    for this purpose, the prefix is 02:42:ac which is not part of our public network, so we're safe.)

    Since the above topology is strictly determined by the /80 prefix and the MAC address, we hope that most of the hardcoding can be removed in the future.

  - Docker currently exposes IPv6-capable containers fully, without restriction. Therefore, it is necessary to set up a firewall, like (`ip6tables`)

        -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
        -A FORWARD -d 2a01:4f8:a0:12eb:deec:642:ac10:0/108 -i eth0 -j ACCEPT
        -A FORWARD -d 2a01:4f8:a0:12eb:deec::/80 -i eth0 -j REJECT --reject-with icmp6-port-unreachable

Development: Getting Started Guide
----------------------------------

As desec-stack utilizes a number of different technologies and software packages, it requires some effort to setup a stack ready for development.
While there are certainly many ways to get started hacking desec-stack, here is one way to do it.

1. **Requirements.** This guide is intended and tested on Ubuntu 20.20.
    However, many other Linux distributions will also do fine.
    For desec-stack, [docker](https://docs.docker.com/install/linux/docker-ce/ubuntu/) and [docker-compose](https://docs.docker.com/compose/install/) are required.
    Further tools that are required to start hacking are git and curl.
    Recommended, but not strictly required for desec-stack development is to use certbot along with Let's Encrypt and PyCharm.
    jq, httpie, libmariadbclient-dev, libpq-dev, python3-dev (>= 3.8) and python3-venv (>= 3.8) are useful if you want to follow this guide.
    The webapp requires nodejs. To install everything you need for this guide except docker and docker-compose, use

       sudo apt install certbot curl git httpie jq libmariadbclient-dev libpq-dev nodejs npm python3-dev python3-venv libmemcached-dev

1. **Get the code.** Clone this repository to your favorite location.

       git clone git@github.com:desec-io/desec-stack.git

1. **Obtain Domain Names.** To run desec-stack, this guide uses a subdomain of dedyn.io provided by desec.io.

    1. Register a deSEC user account. Check out the instructions in our [documentation](https://desec.readthedocs.io/),
       in particular the [Quickstart](https://desec.readthedocs.io/en/latest/quickstart.html) section.

    2. Register a dedyn.io subdomain to run your desec-stack on it and set up the IP addresses.
        For this guide, we assume `example.dedyn.io`. Register it with:

           DOMAIN=example.dedyn.io
           http POST https://desec.io/api/v1/domains/ Authorization:"Token ${TOKEN}" name:='"'${DOMAIN}'"'

        If you receive an answer that is different from status code 201, chances are that the name you chose is already taken by someone else.
        In that case, repeat the last step with a new name.
        To setup the necessary IP address records, we create a couple of A and AAAA records that point to localhost.
        As preparation, create a JSON file `dns.json` with the following content defining the DNS setup for desec-stack:

           [
               {"type": "A",    "ttl":300, "records": ["127.0.0.1"], "subname": "desec"},
               {"type": "AAAA", "ttl":300, "records": ["::1"],       "subname": "desec"},
               {"type": "A",    "ttl":300, "records": ["127.0.0.1"], "subname": "*.desec"},
               {"type": "AAAA", "ttl":300, "records": ["::1"],       "subname": "*.desec"},

               {"type": "A",    "ttl":300, "records": ["127.0.0.1"], "subname": "dedyn"},
               {"type": "AAAA", "ttl":300, "records": ["::1"],       "subname": "dedyn"},
               {"type": "A",    "ttl":300, "records": ["127.0.0.1"], "subname": "*.dedyn"},
               {"type": "AAAA", "ttl":300, "records": ["::1"],       "subname": "*.dedyn"}
           ]

        We use the deSEC API to publish the DNS information as defined in `dns.json`:

           http POST https://desec.io/api/v1/domains/${DOMAIN}/rrsets/ Authorization:"Token ${TOKEN}" < dns.json

1. **Obtain certificates.** desec-stack requires SSL certificates for the above-mentioned `desec` and `dedyn` hostnames as well as for various subdomains.
    (For a complete list, see `www/README.md`.)
    While we recommend to obtain signed certificates from Let's Encrypt, it's also possible to let desec-stack generate self-signed certificates on startup
    by just skipping this step. To use the deSEC certbot hook, first download it to an appropriate location and set up your credentials and domain name.

       mkdir -p ~/bin
       cd ~/bin
       curl https://raw.githubusercontent.com/desec-io/desec-certbot-hook/main/hook.sh > desec_certbot_hook.sh
       touch .dedynauth; chmod 600 .dedynauth
       echo DEDYN_TOKEN=${TOKEN} >> .dedynauth
       echo DEDYN_NAME=${DOMAIN} >> .dedynauth
       chmod +x desec_certbot_hook.sh

    Now we use certbot to obtain certificates, using the DNS challenge for authentication.

       certbot \
           --config-dir certbot/config --logs-dir certbot/logs --work-dir certbot/work \
           --manual --text --preferred-challenges dns \
           --manual-auth-hook ~/bin/desec_certbot_hook.sh \
           --manual-cleanup-hook ~/bin/desec_certbot_hook.sh \
           --server https://acme-v02.api.letsencrypt.org/directory \
           -d "*.${DOMAIN}" -d "update.dedyn.${DOMAIN}" -d "update4.dedyn.$DOMAIN" -d "update6.dedyn.$DOMAIN" \
           -d "checkip.dedyn.${DOMAIN}" -d "checkipv4.dedyn.${DOMAIN}" -d "checkipv6.dedyn.${DOMAIN}" \
           certonly

    Note that the definition of config, logs and work dir are only necessary if you do not want to run certbot as root.
    Verifying the DNS challenge takes a while, so allow this command to take a couple of minutes.
    After successfully retrieving the certificate, you can find them in `certbot/config/live/$DOMAIN/`.
    To make them available to desec-stack (in the default location), we copy certificate and keys.
    In the project root directory,

       mkdir certs
       cd certs
       for SUBNAME in desec www.desec get.desec checkip.dedyn checkipv4.dedyn checkipv6.dedyn dedyn www.dedyn update.dedyn update6.dedyn
       do
           ln -s cer ${SUBNAME}.${DOMAIN}.cer
           ln -s key ${SUBNAME}.${DOMAIN}.key
       done

       cp ~/bin/certbot/config/live/${DOMAIN}/fullchain.pem cer
       cp ~/bin/certbot/config/live/${DOMAIN}/privkey.pem key

    The last two steps need to be repeated whenever the certificates are renewed.
    While any location for the certificates is fine, the `certs/` folder is configured to be ignored by git so that private keys do not accidentally end up being committed.

1. **Configure desec-stack.** As docker-compose application, desec-stack is configured by environment variables defined in the `.env` file in the project root directory.
    Because it contains sensitive information for each deployment, `.env` is not part of the repository and ignored by git.
    However, we ship `.env.default` and `.env.dev` with templates for production and development, respectively.
    `.env.dev` is almost good enough for a basic development system, so let's use that as a basis:

       sed "s/^DESECSTACK_DOMAIN=.*/DESECSTACK_DOMAIN=${DOMAIN}/" .env.dev > .env

    Optionally, edit the file and
    1. configure an email server host name, user name, and password to deliver emails can be included in `.env`. A convenient option is a MailTrap account.
    2. adjust the network prefixes in `.env` to avoid collisions with other local networks.

    Additionally, the VPN server for the replication network needs to be equipped with a pre-shared key (PSK) and a public key infrastructure (PKI).
    To generate the PSK, use the openvpn-server container:

        docker-compose build openvpn-server && docker-compose run openvpn-server openvpn --genkey --secret /dev/stdout > openvpn-server/secrets/ta.key

    To build the PKI, we recommend [easy RSA](https://github.com/OpenVPN/easy-rsa).
    **Please note that PKI instructions here are for development deployments only!**
    **Using this setup for production WILL DEFINITELY result in an INSECURE deployment!**
    To make it available, clone the repository and link to the executable:

        cd openvpn-server/secrets
        git clone https://github.com/OpenVPN/easy-rsa.git
        ln -s easy-rsa/easyrsa3/easyrsa

    In order to create a new PKI,

        ./easyrsa init-pki
        ./easyrsa build-ca nopass

    To make the new PKI's Certificate Authority available to the OpenVPN server,

        ln -s pki/ca.crt

    To issue a certificate for the OpenVPN server, generate a new key pair, a signing request, and sign the certificate.

         ./easyrsa gen-req server nopass
         ./easyrsa sign-req server server  # requires interaction

    Make the key and certificate available to OpenVPN server:

        ln -s pki/issued/server.crt
        ln -s pki/private/server.key

    As the setup of OpenVPN is completed, return to the project directory:

        cd -

1. **Install webapp dependencies.** To install the dependencies for the web site and GUI, run

       cd webapp/
       npm install
       cd -

1. **Run desec-stack.** To run desec-stack, use

       ./dev

    If you run desec-stack for the first time, this will require a couple of downloads and take a while.
    Once it is up and running, you can query the API home endpoint:

       http GET https://desec.${DOMAIN}/api/v1/

    Congratulations, you have desec-stack up and running.
    Of course, as this setup is only on your local machine, DNS information will not be published into the public DNS.
    However, the desec-stack nameserver is available on localhost port 5321.
    To check if desec-stack is working as expected, you can query the desec-stack nameserver locally for any information that you saved using your API.

       EMAIL=john@example.com
       PASSWORD=insecure
       # Register account (https://desec.readthedocs.io/en/latest/quickstart.html). Hint: In dev mode, the captcha response contains the plaintext challenge.
       TOKEN=$(http POST https://desec.${DOMAIN}/api/v1/auth/login/ email:=\"${EMAIL}\" password:=\"${PASSWORD}\" | jq -r .token)
       http POST https://desec.${DOMAIN}/api/v1/domains/ Authorization:"Token ${TOKEN}" name:='"test.example"'
       http POST https://desec.${DOMAIN}/api/v1/domains/test.example/rrsets/ Authorization:"Token ${TOKEN}" type:=\"A\" ttl:=60 records:='["127.0.0.254"]'

    After registering a user with your API, creating a domain and publishing some info to the DNS, use

       dig @localhost -p 5321 test.example 

    to see if the nameserver is behaving as expected.

1. **(Optional) Configure PyCharm for API Development.** As a docker-compose application, desec-stack takes a while to start.
    Additionally, it is hard to connect a debugger to the docker containers.
    Our recommended solution is to develop the API using Django tests running outside the docker-compose application.
    This will dramatically decrease the time required for running the Django tests and enable just-in-time debugging in PyCharm.
    Also, it will enable you to browse dependencies code within PyCharm and thus ease debugging.

    1. To get started, we create a virtual python environment that (to some extend) mimics the python environment in the docker container.
        In the project root,

           cd api
           python3 -m venv venv
           source venv/bin/activate
           pip install wheel
           pip install -r requirements.txt

    1. At this point, Django is ready to run in the virtual environment created above.
        There are two things to consider when running Django outside the container.
        First, the environment variables as defined in the `.env` file need to be made available in the shell.
        This can be done with

           set -a && source ../.env && set +a

        Second, to make the tests run efficiently, a couple of settings are different from the production system:
        passwords are hashed using a fast (but insecure!) method, rate limits are switched off, and so on.
        To use the fast settings in your shell, run

           export DJANGO_SETTINGS_MODULE=api.settings_quick_test

        Third, the API needs a postgres database to run the tests. To serve as a test database,
        the `dbapi` container can be started using a test configuration which exposes the database at
        `127.0.0.1`. In order to let Django know that the database is at `127.0.0.1` instead of the
        usual `dbapi`, set an additional environment variable:

           export DESECSTACK_DJANGO_TEST=1

        Fourth, run the database:

           docker-compose -f docker-compose.yml -f docker-compose.test-api.yml up -d dbapi

        Finally, you can manage Django using the `manage.py` CLI.
        As an example, to run the tests, use

           python3 manage.py test

    1. Open the project root directory `desec-stack` in PyCharm and select File › Settings.
        1. In Project: desec-stack › Project Structure, mark the `api/` folder as a source folder.
        2. In Project: desec-stack › Project Interpreter, add a new interpreter. Choose "existing environment" and select `api/venv/bin/python3` from the project root.
        3. In Languages & Frameworks › Django, enable the Django support and set the Django project root to `api/`.

    1. From the PyCharm menu, select Run › Edit Configurations and click on "Edit configuration templates"; select the "Django tests" template from the list.
        1. Open the Environment Variables dialog. Copy the contents of the `.env` file and paste it here.
        2. Add an environment variable with the name `DESECSTACK_DJANGO_TEST` and the value `1`.
        3. Fill the Custom Settings field with the path to the `settings_quick_test` module.
        4. At the bottom in the "Before launch" sections, add an "External tool" with the following settings:
           - Name: `Postgres Test Container`
           - Program: `docker-compose`
           - Arguments: `-f docker-compose.yml -f docker-compose.test-api.yml up -d dbapi`

    1. To see if the test configuration is working, right click on the api folder in the project view and select Run Test.
       (Note that the first attempt may fail in case the `dbapi` container does not start up fast enough. In that case, just try again.)

    1. To use code inspection, click on Inspect Code… in PyCharm's Code menu and add a local custom scope with the following pattern:

           file:api//*.py&&!file:api/venv//*&&!file:api/manage.py&&!file:api/api/wsgi.py&&!file:api/desecapi/migrations//*

    From this point on, you are set up to use most of PyCharm's convenience features.

    1. For PyCharm's Python Console, the environment variables of your `.env` file and `DJANGO_SETTINGS_MODULE=api.settings_quick_test` need to be configured in Settings › Build, Execution, Deployment › Console › Django Console. (Note that if you need to work with the database, you need to initialize it first by running all migrations; otherwise, the model tables will be missing from the database.)


## Debugging

### RabbitMQ

To access message queue information of RabbitMQ, use the RabbitMQ management plugin. First, port 15672 of the RabbitMQ
container needs to be exposed (default when using `docker-compose.dev.yml`). Then, inside the container, create a user
that can access the RabbitMQ data:

```
rabbitmq-plugins enable rabbitmq_management
rabbitmqctl add_user admin admin
rabbitmqctl set_user_tags admin administrator
rabbitmqctl set_permissions admin '.*' '.*' '.*'
```

Then the web-based management interface will be available at http://localhost:15672 with user `admin` and password
`admin`.
