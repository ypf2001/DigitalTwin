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

    <div v-if="result && result.image" class="card" style="margin-top:16px">
      <div class="card-title">仿真结果</div>
      <img :src="result.image" style="width:100%;max-width:100%" alt="仿真图表" />
    </div>
  </div>
</template>

<script>
import { ref, reactive } from 'vue'
import { runSimulation } from '../api/index.js'

export default {
  name: 'Simulation',
  setup() {
    const params = reactive({ mode: 'fixed', stage: 'BULKING', weather: false })
    const loading = ref(false); const error = ref(''); const result = ref(null)

    async function run() {
      loading.value = true; error.value = ''; result.value = null
      try {
        const data = await runSimulation({ mode: params.mode, stage: params.stage, weather: params.weather })
        if (!data.success) { error.value = data.error || '仿真失败'; return }
        result.value = data
      } catch (e) { error.value = e.message || '网络错误' }
      finally { loading.value = false }
    }

    return { params, loading, error, result, run }
  },
}
</script>
