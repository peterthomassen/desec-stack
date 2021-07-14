FROM ubuntu:bionic

RUN apt-get update && apt-get install -y \
		dnsutils \
		iptables \
		net-tools \
		dirmngr gnupg \
	--no-install-recommends && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN echo 'deb [arch=amd64] http://repo.powerdns.com/ubuntu bionic-auth-45 main' \
      >> /etc/apt/sources.list \
 && echo 'Package: pdns-*' \
      > /etc/apt/preferences.d/pdns \
 && echo 'Pin: origin repo.powerdns.com' \
      >> /etc/apt/preferences.d/pdns \
 && echo 'Pin-Priority: 600' \
      >> /etc/apt/preferences.d/pdns

RUN set -ex \
	&& apt-key adv --keyserver keyserver.ubuntu.com --recv 0x1B0C6205FD380FBB \
	&& apt-get update \
	&& apt-get install -y pdns-server pdns-backend-mysql \
	# credentials management via envsubst
	&& apt-get -y install gettext-base \
	# VPN route
	&& apt-get -y install iproute2 \
	&& apt-get clean \
	&& rm -rf /var/lib/apt/lists/*

RUN rm -rf /etc/powerdns/
COPY conf/ /etc/powerdns/

COPY ./entrypoint.sh /root/

CMD ["/root/entrypoint.sh"]
