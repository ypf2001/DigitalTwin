import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Simulation from '../views/Simulation.vue'
import SeasonCompare from '../views/SeasonCompare.vue'
import Settings from '../views/Settings.vue'
import Training from '../views/Training.vue'

const routes = [
  { path: '/', name: 'Dashboard', component: Dashboard },
  { path: '/simulation', name: 'Simulation', component: Simulation },
  { path: '/season-compare', name: 'SeasonCompare', component: SeasonCompare },
  { path: '/training', name: 'Training', component: Training },
  { path: '/settings', name: 'Settings', component: Settings },
]

export default createRouter({ history: createWebHashHistory(), routes })
