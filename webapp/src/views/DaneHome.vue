<template>
  <v-container fluid="true">
    <v-row>
      <v-col class="flex-grow-0 flex-shrink-0">
        <v-card
            class="mx-auto"
            max-width="300"
            tile
        >
          <v-list disabled>
            <v-subheader>IDENTITIES</v-subheader>
            <v-list-item-group
                v-model="selectedItem"
                color="primary"
            >
              <v-list-item
                  v-for="(item, i) in types"
                  :key="i"
              >
                <v-list-item-icon>
                  <v-icon v-text="item.icon"></v-icon>
                </v-list-item-icon>
                <v-list-item-content>
                  <v-list-item-title v-text="item.name"></v-list-item-title>
                </v-list-item-content>
              </v-list-item>
            </v-list-item-group>
          </v-list>
        </v-card>
      </v-col>
      <v-col class="flex-grow-1">
        <t-l-s-identity-list/>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
</style>

<script>
import TLSIdentityList from "@/views/TLSIdentityList";

export default {
  name: 'dane',
  components: {TLSIdentityList},
  data: () => ({
    'types': [
      {'id': 'tls', 'rdtype': 'TLSA', 'name': 'TLS Keys'},
      {'id': 'smime', 'rdtype': 'SMIMEA', 'name': 'S/MIME Keys'},
      {'id': 'OPENPGP', 'rdtype': 'OPENPGPKEY', 'name': 'OPEN PGP Keys'},
      {'id': 'SSH', 'rdtype': 'SSHFP', 'name': 'SSH Fingerprints'},
    ]
  }),
}
</script>
