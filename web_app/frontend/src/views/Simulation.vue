<template>
  <div>
    <div class="card">
      <div class="card-title">仿真参数设置</div>
      <div class="form-row">
        <div class="form-group">
          <label>控制模式</label>
          <select v-model="params.mode" class="form-select">
            <option value="fixed">固定策略</option>
            <option value="sac">SAC 动态控制</option>
          </select>
        </div>
        <div class="form-group">
          <label>生育期</label>
          <select v-model="params.stage" class="form-select">
            <option value="EMERGENCE">出苗期</option>
            <option value="VEGETATIVE">营养生长期</option>
            <option value="TUBER_INIT">块茎形成期</option>
            <option value="BULKING">块茎膨大期</option>
            <option value="STARCH_ACCUMULATION">淀粉积累期</option>
            <option value="MATURATION">成熟期</option>
          </select>
        </div>
        <div class="form-group">
          <label>真实天气</label>
          <div class="toggle-row">
            <label class="toggle"><input type="checkbox" v-model="params.weather" /><span class="slider"></span></label>
            <span style="font-size:13px;color:var(--text-secondary)">Open-Meteo</span>
          </div>
        </div>
        <div class="form-group" style="display:flex;align-items:flex-end">
          <button class="btn btn-primary" @click="run" :disabled="loading">
            <span v-if="loading" class="spinner"></span>{{ loading ? '运行中...' : '▶ 开始仿真' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="result" class="card-grid">
      <div class="stat-card"><div class="stat-value">{{ result.stats.theta_final }}</div><div class="stat-label">最终 θ</div></div>
      <div class="stat-card accent"><div class="stat-value">{{ result.stats.ec_soil_final }}</div><div class="stat-label">最终 EC (dS/m)</div></div>
      <div class="stat-card success"><div class="stat-value">{{ result.stats.ec_mae }}</div><div class="stat-label">EC 跟踪 MAE</div></div>
      <div class="stat-card warning"><div class="stat-value">{{ result.stats.total_irrigation_mm }}</div><div class="stat-label">总灌溉 (mm)</div></div>
    </div>

    <div v-if="result" class="chart-grid">
      <div class="card"><div class="card-title">土壤含水率 θ</div><div class="chart-wrapper"><canvas ref="cMoisture"></canvas></div></div>
      <div class="card"><div class="card-title">根区 EC (实际 vs 目标)</div><div class="chart-wrapper"><canvas ref="cEC"></canvas></div></div>
      <div class="card"><div class="card-title">灌溉 & 蒸散发</div><div class="chart-wrapper"><canvas ref="cIrr"></canvas></div></div>
      <div class="card"><div class="card-title">控制动作 q_f, q_a</div><div class="chart-wrapper"><canvas ref="cAct"></canvas></div></div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, nextTick, onBeforeUnmount } from 'vue'
import { Chart, LineController, CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend } from 'chart.js'
import { runSimulation } from '../api/index.js'

Chart.register(LineController, CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

const C = { blue: '#1f77b4', orange: '#ff7f0e', green: '#2ca02c', red: '#d62728', gray: '#888', teal: '#00acc1' }

export default {
  name: 'Simulation',
  setup() {
    const params = reactive({ mode: 'fixed', stage: 'BULKING', weather: false })
    const loading = ref(false); const error = ref(''); const result = ref(null)
    const cMoisture = ref(null); const cEC = ref(null); const cIrr = ref(null); const cAct = ref(null)
    let charts = {}

    function destroyCharts() { Object.values(charts).forEach(c => { try { c.destroy() } catch (_) {} }); charts = {} }

    async function run() {
      loading.value = true; error.value = ''; result.value = null; destroyCharts()
      try {
        const data = await runSimulation({ mode: params.mode, stage: params.stage, weather: params.weather })
        if (!data.success) { error.value = data.error || '仿真失败'; return }
        result.value = data; await nextTick(); createCharts(data)
      } catch (e) { error.value = e.message || '网络错误' }
      finally { loading.value = false }
    }

    function createCharts(data) {
      const s = data.series; const labels = s.time_hours.map(t => t.toFixed(1) + 'h')
      const mk = (id, ds, yt) => { const c = new Chart(document.getElementById(id).getContext('2d'), {
        type: 'line', data: { labels, datasets: ds },
        options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
          plugins: { legend: { position: 'top', onClick: () => {}, labels: { boxWidth: 12, padding: 12, font: { size: 11 } } } },
          scales: { x: { ticks: { maxTicksLimit: 10, font: { size: 10 } } }, y: { title: { display: true, text: yt, font: { size: 11 } }, ticks: { font: { size: 10 } } } } }
      }); c.canvas.parentElement.style.height = '240px'; return c }

      charts = {
        m: mk('c-moisture', [
          { data: s.theta, borderColor: C.blue, backgroundColor: C.blue+'20', fill: true, tension: 0.3, pointRadius: 0, label: 'θ' },
          { data: Array(s.theta.length).fill(0.32), borderColor: C.gray, borderDash: [6,4], pointRadius: 0, label: 'θ_fc' },
        ], 'θ (m³/m³)'),
        e: mk('c-ec', [
          { data: s.ec_soil, borderColor: C.red, tension: 0.3, pointRadius: 0, label: 'EC_soil' },
          { data: s.ec_target, borderColor: C.gray, borderDash: [6,4], pointRadius: 0, label: '目标 EC' },
        ], 'EC (dS/m)'),
        i: mk('c-irr', [
          { data: s.irrigation_mm_h, borderColor: C.teal, backgroundColor: C.teal+'30', fill: true, tension: 0.3, pointRadius: 0, label: '灌溉' },
          { data: s.etc_mm_h, borderColor: C.orange, borderDash: [4,4], tension: 0.3, pointRadius: 0, label: 'ET' },
        ], 'mm/h'),
        a: mk('c-act', [
          { data: s.q_f, borderColor: C.blue, tension: 0.3, pointRadius: 1, label: 'q_f' },
          { data: s.q_a, borderColor: C.green, tension: 0.3, pointRadius: 1, label: 'q_a' },
        ], 'L/min'),
      }
    }

    onBeforeUnmount(() => destroyCharts())
    return { params, loading, error, result, cMoisture, cEC, cIrr, cAct, run }
  },
}
</script>
