import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import SimulationLab from '../views/SimulationLab.vue' // 新增导入
import Settings from '../views/Settings.vue'
import Training from '../views/Training.vue'

const routes = [
  { path: '/', name: 'Dashboard', component: Dashboard },
  { path: '/simulation', name: 'SimulationLab', component: SimulationLab }, // 修改路由
  // { path: '/season-compare', name: 'SeasonCompare', component: SeasonCompare }, // 移除此行
  { path: '/training', name: 'Training', component: Training },
  { path: '/settings', name: 'Settings', component: Settings },
]

export default createRouter({ history: createWebHashHistory(), routes })