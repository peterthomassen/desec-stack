<template>
  <v-app id="inspire">
    <v-navigation-drawer
            v-model="drawer"
            app
            right
            disable-resize-watcher
    >
      <v-list dense>
        <v-list-item
                v-for="(item, key) in menu"
                :key="key"
                link
                :to="{name: item.name}"
                :exact="true">
          <v-list-item-action>
            <v-icon>{{item.icon}}</v-icon>
          </v-list-item-action>
          <v-list-item-content>
            <v-list-item-title>
              {{item.text}}
              <v-icon :color="item.post_icon_color" class="text--darken-2" small v-if="item.post_icon">{{item.post_icon}}</v-icon>
            </v-list-item-title>
          </v-list-item-content>
        </v-list-item>
      </v-list>
    </v-navigation-drawer>

    <v-app-bar app class="white">
      <v-toolbar-title><router-link :to="{name: 'home'}">
        <v-img
                :src="require('./assets/logo.svg')"
                alt="deSEC Logo"
                eager
                contain
        ></v-img>
      </router-link></v-toolbar-title>
      <v-spacer/>
      <div class="d-none d-md-block">
        <span class="mx-2" v-for="(item, key) in menu" :key="key">
          <router-link
                  class="primary--text text--darken-2"
                  :to="{name: item.name}"
          >{{item.text}}</router-link>
          <v-icon :color="item.post_icon_color" class="ml-1 text--darken-1" small v-if="item.post_icon">{{item.post_icon}}</v-icon>
        </span>
      </div>
      <v-btn class="mx-4" color="primary" depressed :to="{name: 'signup', query: $route.query}" v-if="!$store.state.authenticated">Create Account</v-btn>
      <v-btn class="mx-4 mr-0" color="primary" depressed :to="{name: 'login'}" v-if="!$store.state.authenticated">Log In</v-btn>
      <v-btn class="mx-4 mr-0" color="primary" depressed outlined @click="logout" v-if="$store.state.authenticated">Log Out</v-btn>
      <v-app-bar-nav-icon class="d-md-none" @click.stop="drawer = !drawer" />
      <template v-slot:extension v-if="$store.state.authenticated">
        <v-tabs background-color="primary darken-1" fixed-tabs>
          <v-tab
            v-for="(item, key) in tabmenu"
            :key="key"
            :to="{name: item.name}"
          >
            {{ item.text }}
            <v-chip
                class="ml-2"
                v-if="item.beta"
                small
            >
              BETA
            </v-chip>
          </v-tab>
          <v-spacer></v-spacer>
          <v-menu
                  bottom
                  left
          >
            <template v-slot:activator="{ on }">
              <v-btn
                      text
                      class="align-self-center mr-4"
                      v-on="on"
              >
                more
                <v-icon right>mdi-menu-down</v-icon>
              </v-btn>
            </template>

            <v-list class="grey lighten-3">
              <v-list-item
                      v-for="(item, key) in tabmenumore"
                      :key="key"
                      :to="{name: item.name}"
              >
                {{ item.text }}
              </v-list-item>
            </v-list>
          </v-menu>
        </v-tabs>
      </template>
    </v-app-bar>

    <v-main>
      <v-banner v-for="alert in $store.state.alerts" :key="alert.id">
        <v-icon
          slot="icon"
          color="warning"
          size="36"
        >
          {{ alert.icon }}
        </v-icon>
        {{ alert.teaser }}
        <template v-slot:actions>
          <v-btn
            color="primary"
            depressed
            :href="alert.href"
            v-if="alert.href"
          >
            {{ alert.button || 'More' }}
          </v-btn>
          <v-btn
            color="primary"
            text
            @click="$store.commit('unalert', alert.id)"
          >
            Hide
          </v-btn>
        </template>
      </v-banner>
      <v-progress-linear
              :active="$store.getters.working"
              :indeterminate="$store.getters.working"
              fixed
              color="secondary"
              style="z-index: 3"
      ></v-progress-linear>
      <router-view/>
    </v-main>
    <v-footer
      class="d-flex flex-column align-stretch pa-0 white--text text--darken-1 elevation-12"
    >
      <div class="grey darken-3 d-sm-flex flex-row justify-space-between pa-4">
        <div class="pa-2">
          <b>deSEC e.V.</b>
        </div>
        <div class="d-sm-flex flex-row align-right py-2">
          <div class="px-2 grey--text text--darken-1">powered by <a class="grey--text" href="//securesystems.de/" style="text-decoration: none">SSE</a></div>
          <div class="px-2"><a href="//desec-status.net/">Service Status</a></div>
          <div class="px-2"><a href="//github.com/desec-io/desec-stack/">Source Code</a></div>
          <div class="px-2"><router-link :to="{name: 'terms'}">Terms of Use</router-link></div>
          <div class="px-2"><router-link :to="{name: 'privacy-policy'}">Privacy Policy (Datenschutzerklärung)</router-link></div>
          <div class="px-2"><router-link :to="{name: 'impressum'}">Legal Notice (Impressum)</router-link></div>
        </div>
      </div>
      <div class="grey darken-4 d-md-flex flex-row justify-space-between pa-6">
        <div>
          <p>{{email}}</p>
          <p>
            Kyffhäuserstraße 5<br/>
            10781 Berlin<br/>
            Germany
          </p>
        </div>
        <div>
          <p>
            Please <router-link :to="{name: 'donate'}">donate</router-link>!
            <v-icon color="red" class="text--darken-2" dense>mdi-heart</v-icon>
          </p>
          <p>
            European Bank Account:<br>
            IBAN: DE91&nbsp;8306&nbsp;5408&nbsp;0004&nbsp;1580&nbsp;59<br>
            BIC: GENODEF1SLR
          </p>
        </div>
        <div>
          <p>deSEC e.V. is registered as</p>
          <p>VR37525 at AG Berlin (Charlottenburg)</p>
        </div>
        <div>
          <p>Vorstand</p>
          <p class="white--text text--darken-2">
            Nils Wisiol<br/>
            Dr. Peter Thomassen<br/>
            Wolfgang Studier<br/>
          </p>
        </div>
      </div>
    </v-footer>
  </v-app>
