<template>
  <div class="dashboard-page page-container">
    <div class="page-header">
      <h2>仪表盘概览</h2>
      <p class="subtitle">实时监控与系统状态</p>
    </div>

    <div class="card-grid top-stats">
      <div class="stat-card">
        <div class="stat-icon weather-icon">☀️</div>
        <div class="stat-content">
          <div class="stat-label">ET0 (mm/天)</div>
          <div class="stat-value">{{ weather.et0 }}</div>
        </div>
      </div>
      <div class="stat-card accent">
        <div class="stat-icon rain-icon">🌧️</div>
        <div class="stat-content">
          <div class="stat-label">降雨 (mm/天)</div>
          <div class="stat-value">{{ weather.rain }}</div>
        </div>
      </div>
      <div class="stat-card success">
        <div class="stat-icon soil-icon">🌱</div>
        <div class="stat-content">
          <div class="stat-label">田间持水量 θ_fc</div>
          <div class="stat-value">{{ soil.theta_fc }}</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="stat-icon wilting-icon">🍂</div>
        <div class="stat-content">
          <div class="stat-label">萎蔫点 θ_wp</div>
          <div class="stat-value">{{ soil.theta_wp }}</div>
        </div>
      </div>
    </div>

    <div class="dashboard-main">
      <div class="card quick-actions-card">
        <div class="card-title">快捷操作</div>
        <div class="action-buttons">
          <router-link to="/simulation" class="btn-large btn-primary">
            <span class="btn-icon">🔬</span>
            <div class="btn-text">
              <strong>仿真实验室</strong>
              <span>运行短期仿真或季节对比</span>
            </div>
          </router-link>
          <router-link to="/training" class="btn-large btn-outline">
            <span class="btn-icon">🧠</span>
            <div class="btn-text">
              <strong>模型训练</strong>
              <span>管理和训练 SAC 控制模型</span>
            </div>
          </router-link>
        </div>
      </div>

      <div class="card system-info-card">
        <div class="card-title">系统信息</div>
        <table class="stats-table">
          <tr><th>项目名称</th><td>马铃薯施肥灌溉数字孪生系统</td></tr>
          <tr><th>目标地区</th><td>内蒙古察右中旗</td></tr>
          <tr><th>灌溉方式</th><td>滴灌施肥 (Fertigation)</td></tr>
          <tr><th>种植面积</th><td>0.1 ha</td></tr>
          <tr><th>管道动力学</th><td>FOPTD 一阶纯滞后模型</td></tr>
          <tr><th>作物生长</th><td>马铃薯 (6 个主要生育期)</td></tr>
          <tr><th>控制算法</th><td>SAC 强化学习动态控制 / 固定策略</td></tr>
        </table>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { getWeather, getConfig } from '../api/index.js'

export default {
  name: 'Dashboard',
  setup() {
    const weather = ref({ et0: '—', rain: '—' })
    const soil = ref({ theta_fc: '—', theta_wp: '—' })

    onMounted(async () => {
      try {
        const w = await getWeather()
        if (w && w.success !== false) {
          weather.value = { et0: w.et0_mm_day, rain: w.rain_mm_day }
        }
      } catch (_) {}

      try {
        const c = await getConfig()
        if (c && c.soil) {
          soil.value = {
            theta_fc: (c.soil.theta_fc || '').toFixed(2) || '—',
            theta_wp: (c.soil.theta_wp || '').toFixed(2) || '—'
          }
        }
      } catch (_) {}
    })

    return { weather, soil }
  },
}
</script>

<style scoped>
.page-header {
  margin-bottom: 24px;
}
.page-header h2 {
  margin: 0 0 4px 0;
  font-size: 24px;
  color: var(--text-color);
}
.subtitle {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.card-grid.top-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}

.stat-card {
  display: flex;
  align-items: center;
  padding: 24px;
  background: var(--card-bg);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  box-shadow: 0 4px 6px rgba(0,0,0,0.02);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 12px rgba(0,0,0,0.05);
}

.stat-icon {
  font-size: 32px;
  width: 60px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  margin-right: 16px;
  background: #f0f4f8;
}

.weather-icon { background: #fff8e1; }
.rain-icon { background: #e3f2fd; }
.soil-icon { background: #e8f5e9; }
.wilting-icon { background: #fbe9e7; }

.stat-content {
  display: flex;
  flex-direction: column;
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-color);
  margin-top: 4px;
}

.dashboard-main {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 900px) {
  .dashboard-main {
    grid-template-columns: 1fr;
  }
}

.action-buttons {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.btn-large {
  display: flex;
  align-items: center;
  padding: 20px;
  border-radius: 12px;
  text-decoration: none;
  transition: all 0.2s ease;
  border: 2px solid transparent;
}

.btn-large.btn-primary {
  background: linear-gradient(135deg, var(--primary-color), var(--primary-color-dark));
  color: white;
  box-shadow: 0 4px 12px rgba(74, 144, 226, 0.2);
}

.btn-large.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(74, 144, 226, 0.3);
}

.btn-large.btn-outline {
  background: transparent;
  border-color: var(--border-color);
  color: var(--text-color);
}

.btn-large.btn-outline:hover {
  border-color: var(--primary-color);
  background: rgba(74, 144, 226, 0.02);
}

.btn-icon {
  font-size: 32px;
  margin-right: 20px;
}

.btn-text {
  display: flex;
  flex-direction: column;
}

.btn-text strong {
  font-size: 18px;
  margin-bottom: 4px;
}

.btn-text span {
  font-size: 13px;
  opacity: 0.8;
}

.stats-table {
  width: 100%;
  border-collapse: collapse;
}

.stats-table th, .stats-table td {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color);
  text-align: left;
}

.stats-table th {
  width: 30%;
  color: var(--text-secondary);
  font-weight: 500;
  background-color: transparent;
}

.stats-table tr:last-child th,
.stats-table tr:last-child td {
  border-bottom: none;
}
</style>