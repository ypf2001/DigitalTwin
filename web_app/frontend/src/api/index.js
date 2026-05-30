import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 120000 })

export function getWeather() { return http.get('/weather').then(r => r.data) }
export function getConfig() { return http.get('/config').then(r => r.data) }
export function runSimulation(params) { return http.post('/simulate', params).then(r => r.data) }
export function runSeasonCompare(params) { return http.post('/season-compare', params).then(r => r.data) }
export function saveConfig(section, updates) { return http.put('/config/save', { section, updates }).then(r => r.data) }

// 训练相关 API
export function getTrainingStatus() { return http.get('/training/status').then(r => r.data) }
export function startTraining(params) { return http.post('/training/start', params).then(r => r.data) }
export function stopTraining() { return http.post('/training/stop').then(r => r.data) }
export function getTrainingModels(queryCloud = false) { return http.get('/training/models', { params: { query_cloud: queryCloud } }).then(r => r.data) }
export function uploadModels() { return http.post('/training/upload').then(r => r.data) }
export function uploadSelected(names) { return http.post('/training/upload/selected', { names }).then(r => r.data) }
export function stopUpload() { return http.post('/training/upload/stop').then(r => r.data) }
export function deleteModel(name) { return http.delete('/training/models/' + encodeURIComponent(name)).then(r => r.data) }
export function clearProgress() { return http.post('/training/progress/clear').then(r => r.data) }
export function getUploadProgress() { return http.get('/training/upload/progress').then(r => r.data) }
