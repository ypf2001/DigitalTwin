<template>
  <div>
    <div v-if="loading" class="loading-overlay"><span class="spinner dark"></span>加载中...</div>
    <div v-else-if="error" class="error-box">{{ error }}</div>
    <template v-else-if="data">
      <div class="card">
        <div class="card-title">土壤参数</div>
        <table class="stats-table">
          <tr><th>田间持水量 θ_fc</th><td>{{ data.soil?.theta_fc }}</td></tr>
          <tr><th>萎蔫点 θ_wp</th><td>{{ data.soil?.theta_wp }}</td></tr>
          <tr><th>初始含水率</th><td>{{ data.soil?.theta_init }}</td></tr>
          <tr><th>初始 EC</th><td>{{ data.soil?.ec_init }} dS/m</td></tr>
        </table>
      </div>
      <div class="card">
        <div class="card-title">动作空间</div>
        <table class="stats-table">
          <tr><th>q_f 范围</th><td>0 ~ 10 L/min</td></tr>
          <tr><th>q_a 范围</th><td>0 ~ 5 L/min</td></tr>
          <tr><th>固定策略</th><td>q_f = {{ data.action_fixed?.[0] }}, q_a = {{ data.action_fixed?.[1] }}</td></tr>
        </table>
      </div>
      <div v-if="data.mixing_tank" class="card"><div class="card-title">混肥罐</div>
        <table class="stats-table"><tr v-for="(v,k) in data.mixing_tank" :key="k"><th>{{k}}</th><td>{{v}}</td></tr></table>
      </div>
      <div v-if="data.pipe" class="card"><div class="card-title">管道 (FOPTD)</div>
        <table class="stats-table"><tr v-for="(v,k) in data.pipe" :key="k"><th>{{k}}</th><td>{{v}}</td></tr></table>
      </div>
      <div v-if="data.sac" class="card"><div class="card-title">SAC 参数</div>
        <table class="stats-table"><tr v-for="(v,k) in data.sac" :key="k"><th>{{k}}</th><td>{{v}}</td></tr></table>
      </div>
      <div v-if="data.stages" class="card"><div class="card-title">生育期参数</div>
        <div style="overflow-x:auto">
          <table class="stats-table">
            <thead><tr><th>生育期</th><th>Kc</th><th>目标 EC (dS/m)</th><th>根深 (m)</th></tr></thead>
            <tbody><tr v-for="(v,k) in data.stages" :key="k"><td>{{k}}</td><td>{{v.kc}}</td><td>{{v.target_ec}}</td><td>{{v.root_depth}}</td></tr></tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { getConfig } from '../api/index.js'

export default {
  name: 'Settings',
  setup() {
    const data = ref(null); const loading = ref(true); const error = ref('')
    onMounted(async () => {
      try {
        const c = await getConfig()
        if (c.error) { error.value = c.error; return }
        data.value = c
      } catch (e) { error.value = e.message || '加载失败' }
      finally { loading.value = false }
    })
    return { data, loading, error }
  },
}
</script>