</template>

<script>
import router from './router';
import {logout} from './utils';

export default {
  name: 'App',
  data: () => ({
    drawer: false,
    email: process.env.VUE_APP_EMAIL,
    menu: {
      'home': {
        'name': 'home',
        'icon': 'mdi-home',
        'text': 'Home',
      },
      'docs': {
        'name': 'docs',
        'icon': 'mdi-book-open-page-variant',
        'text': 'API Reference',
      },
      'roadmap': {
        'name': 'roadmap',
        'icon': 'mdi-road-variant',
        'text': 'Roadmap',
      },
      'talk': {
        'name': 'talk',
        'icon': 'mdi-forum-outline',
        'text': 'Talk',
      },
      'donate': {
        'name': 'donate',
        'icon': 'mdi-gift-outline',
        'text': 'Donate',
        'post_icon': 'mdi-heart',
        'post_icon_color': 'red',
      },
      'about': {
        'name': 'about',
        'icon': 'mdi-umbrella',
        'text': 'About',
      },
      'reset-password': {
        'name': 'reset-password',
        'icon': 'mdi-lock-reset',
        'text': 'Reset Account Password',
      },
    },
    tabmenu: {
      'domains': {
        'name': 'domains',
        'text': 'Domain Management',
      },
      'tokens': {
        'name': 'tokens',
        'text': 'Token Management',
      },
      'dane': {
        'name': 'dane',
        'text': 'DANE Management',
        'beta': true,
      }
    },
    tabmenumore: {
      'change-email': {
        'name': 'change-email',
        'text': 'Change Email Address',
      },
      'delete-account': {
        'name': 'delete-account',
        'text': 'Delete Account',
      },
    },
  }),
  methods: {
    async logout() {
      await logout();
      router.push({name: 'home'});
    }
  }
}
</script>
