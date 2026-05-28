<template>
  <div class="settings-page">
    <div class="page-header">
      <div class="header-titles">
        <h2>系统设置</h2>
        <p class="subtitle">全局参数配置与调整</p>
      </div>
      <div v-if="data" class="header-actions">
        <button v-if="editing" class="btn btn-outline" @click="cancelEdit">✖ 取消</button>
        <button class="btn" :class="editing?'btn-primary':'btn-outline'" @click="toggleEdit">
          {{ editing ? '💾 保存配置' : '✏️ 编辑模式' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading-overlay"><span class="spinner dark"></span>加载中...</div>
    <div v-else-if="error" class="error-box">{{ error }}</div>

    <template v-else-if="data">
      <div v-if="saveMsg" class="success-box" style="margin-bottom: 20px;">{{ saveMsg }}</div>

      <div class="settings-grid">
        <!-- 左侧列 -->
        <div class="settings-col">
          <!-- Soil -->
          <div class="card">
            <div class="card-title">土壤初始与物理参数</div>
            <table class="stats-table config-table">
              <tr v-for="(v, k) in soilFields" :key="k">
                <th>{{ v.label }}</th>
                <td>
                  <input v-if="editing" v-model="edits['env.'+k]" class="form-input" />
                  <span v-else>{{ data.soil?.[k] }}</span>
                </td>
              </tr>
            </table>
          </div>

          <!-- Fixed Strategy -->
          <div class="card">
            <div class="card-title">固定灌溉策略</div>
            <table class="stats-table config-table">
              <tr><th>q_f (肥料流量 L/min)</th><td>
                <input v-if="editing" v-model="edits['action.fixed_strategy.0']" class="form-input" />
                <span v-else>{{ data.action_fixed?.[0] }}</span>
              </td></tr>
              <tr><th>q_a (酸液流量 L/min)</th><td>
                <input v-if="editing" v-model="edits['action.fixed_strategy.1']" class="form-input" />
                <span v-else>{{ data.action_fixed?.[1] }}</span>
              </td></tr>
            </table>
          </div>

          <!-- Mixing Tank -->
          <div v-if="data.mixing_tank" class="card">
            <div class="card-title">混肥罐参数</div>
            <table class="stats-table config-table">
              <tr v-for="(v, k) in data.mixing_tank" :key="k">
                <th>{{ k }}</th>
                <td>
                  <input v-if="editing" v-model="edits['mixing_tank.'+k]" class="form-input" />
                  <span v-else>{{ v }}</span>
                </td>
              </tr>
            </table>
          </div>

          <!-- Pipe -->
          <div v-if="data.pipe" class="card">
            <div class="card-title">管道动态参数 (FOPTD)</div>
            <table class="stats-table config-table">
              <tr v-for="(v, k) in data.pipe" :key="k">
                <th>{{ k }}</th>
                <td>
                  <input v-if="editing" v-model="edits['pipe.'+k]" class="form-input" />
                  <span v-else>{{ v }}</span>
                </td>
              </tr>
            </table>
          </div>
        </div>

        <!-- 右侧列 -->
        <div class="settings-col">
          <!-- Crop Stages -->
          <div v-if="data.stages" class="card">
            <div class="card-title">马铃薯生育期特征</div>
            <div style="overflow-x:auto">
              <table class="stats-table config-table compact">
                <thead><tr><th>生育期</th><th>Kc</th><th>目标 EC</th><th>根深</th></tr></thead>
                <tbody>
                  <tr v-for="(v, k) in data.stages" :key="k">
                    <td>{{ stageNames[k] || k }}</td>
                    <td>
                      <input v-if="editing" v-model="edits['stages.'+k+'.kc']" class="form-input" />
                      <span v-else>{{ v.kc }}</span>
                    </td>
                    <td>
                      <input v-if="editing" v-model="edits['stages.'+k+'.target_ec']" class="form-input" />
                      <span v-else>{{ v.target_ec }}</span>
                    </td>
                    <td>
                      <input v-if="editing" v-model="edits['stages.'+k+'.root_depth']" class="form-input" />
                      <span v-else>{{ v.root_depth }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- SAC -->
          <div v-if="data.sac" class="card">
            <div class="card-title">强化学习 (SAC) 超参数</div>
            <table class="stats-table config-table">
              <tr v-for="(v, k) in data.sac" :key="k">
                <th>{{ k }}</th>
                <td>
                  <input v-if="editing" v-model="edits['sac.'+k]" class="form-input" />
                  <span v-else>{{ v }}</span>
                </td>
              </tr>
            </table>
          </div>

          <!-- Reward -->
          <div v-if="data.reward" class="card">
            <div class="card-title">奖励函数权重</div>
            <table class="stats-table config-table">
              <tr v-for="(v, k) in data.reward" :key="k">
                <th>{{ k }}</th>
                <td>
                  <input v-if="editing" v-model="edits['reward.'+k]" class="form-input" />
                  <span v-else>{{ v }}</span>
                </td>
              </tr>
            </table>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script>
import { ref, reactive, onMounted } from 'vue'
import { getConfig, saveConfig } from '../api/index.js'

const SECTION_KEY_MAP = {
  env: 'simulation', soil: 'simulation', mixing_tank: 'simulation',
  pipe: 'simulation', action: 'simulation', obs: 'simulation',
  day_night: 'simulation', plc: 'simulation',
  crop: 'crop', stages: 'crop',
  sac: 'sac', reward: 'reward', irrigation: 'irrigation',
}

export default {
  name: 'Settings',
  setup() {
    const data = ref(null); const loading = ref(true); const error = ref('')
    const editing = ref(false); const saveMsg = ref(''); const edits = reactive({})

    const soilFields = {
      theta_fc: { label: '田间持水量  θfc' },
      theta_wp: { label: '萎蔫点  θwp' },
      theta_init: { label: '初始含水率  θinit' },
      ec_init: { label: '初始电导率  ECinit (dS/m)' },
    }

    const stageNames = {
      emergence: '出苗期', vegetative: '营养生长期', tuber_init: '块茎形成期',
      bulking: '块茎膨大期', starch_accumulation: '淀粉积累期', maturation: '成熟期',
    }

    function initEdits() {
      if (!data.value) return
      const e = {}
      // soil
      for (const k of Object.keys(soilFields)) e['env.' + k] = data.value.soil?.[k] ?? ''
      // fixed strategy
      e['action.fixed_strategy.0'] = data.value.action_fixed?.[0] ?? ''
      e['action.fixed_strategy.1'] = data.value.action_fixed?.[1] ?? ''
      // stages
      if (data.value.stages) {
        for (const [k, v] of Object.entries(data.value.stages)) {
          e['stages.' + k + '.kc'] = v.kc ?? ''
          e['stages.' + k + '.target_ec'] = v.target_ec ?? ''
          e['stages.' + k + '.root_depth'] = v.root_depth ?? ''
        }
      }
      // mixing_tank
      if (data.value.mixing_tank) for (const [k, v] of Object.entries(data.value.mixing_tank)) e['mixing_tank.' + k] = v ?? ''
      // pipe
      if (data.value.pipe) for (const [k, v] of Object.entries(data.value.pipe)) e['pipe.' + k] = v ?? ''
      // sac
      if (data.value.sac) for (const [k, v] of Object.entries(data.value.sac)) e['sac.' + k] = v ?? ''
      // reward
      if (data.value.reward) for (const [k, v] of Object.entries(data.value.reward)) e['reward.' + k] = v ?? ''

      Object.assign(edits, e)
    }

    function toggleEdit() {
      if (editing.value) {
        saveAll()
      } else {
        initEdits()
        editing.value = true
        saveMsg.value = ''
      }
    }

    function cancelEdit() {
      editing.value = false
      saveMsg.value = ''
    }

    async function saveAll() {
      saveMsg.value = ''
      try {
        // 按 section 分组保存
        const sections = {}
        for (const [path, val] of Object.entries(edits)) {
          const topKey = path.split('.')[0]
          const section = SECTION_KEY_MAP[topKey] || 'simulation'
          if (!sections[section]) sections[section] = {}
          sections[section][path] = val
        }

        for (const [section, updates] of Object.entries(sections)) {
          await saveConfig(section, updates)
        }

        editing.value = false
        saveMsg.value = '配置已保存！'

        // 重新加载
        const c = await getConfig()
        if (!c.error) data.value = c
      } catch (e) {
        saveMsg.value = '保存失败: ' + (e.message || '')
      }
    }

    onMounted(async () => {
      try {
        const c = await getConfig()
        if (c.error) { error.value = c.error; return }
        data.value = c
      } catch (e) { error.value = e.message || '加载失败' }
      finally { loading.value = false }
    })

    return { data, loading, error, editing, saveMsg, edits, soilFields, stageNames, toggleEdit, cancelEdit }
  },
}
</script>

<style scoped>
.settings-page {
  width: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-titles h2 {
  margin: 0 0 4px 0;
  font-size: 24px;
  color: var(--text-color);
}

.subtitle {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 1000px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}

.config-table th {
  width: 45%;
  font-weight: 500;
}

.config-table td {
  padding: 8px 12px;
}

.config-table.compact th,
.config-table.compact td {
  padding: 6px 8px;
  font-size: 13px;
}

.form-input {
  width: 100%;
  max-width: 120px;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  transition: border-color 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.success-box {
  padding: 12px 16px;
  background-color: #e8f5e9;
  color: #2e7d32;
  border-radius: 6px;
  border: 1px solid #c8e6c9;
  font-weight: 500;
}
</style>
