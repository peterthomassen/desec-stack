<template>
  <div>
    <!-- Error Snackbar -->
    <v-snackbar
      v-model="snackbar"
      color="error"
      multi-line
      vertical
      :timeout="-1"
    >
      {{ errors[errors.length - 1] }}
      <v-btn @click="snackbar = false">
        Close
      </v-btn>
    </v-snackbar>

    <!-- The Actual Table -->
    <v-data-table
            :headers="headers"
            :item-class="itemClass"
            :items="rows"
            :search="search"
            :custom-filter="filterSearchableCols"
            :loading="$store.getters.working || createDialogWorking || destroyDialogWorking"
            class="elevation-1"
            @click:row="rowClick"
    >
      <template slot="top">
        <!-- Headline & Toolbar, Including New Form -->
        <v-toolbar flat>
          <v-toolbar-title>{{ headlines.table }}</v-toolbar-title>
          <v-spacer />
          <v-text-field
                  v-model="search"
                  v-if="$vuetify.breakpoint.smAndUp"
                  append-icon="mdi-magnify"
                  label="Search"
                  single-line
                  hide-details
          />
          <v-spacer v-if="Object.keys(writeableAdvancedColumns).length > 0"/>
          <v-switch
              v-model="showAdvanced"
              v-if="Object.keys(writeableAdvancedColumns).length > 0"
              label="Show advanced settings"
              class="mt-6"
          />
          <v-spacer />
          <v-btn
                  id="create"
                  color="primary"
                  dark
                  small
                  fab
                  depressed
                  :disabled="$store.getters.working"
          >
            <v-icon>mdi-plus</v-icon>
          </v-btn>
          <template v-slot:extension v-if="$vuetify.breakpoint.xsOnly">
            <v-text-field
                    v-model="search"
                    append-icon="mdi-magnify"
                    label="Search"
                    single-line
                    hide-details
            />
          </template>
          <v-dialog
                  v-if="createable"
                  v-model="createDialog"
                  activator="#create"
                  max-width="500px"
                  persistent
                  @keydown.esc="close"
          >
            <v-card>
              <v-form v-model="valid" @submit.prevent="save()">
                <v-card-title>
                  <span class="headline">{{ headlines.create }}</span>
                  <v-spacer />
                  <v-icon @click.stop="close">
                    mdi-close
                  </v-icon>
                </v-card-title>
                <v-divider />
                <v-progress-linear
                        v-if="createDialogWorking"
                        height="2"
                        :indeterminate="true"
                />

                <v-alert
                        :value="createDialogError"
                        type="error"
                        style="overflow: auto"
                >
                  {{ errors[errors.length - 1] }}
                </v-alert>

                <v-alert
                        :value="createDialogSuccess"
                        type="success"
                        style="overflow: auto"
                >
                  <span v-html="texts.createSuccess(createDialogItem)"></span>
                </v-alert>

                <v-alert
                        :value="!!texts.createWarning(destroyDialogItem)"
                        type="warning"
                >
                  {{ texts.createWarning(createDialogItem) }}
                </v-alert>

                <v-card-text v-if="createDialog">
                  <!-- v-if required here to make autofocus below working for the 2nd+ times, cf stackoverflow.com/a/51476992 -->
                  <span v-html="texts.create()"></span>
                  <!-- New Form -->
                  <component
                          :is="c.datatype"
                          v-for="(c, id) in writeableStandardColumns"
                          :key="id"
                          v-model="createDialogItem[c.value]"
                          v-bind="c.fieldProps ? c.fieldProps(createDialogItem) : {}"
                          :label="c.textCreate || c.text"
                          :error-messages="c.createErrors"
                          :required="c.required || false"
                          :disabled="createInhibited || createDialogSuccess"
                          autofocus
                          @input="clearErrors(c)"
                  />

                    <v-expansion-panels
                        flat
                        v-if="Object.keys(writeableAdvancedColumns).length > 0"
                    >
                      <v-expansion-panel>
                        <v-expansion-panel-header class="primary lighten-5">
                          <span>Advanced settings</span>
                        </v-expansion-panel-header>
                        <v-expansion-panel-content>
                          <component
                                  :is="c.datatype"
                                  v-for="(c, id) in writeableAdvancedColumns"
                                  :key="id"
                                  v-model="createDialogItem[c.value]"
                                  v-bind="c.fieldProps ? c.fieldProps(createDialogItem) : {}"
                                  :label="c.textCreate || c.text"
                                  :error-messages="c.createErrors"
                                  :required="c.required || false"
                                  :disabled="createInhibited || createDialogSuccess"
                                  autofocus
                                  @input="clearErrors(c)"
                          />
                        </v-expansion-panel-content>
                      </v-expansion-panel>
                    </v-expansion-panels>

                  <div class="mt-4" v-html="texts.createBottom()"></div>
                </v-card-text>

                <v-card-actions class="pb-4">
                  <v-spacer />
                  <v-btn
                          color="primary"
                          class="grow"
                          :outlined="!createDialogSuccess"
                          :disabled="createDialogWorking"
                          @click.native="close"
                  >
                    {{ createDialogSuccess ? 'Close' : 'Cancel' }}
                  </v-btn>
                  <v-btn
                          type="submit"
                          color="primary"
                          class="grow"
                          depressed
                          :disabled="createInhibited || !valid || createDialogWorking || createDialogSuccess"
                          :loading="createDialogWorking"
                          v-if="!createDialogSuccess"
                  >
                    Save
                  </v-btn>
                  <v-spacer />
                </v-card-actions>
              </v-form>
            </v-card>
          </v-dialog>
        </v-toolbar>
        <v-alert text type="info" v-if="texts.banner"><span v-html="texts.banner()"></span></v-alert>
      </template>

      <template
        v-for="(column, id) in columns"
        v-slot:[column.name]="itemFieldProps"
      >
        <component
          :is="column.datatype"
          :key="id"
          :readonly="column.readonly"
          :disabled="$store.getters.working || itemIsReadOnly(itemFieldProps.item)"
          v-model="itemFieldProps.item[column.value]"
          v-bind="column.fieldProps ? column.fieldProps(itemFieldProps.item) : {}"
          @keyup="keyupHandler"
          @dirty="dirty.add(itemFieldProps.item); dirtyError.delete(itemFieldProps.item);"
        />
      </template>
      <template v-slot:[`item.actions`]="itemFieldProps">
        <v-layout
                class="my-1 py-3"
                justify-end
        >
          <v-btn
                  v-for="action in actions"
                  :disabled="$store.getters.working || itemIsReadOnly(itemFieldProps.item)"
                  :key="action.key"
                  color="grey"
                  icon
                  @click.stop="action.go(itemFieldProps.item)"
          >
            <v-icon>{{ action.icon }}</v-icon>
          </v-btn>
          <v-btn
                  v-if="updatable"
                  :disabled="$store.getters.working || itemIsReadOnly(itemFieldProps.item)"
                  color="grey"
                  icon
                  @click.stop="save(itemFieldProps.item, $event)"
          >
            <v-icon>mdi-content-save-edit</v-icon>
          </v-btn>
          <v-btn
                  v-if="destroyable"
                  :disabled="$store.getters.working || itemIsReadOnly(itemFieldProps.item)"
                  color="grey"
                  class="hover-red"
                  icon
                  @click.stop="destroyAsk(itemFieldProps.item)"
          >
            <v-icon>mdi-delete</v-icon>
          </v-btn>
        </v-layout>
      </template>
      <template slot="no-data">
        <div class="py-4 text-xs-center">
          <h2 class="title">
            Feels so empty here!
          </h2>
          <p>No entries yet.</p>
        </div>
      </template>
    </v-data-table>

    <!-- Delete Dialog -->
    <v-dialog
      v-model="destroyDialog"
      max-width="500px"
      persistent
    >
      <v-card>
        <v-form @submit.prevent="destroy(destroyDialogItem)">
          <v-card-title>
            <span class="headline">{{ headlines.destroy }}</span>
          </v-card-title>

          <v-divider />
          <v-progress-linear
            v-if="destroyDialogWorking"
            height="2"
            :indeterminate="true"
          />

          <v-alert
                  :value="!!texts.destroyInfo(destroyDialogItem)"
                  type="info"
          >
            {{ texts.destroyInfo(destroyDialogItem) }}
          </v-alert>
          <v-alert
                  :value="!!texts.destroyWarning(destroyDialogItem)"
                  type="warning"
          >
            {{ texts.destroyWarning(destroyDialogItem) }}
          </v-alert>
          <v-alert
            :value="!!destroyDialogError"
            type="error"
          >
            {{ errors[errors.length - 1] }}
          </v-alert>

          <v-card-text>
            {{ texts.destroy(destroyDialogItem) }}
          </v-card-text>

          <v-card-actions>
            <v-spacer />
            <v-btn
              color="primary"
              class="grow"
              outlined
              :disabled="destroyDialogWorking"
              @click.native="destroyClose"
            >
              Cancel
            </v-btn>
            <v-btn
              color="primary"
              class="grow"
              depressed
              type="submit"
              :loading="destroyDialogWorking"
            >
              Delete
            </v-btn>
            <v-spacer />
          </v-card-actions>
        </v-form>
      </v-card>
    </v-dialog>
    <component
            :is="extraComponentName"
            v-bind="extraComponentBind"
            @input="() => { this.extraComponentName = ''; }"
    ></component>
  </div>
