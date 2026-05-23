<template>
  <div>
    <div class="card">
      <div class="card-title">季节对比设置</div>
      <div class="form-row">
        <div class="form-group">
          <label>真实天气</label>
          <div class="toggle-row">
            <label class="toggle"><input type="checkbox" v-model="weather" /><span class="slider"></span></label>
            <span style="font-size:13px;color:var(--text-secondary)">Open-Meteo</span>
          </div>
        </div>
        <div class="form-group" style="display:flex;align-items:flex-end">
          <button class="btn btn-primary" @click="run" :disabled="loading">
            <span v-if="loading" class="spinner"></span>{{ loading ? '运行中...' : '▶ 开始 90 天对比' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="result" class="card" style="overflow-x:auto">
      <div class="card-title">统计对比</div>
      <table class="stats-table">
        <thead><tr><th>指标</th><th>T1 (等量)</th><th>T2 (根系)</th><th>改善</th></tr></thead>
        <tbody>
          <tr v-for="r in statRows" :key="r.label">
            <td>{{ r.label }}</td><td>{{ r.v1 }}</td><td>{{ r.v2 }}</td><td :class="{ improve: r.good }">{{ r.delta }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="result" class="chart-grid">
      <div class="card"><div class="card-title">θ — T1 vs T2</div><div class="chart-wrapper"><canvas id="c-stheta"></canvas></div></div>
      <div class="card"><div class="card-title">EC 动态 — T1 vs T2</div><div class="chart-wrapper"><canvas id="c-sec"></canvas></div></div>
      <div class="card"><div class="card-title">灌溉事件</div><div class="chart-wrapper"><canvas id="c-sirr"></canvas></div></div>
      <div class="card"><div class="card-title">累积灌溉量</div><div class="chart-wrapper"><canvas id="c-scum"></canvas></div></div>
    </div>
  </div>
</template>

<script>
import { ref, computed, nextTick, onBeforeUnmount } from 'vue'
import { Chart, LineController, CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend } from 'chart.js'
import { runSeasonCompare } from '../api/index.js'

Chart.register(LineController, CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

const BLUE = '#1f77b4'; const ORANGE = '#ff7f0e'; const GRAY = '#888'

export default {
  name: 'SeasonCompare',
  setup() {
    const weather = ref(false); const loading = ref(false); const error = ref(''); const result = ref(null)
    let charts = {}

    const statRows = computed(() => {
      if (!result.value) return []
      const s = result.value.stats
      return [
        { label: 'EC 跟踪 MAE', v1: s.ec_mae_t1, v2: s.ec_mae_t2, good: s.ec_mae_t2 < s.ec_mae_t1, delta: (s.ec_mae_t1 - s.ec_mae_t2) > 0 ? '↓' + (s.ec_mae_t1 - s.ec_mae_t2).toFixed(3) : '—' },
        { label: '平均 θ', v1: s.theta_mean_t1, v2: s.theta_mean_t2, good: true, delta: (s.theta_improve_pct >= 0 ? '+' : '') + s.theta_improve_pct + '%' },
        { label: '总灌溉量 (mm)', v1: s.total_irr_t1, v2: s.total_irr_t2, good: false, delta: ((s.total_irr_t2 - s.total_irr_t1) / (s.total_irr_t1 + 1e-6) * 100).toFixed(1) + '%' },
        { label: '总蒸散发 (mm)', v1: s.total_et_t1, v2: s.total_et_t2, good: false, delta: ((s.total_et_t2 - s.total_et_t1) / (s.total_et_t1 + 1e-6) * 100).toFixed(1) + '%' },
        { label: '深层渗漏 (mm)', v1: s.deep_drain_t1, v2: s.deep_drain_t2, good: s.deep_drain_t2 < s.deep_drain_t1, delta: s.deep_drain_t2 < s.deep_drain_t1 ? '↓' + (s.deep_drain_t1 - s.deep_drain_t2).toFixed(1) : '—' },
        { label: '灌溉期 θ CV', v1: s.theta_cv_t1, v2: s.theta_cv_t2, good: s.theta_cv_t2 < s.theta_cv_t1, delta: (s.theta_cv_t1 - s.theta_cv_t2) > 0.001 ? '↓ 更稳定' : '—' },
        { label: 'WUE 代理', v1: s.wue_t1, v2: s.wue_t2, good: true, delta: (s.wue_change_pct >= 0 ? '+' : '') + s.wue_change_pct + '%' },
      ]
    })

    function destroyCharts() { Object.values(charts).forEach(c => { try { c.destroy() } catch (_) {} }); charts = {} }

    function downsample(arr, n = 400) { if (arr.length <= n) return arr; const s = Math.ceil(arr.length / n); return arr.filter((_, i) => i % s === 0) }

    async function run() {
      loading.value = true; error.value = ''; result.value = null; destroyCharts()
      try {
        const data = await runSeasonCompare({ weather: weather.value })
        if (!data.success) { error.value = data.error || '仿真失败'; return }
        result.value = data; await nextTick(); createCharts(data)
      } catch (e) { error.value = e.message || '网络错误' }
      finally { loading.value = false }
    }

    function createCharts(data) {
      const t1 = data.T1; const t2 = data.T2
      const lbl = downsample(t1.time_day, 400).map(d => d.toFixed(1) + 'd')
      const th1 = downsample(t1.theta, 400); const th2 = downsample(t2.theta, 400)
      const ec1 = downsample(t1.ec_soil, 400); const ec2 = downsample(t2.ec_soil, 400)
      const ect = downsample(t1.ec_target, 400)
      const ir1 = downsample(t1.irrigation_mm_h, 400); const ir2 = downsample(t2.irrigation_mm_h, 400)
      const cum1 = []; const cum2 = []; let s1 = 0; let s2 = 0
      for (let i = 0; i < t1.irrigation_mm_h.length; i++) { s1 += t1.irrigation_mm_h[i] * 0.25; cum1.push(s1) }
      for (let i = 0; i < t2.irrigation_mm_h.length; i++) { s2 += t2.irrigation_mm_h[i] * 0.25; cum2.push(s2) }

      const mk = (id, ds, yt, xt) => { const c = new Chart(document.getElementById(id).getContext('2d'), {
        type: 'line', data: { labels: lbl, datasets: ds },
        options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
          plugins: { legend: { position: 'top', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } } },
          scales: { x: { title: { display: true, text: xt || '天数 (DAE)', font: { size: 11 } }, ticks: { maxTicksLimit: 10, font: { size: 10 } } },
                    y: { title: { display: true, text: yt, font: { size: 11 } }, ticks: { font: { size: 10 } } } } }
      }); c.canvas.parentElement.style.height = '240px'; return c }

      charts = {
        th: mk('c-stheta', [
          { data: th1, borderColor: BLUE, tension: 0.3, pointRadius: 0, label: 'θ T1' },
          { data: th2, borderColor: ORANGE, borderDash: [6,3], tension: 0.3, pointRadius: 0, label: 'θ T2' },
          { data: Array(th1.length).fill(0.32), borderColor: GRAY, borderDash: [3,6], pointRadius: 0, borderWidth: 0.8, label: 'θ_fc' },
        ], 'θ (m³/m³)'),
        ec: mk('c-sec', [
          { data: ec1, borderColor: BLUE, tension: 0.3, pointRadius: 0, label: 'EC T1' },
          { data: ec2, borderColor: ORANGE, borderDash: [6,3], tension: 0.3, pointRadius: 0, label: 'EC T2' },
          { data: ect, borderColor: '#333', borderDash: [3,3], pointRadius: 0, borderWidth: 1, label: '目标 EC' },
        ], 'EC (dS/m)'),
        ir: mk('c-sirr', [
          { data: ir1, borderColor: BLUE, tension: 0.3, pointRadius: 0, label: 'T1' },
          { data: ir2, borderColor: ORANGE, borderDash: [6,3], tension: 0.3, pointRadius: 0, label: 'T2' },
        ], 'mm/h'),
        cu: mk('c-scum', [
          { data: downsample(cum1, 400), borderColor: BLUE, tension: 0.3, pointRadius: 0, label: '累积 T1' },
          { data: downsample(cum2, 400), borderColor: ORANGE, borderDash: [6,3], tension: 0.3, pointRadius: 0, label: '累积 T2' },
        ], '累积 (mm)'),
      }
    }

    onBeforeUnmount(() => destroyCharts())
    return { weather, loading, error, result, statRows, run }
  },
}
</script>
