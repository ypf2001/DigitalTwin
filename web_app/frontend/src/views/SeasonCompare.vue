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

    <div v-if="result && result.image" class="card" style="margin-top:16px">
      <div class="card-title">对比图表</div>
      <img :src="result.image" style="width:100%;max-width:100%" alt="季节对比图表" />
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'
import { runSeasonCompare } from '../api/index.js'

export default {
  name: 'SeasonCompare',
  setup() {
    const weather = ref(false); const loading = ref(false); const error = ref(''); const result = ref(null)

    const statRows = computed(() => {
      if (!result.value || !result.value.stats) return []
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

    async function run() {
      loading.value = true; error.value = ''; result.value = null
      try {
        const data = await runSeasonCompare({ weather: weather.value })
        if (!data.success) { error.value = data.error || '仿真失败'; return }
        result.value = data
      } catch (e) { error.value = e.message || '网络错误' }
      finally { loading.value = false }
    }

    return { weather, loading, error, result, statRows, run }
  },
}
</script>
