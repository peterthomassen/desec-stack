from datetime import timedelta
from socket import gethostbyname
from time import sleep

from django.conf import settings
from django.core.mail import get_connection, mail_admins
from django.core.management import BaseCommand
from django.utils import timezone
import dns.exception, dns.message, dns.query, dns.rdatatype

from desecapi import pdns
from desecapi.models import Domain


def query_serial(zone, server):
    """
    Checks a zone's serial on a server.
    :return: serial if received; None if the server did not know; False on error
    """
    query = dns.message.make_query(zone, 'SOA')
    try:
        response = dns.query.tcp(query, server, timeout=5)
    except dns.exception.Timeout:
        return False

    for rrset in response.answer:
        if rrset.rdtype == dns.rdatatype.SOA:
            return int(rrset[0].serial)
    return None


class Command(BaseCommand):
    help = 'Check secondaries for consistency with nsmaster.'

    def __init__(self, *args, **kwargs):
        self.servers = {gethostbyname(server): server for server in settings.WATCHDOG_SECONDARIES}
        super().__init__(*args, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument('domain-name', nargs='*',
                            help='Domain name to check. If omitted, will check all recently published domains.')
        parser.add_argument('--delay', type=int, default=120, help='Delay SOA checks to allow pending AXFRs to finish.')
        parser.add_argument('--window', type=int, default=settings.WATCHDOG_WINDOW_SEC,
                            help='Check domains that were published no longer than this many seconds ago.')

    def find_outdated_servers(self, zone, local_serial):
        """
        Returns a dict, the key being the outdated secondary name, and the value being the node's current zone serial.
        """
        outdated = {}
        for server in self.servers:
            remote_serial = query_serial(zone, server)
            if not remote_serial or remote_serial < local_serial:
                outdated[self.servers[server]] = remote_serial

        return outdated

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(seconds=options['window'])
        recent_domain_names = Domain.objects.filter(published__gt=threshold).values_list('name', flat=True)
        serials = {zone: s for zone, s in pdns.get_serials().items() if zone.rstrip('.') in recent_domain_names}

        if options['domain-name']:
            serials = {zone: serial for zone, serial in serials.items() if zone.rstrip('.') in options['domain-name']}

        print('Sleeping for {} seconds before checking {} domains ...'.format(options['delay'], len(serials)))
        sleep(options['delay'])

        outdated_zone_count = 0
        outdated_secondaries = set()

        output = []
        timeouts = {}
        for zone, local_serial in serials.items():
            outdated_serials = self.find_outdated_servers(zone, local_serial)
            for server, serial in outdated_serials.items():
                if serial is False:
                    timeouts.setdefault(server, [])
                    timeouts[server].append(zone)
            outdated_serials = {k: serial for k, serial in outdated_serials.items() if serial is not False}

            if outdated_serials:
                outdated_secondaries.update(outdated_serials.keys())
                output.append(f'{zone} ({local_serial}) is outdated on {outdated_serials}')
                print(output[-1])
                outdated_zone_count += 1
            else:
                print(f'{zone} ok')

        output.append(f'Checked {len(serials)} domains, {outdated_zone_count} were outdated.')
        print(output[-1])

        self.report(outdated_secondaries, output, timeouts)

    def report(self, outdated_secondaries, output, timeouts):
        if not outdated_secondaries and not timeouts:
            return

        subject = f'{timeouts and "CRITICAL ALERT" or "ALERT"} {len(outdated_secondaries)} secondaries out of sync'
        message = ''

        if timeouts:
            message += f'The following servers had timeouts:\n\n{timeouts}\n\n'

        if outdated_secondaries:
            message += f'The following {len(outdated_secondaries)} secondaries are out of sync:\n'
            for outdated_secondary in outdated_secondaries:
                message += f'* {outdated_secondary}\n'
            message += '\n'

        message += f'Current secondary IPs: {self.servers}\n'
        message += '\n'.join(output)

        mail_admins(subject, message, connection=get_connection('django.core.mail.backends.smtp.EmailBackend'))
