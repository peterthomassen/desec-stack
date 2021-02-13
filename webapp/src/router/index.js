import Vue from 'vue'
import VueRouter from 'vue-router'
import Home from '../views/Home.vue'
import {HTTP, logout} from "../utils";
import Login from "../views/Login";
import store from '../store';

Vue.use(VueRouter)

const routes = [
  {
    path: '/',
    name: 'home',
    component: Home
  },
  {
    path: '/signup/:email?',
    name: 'signup',
    // route level code-splitting
    // this generates a separate chunk (about.[hash].js) for this route
    // which is lazy-loaded when the route is visited.
    component: () => import(/* webpackChunkName: "signup" */ '../views/SignUp.vue')
  },
  {
    path: '/custom-setup/:domain',
    name: 'customSetup',
    component: () => import(/* webpackChunkName: "signup" */ '../views/DomainSetupPage'),
    props: true,
  },
  {
    path: '/dyn-setup/:domain',
    alias: '/dynsetup/:domain',
    name: 'dynSetup',
    component: () => import(/* webpackChunkName: "signup" */ '../views/DynSetup.vue')
  },
  {
    path: '/welcome/:domain?',
    name: 'welcome',
    component: () => import(/* webpackChunkName: "signup" */ '../views/Welcome.vue')
  },
  {
    path: '//desec.readthedocs.io/',
    name: 'docs',
    beforeEnter(to) { location.href = to.path },
  },
  {
    path: '//talk.desec.io/',
    name: 'talk',
    beforeEnter(to) { location.href = to.path },
  },
  {
    path: '/confirm/:action/:code',
    name: 'confirmation',
    component: () => import(/* webpackChunkName: "signup" */ '../views/Confirmation.vue')
  },
  {
    path: '/reset-password/:email?',
    name: 'reset-password',
    component: () => import(/* webpackChunkName: "account" */ '../views/ResetPassword.vue')
  },
  {
    path: '/change-email/:email?',
    name: 'change-email',
    component: () => import(/* webpackChunkName: "account" */ '../views/ChangeEmail.vue'),
    meta: {guest: false},
  },
  {
    path: '/delete-account/',
    name: 'delete-account',
    component: () => import(/* webpackChunkName: "account" */ '../views/DeleteAccount.vue'),
    meta: {guest: false},
  },
  {
    path: '/donate/',
    name: 'donate',
    component: () => import('../views/Donate.vue')
  },
  {
    path: '//github.com/desec-io/desec-stack/projects?query=is%3Aopen+sort%3Aname-asc',
    name: 'roadmap',
    beforeEnter(to) { location.href = to.path },
  },
  {
    path: '/impressum/',
    name: 'impressum',
    component: () => import('../views/Impressum.vue')
  },
  {
    path: '/privacy-policy/',
    name: 'privacy-policy',
    component: () => import('../views/PrivacyPolicy.vue')
  },
  {
    path: '/terms/',
    name: 'terms',
    component: () => import('../views/Terms.vue')
  },
  {
    path: '/about/',
    name: 'about',
    component: () => import('../views/About.vue')
  },
  {
    path: '/login',
    name: 'login',
    component: Login,
  },
  {
    path: '/tokens',
    name: 'tokens',
    component: () => import(/* webpackChunkName: "gui" */ '../views/TokenList.vue'),
    meta: {guest: false},
  },
  {
    path: '/domains',
    name: 'domains',
    component: () => import(/* webpackChunkName: "gui" */ '../views/DomainList.vue'),
    meta: {guest: false},
  },
  {
    path: '/domains/:domain',
    name: 'domain',
    component: () => import(/* webpackChunkName: "gui" */ '../views/Domain/CrudDomain.vue'),
    meta: {guest: false},
  },
  {
    path: '/dane',
    name: 'dane',
    component: () => import(/* webpackChunkName: "gui" */ '../views/DaneHome.vue'),
    meta: {guest: false},
  },
]

const router = new VueRouter({
  mode: 'history',
  base: process.env.BASE_URL,
  scrollBehavior (to, from) {
    // Skip if destination full path has query parameters and differs in no other way from previous
    if (from && Object.keys(to.query).length) {
      if (to.fullPath.split('?')[0] == from.fullPath.split('?')[0]) return;
    }
    return { x: 0, y: 0 }
  },
  routes
})

router.beforeEach((to, from, next) => {
  // see if there are credentials in the session store that we don't know of
  let recovered = false;
  if (sessionStorage.getItem('token') && !store.state.authenticated) {
    const token = JSON.parse(sessionStorage.getItem('token'))
    HTTP.defaults.headers.common['Authorization'] = 'Token ' + token.token;
    store.commit('login', token);
    recovered = true
  }

  if (to.matched.some(record => 'guest' in record.meta && record.meta.guest === false)) {
    // this route requires auth, check if logged in
    // if not, redirect to login page.
    if (!store.state.authenticated) {
      next({
        name: 'login',
        query: { redirect: to.fullPath }
      })
    } else {
      next()
    }
  } else {
    if (store.state.authenticated) {
      // Log in state was present, but not needed for the current page
      // User restored a previous session. If navigation to home, divert to home page for authorized users
      if (recovered && to.name == 'home') {
        next({name: 'domains'})
      } else {
        // user navigated to a page that doesn't require auth
        // to bias on the safe side we log out
        logout()
      }
    }
    next() // make sure to always call next()!
  }
});

export default router
