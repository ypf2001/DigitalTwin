import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 120000 })

export function getWeather() { return http.get('/weather').then(r => r.data) }
export function getConfig() { return http.get('/config').then(r => r.data) }
export function runSimulation(params) { return http.post('/simulate', params).then(r => r.data) }
export function runSeasonCompare(params) { return http.post('/season-compare', params).then(r => r.data) }
