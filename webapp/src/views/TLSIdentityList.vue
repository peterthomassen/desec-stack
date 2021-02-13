<script>
import { HTTP, withWorking } from '@/utils';
import CrudList from './CrudList';

export default {
  name: 'TLSIdentityList',
  extends: CrudList,
  components: {
  },
  data() {
    return {
        createable: true,
        updatable: false,
        destroyable: true,
        headlines: {
          table: 'TLS Identities',
          create: 'Add an identity',
          destroy: 'Remove an identity',
        },
        texts: {
          banner: () => 'Publish your web servers\' cryptographic identity in the DNS by adding your server certificate(s) below.',
          create: () => `Adds a TLS identity.`,
          destroy: d => (`Remove TLS identity ${d.name}?`),
          destroyInfo: () => 'Removing this TLS identity may render your website unavailable users.',
        },
        columns: {
          name: {
            name: 'item.name',
            text: 'Name',
            textCreate: 'Enter identity name',
            align: 'left',
            sortable: true,
            value: 'name',
            readonly: true,
            required: false,
            writeOnCreate: true,
            datatype: 'GenericText',
            searchable: true,
          },
          cert: {
            name: 'item.certificate',
            text: 'Certificate',
            textCreate: 'Paste certificte in PEM format',
            align: 'left',
            sortable: true,
            value: 'certificate',
            readonly: true,
            required: true,
            writeOnCreate: true,
            datatype: 'MultilineText',
            searchable: false,
          },
          fingerprint: {
            name: 'item.fingerprint',
            text: 'Fingerprint',
            algin: 'left',
            sortable: true,
            value: 'fingerprint',
            readonly: true,
            datatype: 'GenericText',
          },
          not_valid_before: {
            name: 'item.not_valid_before',
            text: 'Begin Validity',
            algin: 'left',
            sortable: true,
            value: 'not_valid_before',
            readonly: true,
            datatype: 'TimeAgo',
          },
          not_valid_after: {
            name: 'item.not_valid_after',
            text: 'Expiration',
            algin: 'left',
            sortable: true,
            value: 'not_valid_after',
            readonly: true,
            datatype: 'TimeAgo',
          },
          subject_names: {
            name: 'item.subject_names',
            text: 'Subject Names',
            algin: 'left',
            sortable: true,
            value: 'subject_names',
            readonly: true,
            datatype: 'MultilineText',
          },
          records_in: {
            name: 'item.published_at',
            text: 'published at',
            algin: 'left',
            sortable: true,
            value: 'published_at',
            readonly: true,
            datatype: 'MultilineText',
          },
          created: {
            name: 'item.created',
            text: 'Created',
            align: 'left',
            sortable: true,
            value: 'created',
            readonly: true,
            datatype: 'TimeAgo',
            searchable: false,
          },
        },
        actions: [
          // {
          //   key: 'info',
          //   go: d => this.showDomainInfo(d),
          //   icon: 'mdi-information',
          // },
        ],
        paths: {
          list: 'identities/tls/',
          create: 'identities/tls/',
          delete: 'identities/tls/:{id}',
        },
        itemDefaults: () => ({ name: '' }),
        postcreate: d => {
          this.close();
          this.showDomainInfo(d, true);
        },
        async showDomainInfo(d, isNew = false) {
          const url = this.resourcePath(this.paths.delete, d, ':');
          if (d.keys === undefined) {
            await withWorking(this.error, () => HTTP
                .get(url)
                .then(r => {
                  d.keys = r.data.keys;
                })
            );
          }
          let ds = d.keys.map(key => key.ds);
          ds = ds.concat.apply([], ds)
          let dnskey = d.keys.map(key => key.dnskey);
          this.extraComponentBind = {'domain': d.name, 'ds': ds, 'dnskey': dnskey, 'is-new': isNew};
          this.extraComponentName = 'DomainSetupDialog';
        },
        handleRowClick: (value) => {
          console.log(value);
          // this.$router.push({name: 'domain', params: {domain: value.name}});
        },
    }
  },
  computed: {
  },
};
</script>
