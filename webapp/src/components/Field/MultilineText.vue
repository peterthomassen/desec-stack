<template>
  <v-textarea
    :label="label"
    :disabled="disabled || readonly"
    :error-messages="errorMessages"
    :value="value"
    :type="type || ''"
    :placeholder="required ? '' : '(optional)'"
    :hint="hint"
    persistent-hint
    :required="required"
    :rules="[v => !required || !!v || 'Required.']"
    @input="changed('input', $event)"
    @input.native="$emit('dirty', $event)"
    @keyup="changed('keyup', $event)"
  />
</template>

<script>
export default {
  name: 'MultilineText',
  props: {
    disabled: {
      type: Boolean,
      required: false,
    },
    errorMessages: {
      type: [String, Array],
      default: () => [],
    },
    hint: {
      type: String,
      default: '',
    },
    label: {
      type: String,
      required: false,
    },
    readonly: {
      type: Boolean,
      required: false,
    },
    required: {
      type: Boolean,
      default: false,
    },
    value: {
      type: [String, Number],
      required: false,
    },
    type: {
      type: String,
      required: false,
    },
  },
  methods: {
    changed(event, e) {
      this.$emit(event, e);
      this.$emit('dirty');
    },
  },
};
</script>

<style>
/* Removes dropdown icon from read-only select */
.v-application--is-ltr .v-text-field.v-input--is-disabled .v-input__append-inner {
  display: none;
}
/* remove underline from disabled text fields so they look like regular text */
:not(v-select).theme--light.v-text-field.v-input--is-disabled .v-input__slot::before {
  content: none;
}
/* display disabled text fields in normal color */
.theme--light.v-input--is-disabled input {
  color: rgba(0, 0, 0, 0.87);
}
</style>