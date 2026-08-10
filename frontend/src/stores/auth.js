import { defineStore, acceptHMRUpdate } from 'pinia'
import { api } from '../api/client'

export const useAuth = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: null,
  }),
  getters: {
    isAuthed: (s) => !!s.token,
  },
  actions: {
    async login(username, password) {
      const { data } = await api.login(username, password)
      this.token = data.access_token
      this.user = data.user
      localStorage.setItem('token', data.access_token)
    },
    async fetchMe() {
      const { data } = await api.me()
      this.user = data
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
    },
  },
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useAuth, import.meta.hot))
}
