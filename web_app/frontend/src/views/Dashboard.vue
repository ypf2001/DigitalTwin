<template>
  <div>
    <div class="card-grid">
      <div class="stat-card"><div class="stat-value">{{ weather.et0 }}</div><div class="stat-label">ET0 (mm/天)</div></div>
      <div class="stat-card accent"><div class="stat-value">{{ weather.rain }}</div><div class="stat-label">降雨 (mm/天)</div></div>
      <div class="stat-card success"><div class="stat-value">{{ soil.theta_fc }}</div><div class="stat-label">田间持水量 θ_fc</div></div>
      <div class="stat-card warning"><div class="stat-value">{{ soil.theta_wp }}</div><div class="stat-label">萎蔫点 θ_wp</div></div>
    </div>
    <div class="card" style="margin-top:20px">
      <div class="card-title">快捷操作</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <router-link to="/simulation" class="btn btn-primary">🔬 运行仿真</router-link>
        <router-link to="/season-compare" class="btn btn-outline">📈 季节对比</router-link>
      </div>
    </div>
    <div class="card" style="margin-top:20px">
      <div class="card-title">系统信息</div>
      <table class="stats-table">
        <tr><th>项目</th><td>马铃薯施肥灌溉数字孪生系统</td></tr>
        <tr><th>地区</th><td>内蒙古察右中旗</td></tr>
        <tr><th>灌溉方式</th><td>滴灌施肥 (Fertigation)</td></tr>
        <tr><th>面积</th><td>0.1 ha</td></tr>
        <tr><th>管道模型</th><td>FOPTD 一阶纯滞后</td></tr>
        <tr><th>作物</th><td>马铃薯 (6 个生育期)</td></tr>
        <tr><th>控制算法</th><td>SAC 强化学习 + 固定策略</td></tr>
      </table>
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
      try { const w = await getWeather(); if (w && w.success !== false) { weather.value = { et0: w.et0_mm_day, rain: w.rain_mm_day } } } catch (_) {}
      try { const c = await getConfig(); if (c && c.soil) { soil.value = { theta_fc: (c.soil.theta_fc||'').toFixed(2)||'—', theta_wp: (c.soil.theta_wp||'').toFixed(2)||'—' } } } catch (_) {}
    })
    return { weather, soil }
  },
}
</script>