</template>

<script>
import { HTTP, withWorking } from '@/utils';
import RRSetType from '@/components/Field/RRSetType';
import TimeAgo from '@/components/Field/TimeAgo';
import Checkbox from '@/components/Field/Checkbox';
import Code from '@/components/Field/Code';
import GenericText from '@/components/Field/GenericText';
import Record from '@/components/Field/Record';
import RecordList from '@/components/Field/RecordList';
import Switchbox from '@/components/Field/Switchbox';
import TTL from '@/components/Field/TTL';
import MultilineText from "@/components/Field/MultilineText";

const filter = function (obj, predicate) {
  const result = {};
  let key;
  for (key in obj) {
    if (Object.prototype.hasOwnProperty.call(obj, key) && predicate(obj[key])) {
      result[key] = obj[key];
    }
  }

  return result;
};

// safely access deeply nested objects
const safeget = (path, object) => path.reduce((xs, x) => ((xs && xs[x]) ? xs[x] : null), object);

export default {
  name: 'CrudList',
  components: {
    RRSetType,
    TimeAgo,
    Switchbox,
    Checkbox,
    Code,
    GenericText,
    Record,
    RecordList,
    TTL,
    MultilineText,
  },
  data() { return {
    createDialog: false,
    createDialogWorking: false,
    createDialogIndex: null,
    createDialogItem: {},
    createDialogError: false,
    createDialogSuccess: false,
    destroyDialog: false,
    destroyDialogWorking: false,
    destroyDialogItem: {},
    destroyDialogIndex: null,
    destroyDialogError: false,
    errors: [],
    extraComponentName: '',
    extraComponentBind: {},
    fullWidth: false,
    snackbar: false,
    showAdvanced: false,
    search: '',
    rows: [],
    valid: false,
    dirty: new Set(),
    dirtyError: new Set(),
    /* to be overwritten */
    // features
    createable: true,
    updatable: false,
    destroyable: true,
    // optics
    headlines: {
      table: 'Crud List',
      create: 'New Object',
      destroy: 'Delete Object',
    },
    texts: {
      banner: undefined,
      create: () => ('Create a new object.'),
      createBottom: () => undefined,
      createSuccess: () => undefined,
      createWarning: () => (false),
      destroy: () => ('Delete an object permanently. This operation can likely not be undone.'),
      destroyInfo: () => (false),
      destroyWarning: () => (false),
    },
    columns: {},
    actions: [],
    // resource
    paths: {
      list: 'needs/to/be/overwritten/',
      create: 'needs/to/be/overwritten/',
      delete: 'needs/to/be/overwritten/',
      update: 'needs/to/be/overwritten/',
    },
    // object
    itemDefaults: () => ({}),
    // callbacks
    itemIsReadOnly: () => false,
    postcreate: this.close,
    precreate: () => undefined,
    preupdate: () => undefined,
    keyupHandler: (e) => {
      // Intercept Enter key
      if (e.keyCode === 13) {
        // Submit
        document.activeElement.blur();
        e.target.closest('tr').querySelector('.mdi-content-save-edit').closest('button').click();
      }
    },
    handleRowClick: () => {},
  }},
  computed: {
    createInhibited: () => false,
    headers() {
      let cols = Object.values(Object.assign({}, this.columns)); // (shallowly) copy cols and convert to array
      if (!this.showAdvanced) {
        cols = cols.filter(col => !(col.advanced || false));
      }
      cols.push({
        text: 'Actions',
        sortable: false,
        align: 'right',
        value: 'actions',
        width: '130px',
      });
      return cols; // data table expects an array
    },
    writeableStandardColumns() {
      return this.filterWriteableColumns(col => !(col.advanced || false));
    },
    writeableAdvancedColumns() {
      return this.filterWriteableColumns(col => (col.advanced || false));
    },
  },
  async created() {
    const self = this;
    const url = self.resourcePath(self.paths.list, self.$route.params, '::');
    await withWorking(this.error, () => HTTP
            .get(url)
            .then(r => self.rows = r.data)
    );
    this.createDialogItem = Object.assign({}, this.itemDefaults());
  },
  methods: {
    itemClass(item) {
      if (this.itemIsReadOnly(item)) {
        return 'grey text--disabled grey lighten-4';
      }
      if (this.dirtyError.has(item)) {
        return 'red lighten-5';
      }
      if (this.dirty.has(item)) {
        return 'orange lighten-5';
      }
      return '';
    },
    filterWriteableColumns(callback) {
      const columns = filter(this.columns, c => !c.readonly || c.writeOnCreate);
      return filter(columns, callback);
    },
    clearErrors(c) {
      c.createErrors = [];
    },
    rowClick(value) {
      this.handleRowClick(value);
    },
    /** *
     * Ask the user to delete the given item.
     * @param item
     */
    destroyAsk(item) {
      this.destroyDialogIndex = this.rows.indexOf(item);
      this.destroyDialogItem = item;
      this.destroyDialog = true;
    },
    /** *
     * Delete an item from table and server.
     * Errors are handeled by calling the error function.
     * On success, the destroy dialog will be closed (if opened)
     * @param item
     */
    async destroy(item) {
      this.destroyDialogWorking = true;
      this.destroyDialogError = null;
      const url = this.resourcePath(
              this.resourcePath(this.paths.delete, this.$route.params, '::'),
              item, ':',
      );
      const r = await withWorking(this.error, () => HTTP.delete(url));
      if (r) {
        this.rows.splice(this.rows.indexOf(item), 1);
        this.destroyClose();
      }
      this.destroyDialogWorking = false;
    },
    /** *
     * Closes the destroy dialog and cleans up.
     */
    destroyClose() {
      this.destroyDialogIndex = null;
      this.destroyDialogItem = {};
      this.destroyDialog = false;
      this.destroyDialogError = null;
    },
    /** *
     * Save an edited or new item in table and server.
     * The item is given by this.dialogIndex and this.dialogItem.
     * Errors are handled by calling the error function.
     */
    async save(item, event) {
      for (const c in this.columns) {
        this.columns[c].createErrors = [];
      }
      const self = this;
      if (item) {
        // edit item
        let tr;
        if (event) {
          // TODO do not temper with the DOM directly -- bad things will happen (see commit msg)
          tr = event.target.closest('tr');
          tr.addEventListener("animationend", () => tr.classList.remove('successFade'), true);
          tr.classList.add('successFade');
        }
        this.preupdate(item);
        const url = this.resourcePath(
                this.resourcePath(this.paths.update, this.$route.params, '::'),
                item,
                ':',
        );
        await withWorking(this.error, () => HTTP
                .patch(url, item)
                .then(r => {
                  Object.assign(self.rows[self.rows.indexOf(item)], r.data);
                  self.dirty.delete(item);
                  self.dirtyError.delete(item);
                })
                .catch(function (error) {
                  self.dirtyError.add(item);
                  throw error;
                })
        );
      } else {
        // new item
        this.createDialogWorking = true;
        this.createDialogError = false;
        this.createDialogSuccess = false;
        this.precreate();
        const url = this.resourcePath(
                this.resourcePath(this.paths.create, this.$route.params, '::'),
                this.createDialogItem,
                ':',
        );
        const r = await withWorking(this.error, () => HTTP.post(url, self.createDialogItem))
        if (r) {
          this.createDialogItem = r.data;
          this.createDialogSuccess = true;
          const l = this.rows.push(r.data);
          this.postcreate(this.rows[l - 1]);
        }
      }
      this.createDialogWorking = false;
    },
    /** *
     * Close the dialog and clean up state.
     */
    close() {
      this.createDialog = false;
      this.createDialogItem = Object.assign({}, this.itemDefaults());
      this.createDialogIndex = null;
      this.createDialogError = false;
      this.createDialogSuccess = false;
      for (const c in this.columns) {
        this.columns[c].createErrors = [];
      }
    },
    /** *
     * Handle the error e by displaying it to the user.
     * @param e
     */
    error(e) {
      if (safeget(['response', 'data', 'detail'], e)) {
        e = e.response.data.detail;
      } else if (safeget(['response', 'data'], e)) {
        e = safeget(['response', 'data'], e);
      }
      if (!safeget(['response'], e) && safeget(['request'], e)) {
        e = `Cannot reach server at ${HTTP.baseURL ? HTTP.baseURL : window.location.hostname}. Are you offline?`;
      }
      this.errors.push(e);
      if (this.destroyDialog) {
        this.destroyDialogError = e;
      } else if (this.createDialog) {
        // see if e contains field-specific errors
        if (Object.keys(e).every(key => Object.prototype.hasOwnProperty.call(this.columns, key))) {
          // assume we obtained field-specific error(s),
          // so let's assign them to the input fields
          for (const c in e) {
            this.columns[c].createErrors = e[c];
          }
        } else {
          this.createDialogError = true;
        }
      } else {
        this.snackbar = true;
      }
    },
    /** *
     * Converts a URL template with parameters into a URL.
     * All colon-prefixed placeholders, enclosed in braces,
     * (e.g., ":{name}") in p are replaced with a value if
     * obj contains a property with the corresponding name.
     *
     * @param p URL template, like /api/users/:{id}/posts/
     * @param obj An object to take values from, like { id: 23, text: 'foo' }
     * @returns URL, like /api/users/23/posts/
     */
    resourcePath(p, obj, marker) {
      for (const property in obj) {
        if (Object.prototype.hasOwnProperty.call(obj, property)) {
          p = p.replace(`${marker}{${property}}`, obj[property]);
        }
      }
      return p;
    },
    filterRows(items, search, filter) {
      search = search.toString().toLowerCase();
      return items.filter(row => (
        Object.keys(this.columns).some(c => (this.columns[c].searchable && filter(row[c], search)))
      ));
    },
    filterSearchableCols (value, search) {
      // TODO only search searchable columns
      return value != null &&
              search != null &&
              typeof value !== 'boolean' &&
              value.toString().toLocaleLowerCase().indexOf(search.toLocaleLowerCase()) !== -1
    },
  },
};
</script>

<!-- Add "scoped" attribute to limit CSS to this component only -->
<style scoped>
  /* If this is on tr instead of td, it doesn't work for the first one */
  >>> tr.successFade td {
    animation: successFade 1s;
  }
  >>> tr.successFade:focus-within td {
    animation: none;
  }
  @keyframes successFade {
    from { background-color: forestgreen; }
  }
  >>> tr.orange .mdi-content-save-edit, >>> tr.red .mdi-content-save-edit {
    color: forestgreen;
  }
  >>> tr:focus-within :focus {
    background-color: #FFFFFF;
  }
  >>> tbody tr > :hover {
    cursor: pointer;
  }
  >>> tbody tr.text--disabled > :hover {
    cursor: auto;
  }
</style>
