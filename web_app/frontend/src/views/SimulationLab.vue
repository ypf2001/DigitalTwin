<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>仿真实验室</h2>
        <p class="subtitle">短期仿真 / 季节对比</p>
      </div>
    </div>
    <div class="tabs-container">
      <div class="tabs-header">
        <button :class="{ 'tab-button': true, 'active': activeTab === 'simulation' }" @click="activeTab = 'simulation'">短期仿真</button>
        <button :class="{ 'tab-button': true, 'active': activeTab === 'seasonCompare' }" @click="activeTab = 'seasonCompare'">季节对比</button>
      </div>
      <div class="tabs-content">
        <!-- 短期仿真 Tab -->
        <div v-if="activeTab === 'simulation'">
          <div class="card">
            <div class="card-title">仿真参数设置</div>
            <div class="form-row">
              <div class="form-group">
                <label>控制模式</label>
                <select v-model="simulationParams.mode" class="form-select">
                  <option value="fixed">固定策略</option>
                  <option value="sac">SAC 动态控制</option>
                </select>
              </div>
              <div class="form-group">
                <label>生育期</label>
                <select v-model="simulationParams.stage" class="form-select">
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
                  <label class="toggle"><input type="checkbox" v-model="simulationParams.weather" /><span class="slider"></span></label>
                  <span style="font-size:13px;color:var(--text-secondary)">Open-Meteo</span>
                </div>
              </div>
              <div class="form-group" style="display:flex;align-items:flex-end">
                <button class="btn btn-primary" @click="runShortTermSimulation" :disabled="simulationLoading">
                  <span v-if="simulationLoading" class="spinner"></span>{{ simulationLoading ? '运行中...' : '▶ 开始仿真' }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="simulationError" class="error-box">{{ simulationError }}</div>

          <div v-if="simulationResult" class="card-grid">
            <div class="stat-card"><div class="stat-value">{{ simulationResult.stats.theta_final }}</div><div class="stat-label">最终 θ</div></div>
            <div class="stat-card accent"><div class="stat-value">{{ simulationResult.stats.ec_soil_final }}</div><div class="stat-label">最终 EC (dS/m)</div></div>
            <div class="stat-card success"><div class="stat-value">{{ simulationResult.stats.ec_mae }}</div><div class="stat-label">EC 跟踪 MAE</div></div>
            <div class="stat-card warning"><div class="stat-value">{{ simulationResult.stats.total_irrigation_mm }}</div><div class="stat-label">总灌溉 (mm)</div></div>
          </div>

          <div v-if="simulationResult && simulationResult.series" class="twin-visual-grid">
            <div class="viz-panel">
              <div class="viz-head">
                <div>
                  <h3>根区土壤含水率</h3>
                  <span>θ / 田间持水量 / 凋萎点</span>
                </div>
                <strong>{{ latestValue('theta') }}</strong>
              </div>
              <svg class="mini-chart" viewBox="0 0 640 220" role="img" aria-label="根区土壤含水率曲线">
                <g class="grid-lines">
                  <line v-for="y in gridY" :key="'theta-grid-'+y" :x1="chart.left" :x2="chart.right" :y1="y" :y2="y" />
                </g>
                <line class="guide success" :x1="chart.left" :x2="chart.right" :y1="valueY(0.32, domainFor(['theta'], true))" :y2="valueY(0.32, domainFor(['theta'], true))" />
                <line class="guide danger" :x1="chart.left" :x2="chart.right" :y1="valueY(0.04, domainFor(['theta'], true))" :y2="valueY(0.04, domainFor(['theta'], true))" />
                <polyline class="line blue" :points="linePoints('theta', domainFor(['theta'], true))" />
              </svg>
              <div class="viz-meta"><span>最小 {{ minValue('theta') }}</span><span>平均 {{ meanValue('theta') }}</span><span>最大 {{ maxValue('theta') }}</span></div>
            </div>

            <div class="viz-panel">
              <div class="viz-head">
                <div>
                  <h3>EC 目标跟踪</h3>
                  <span>土壤 EC 与目标 EC</span>
                </div>
                <strong>{{ simulationResult.stats.ec_mae }}</strong>
              </div>
              <svg class="mini-chart" viewBox="0 0 640 220" role="img" aria-label="土壤 EC 与目标 EC 曲线">
                <g class="grid-lines">
                  <line v-for="y in gridY" :key="'ec-grid-'+y" :x1="chart.left" :x2="chart.right" :y1="y" :y2="y" />
                </g>
                <polyline class="line red" :points="linePoints('ec_soil', domainFor(['ec_soil', 'ec_target']))" />
                <polyline class="line purple dashed" :points="linePoints('ec_target', domainFor(['ec_soil', 'ec_target']))" />
              </svg>
              <div class="legend-row"><span class="dot red"></span>实际 EC<span class="dot purple"></span>目标 EC</div>
            </div>

            <div class="viz-panel">
              <div class="viz-head">
                <div>
                  <h3>水分通量</h3>
                  <span>灌溉速率与蒸散发</span>
                </div>
                <strong>{{ simulationResult.stats.total_et_mm }}</strong>
              </div>
              <svg class="mini-chart" viewBox="0 0 640 220" role="img" aria-label="灌溉和蒸散发曲线">
                <g class="grid-lines">
                  <line v-for="y in gridY" :key="'water-grid-'+y" :x1="chart.left" :x2="chart.right" :y1="y" :y2="y" />
                </g>
                <rect v-for="bar in barRects('irrigation_mm_h', domainFor(['irrigation_mm_h', 'etc_mm_h'], true))" :key="bar.key" class="bar blue" v-bind="bar" />
                <polyline class="line orange" :points="linePoints('etc_mm_h', domainFor(['irrigation_mm_h', 'etc_mm_h'], true))" />
              </svg>
              <div class="legend-row"><span class="dot blue"></span>灌溉<span class="dot orange"></span>ET</div>
            </div>

            <div class="viz-panel">
              <div class="viz-head">
                <div>
                  <h3>控制动作</h3>
                  <span>肥料流量与酸液流量</span>
                </div>
                <strong>{{ latestValue('q_f') }} / {{ latestValue('q_a') }}</strong>
              </div>
              <svg class="mini-chart" viewBox="0 0 640 220" role="img" aria-label="肥料流量与酸液流量曲线">
                <g class="grid-lines">
                  <line v-for="y in gridY" :key="'action-grid-'+y" :x1="chart.left" :x2="chart.right" :y1="y" :y2="y" />
                </g>
                <polyline class="line green" :points="linePoints('q_f', domainFor(['q_f', 'q_a'], true))" />
                <polyline class="line amber" :points="linePoints('q_a', domainFor(['q_f', 'q_a'], true))" />
              </svg>
              <div class="legend-row"><span class="dot green"></span>q_f<span class="dot amber"></span>q_a</div>
            </div>
          </div>

          <div v-if="simulationResult && simulationResult.image" class="card" style="margin-top:16px">
            <div class="card-title">仿真结果</div>
            <img :src="simulationResult.image" style="width:100%;max-width:100%" alt="仿真图表" />
          </div>
        </div>

        <!-- 季节对比 Tab -->
        <div v-if="activeTab === 'seasonCompare'">
          <div class="card">
            <div class="card-title">季节对比设置</div>
            <div class="form-row">
              <div class="form-group">
                <label>真实天气</label>
                <div class="toggle-row">
                  <label class="toggle"><input type="checkbox" v-model="seasonCompareWeather" /><span class="slider"></span></label>
                  <span style="font-size:13px;color:var(--text-secondary)">Open-Meteo</span>
                </div>
              </div>
              <div class="form-group" style="display:flex;align-items:flex-end">
                <button class="btn btn-primary" @click="runSeasonComparison" :disabled="seasonCompareLoading">
                  <span v-if="seasonCompareLoading" class="spinner"></span>{{ seasonCompareLoading ? '运行中...' : '▶ 开始 90 天对比' }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="seasonCompareError" class="error-box">{{ seasonCompareError }}</div>

          <div v-if="seasonCompareResult" class="card" style="overflow-x:auto">
            <div class="card-title">统计对比</div>
            <table class="stats-table">
              <thead><tr><th>指标</th><th>T1 (等量)</th><th>T2 (根系)</th><th>改善</th></tr></thead>
              <tbody>
                <tr v-for="r in seasonCompareStatRows" :key="r.label">
                  <td>{{ r.label }}</td><td>{{ r.v1 }}</td><td>{{ r.v2 }}</td><td :class="{ improve: r.good }">{{ r.delta }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="seasonCompareResult && seasonCompareResult.image" class="card" style="margin-top:16px">
            <div class="card-title">对比图表</div>
            <img :src="seasonCompareResult.image" style="width:100%;max-width:100%" alt="季节对比图表" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, computed } from 'vue'
import { runSimulation, runSeasonCompare } from '../api/index.js'

export default {
  name: 'SimulationLab',
  setup() {
    // 短期仿真状态
    const activeTab = ref('simulation')
    const simulationParams = reactive({ mode: 'fixed', stage: 'BULKING', weather: false })
    const simulationLoading = ref(false)
    const simulationError = ref('')
    const simulationResult = ref(null)
    const chart = { left: 34, right: 620, top: 18, bottom: 190, width: 586, height: 172 }
    const gridY = [18, 61, 104, 147, 190]

    async function runShortTermSimulation() {
      simulationLoading.value = true
      simulationError.value = ''
      simulationResult.value = null
      try {
        const data = await runSimulation({ mode: simulationParams.mode, stage: simulationParams.stage, weather: simulationParams.weather })
        if (!data.success) {
          simulationError.value = data.error || '仿真失败'
          return
        }
        simulationResult.value = data
      } catch (e) {
        simulationError.value = e.message || '网络错误'
      } finally {
        simulationLoading.value = false
      }
    }

    // 季节对比状态
    const seasonCompareWeather = ref(false)
    const seasonCompareLoading = ref(false)
    const seasonCompareError = ref('')
    const seasonCompareResult = ref(null)

    const seasonCompareStatRows = computed(() => {
      if (!seasonCompareResult.value || !seasonCompareResult.value.stats) return []
      const s = seasonCompareResult.value.stats
      return [
        { label: 'EC 跟踪 MAE', v1: s.ec_mae_t1, v2: s.ec_mae_t2, good: s.ec_mae_t2 < s.ec_mae_t1, delta: (s.ec_mae_t1 - s.ec_mae_t2) > 0 ? '↓' + (s.ec_mae_t1 - s.ec_mae_t2).toFixed(3) : '—' },
        { label: '平均 θ', v1: s.theta_mean_t1, v2: s.theta_mean_t2, good: true, delta: (s.theta_improve_pct >= 0 ? '+' : '') + s.theta_improve_pct + '%' },
        { label: '计划灌溉量 (mm)', v1: s.total_irr_t1, v2: s.total_irr_t2, good: false, delta: ((s.total_irr_t2 - s.total_irr_t1) / (s.total_irr_t1 + 1e-6) * 100).toFixed(1) + '%' },
        { label: '仿真实际灌入 (mm)', v1: s.simulated_irr_t1, v2: s.simulated_irr_t2, good: false, delta: ((s.simulated_irr_t2 - s.simulated_irr_t1) / (s.simulated_irr_t1 + 1e-6) * 100).toFixed(1) + '%' },
        { label: '总蒸散发 (mm)', v1: s.total_et_t1, v2: s.total_et_t2, good: false, delta: ((s.total_et_t2 - s.total_et_t1) / (s.total_et_t1 + 1e-6) * 100).toFixed(1) + '%' },
        { label: '深层渗漏 (mm)', v1: s.deep_drain_t1, v2: s.deep_drain_t2, good: s.deep_drain_t2 < s.deep_drain_t1, delta: s.deep_drain_t2 < s.deep_drain_t1 ? '↓' + (s.deep_drain_t1 - s.deep_drain_t2).toFixed(1) : '—' },
        { label: '灌溉期 θ CV', v1: s.theta_cv_t1, v2: s.theta_cv_t2, good: s.theta_cv_t2 < s.theta_cv_t1, delta: (s.theta_cv_t1 - s.theta_cv_t2) > 0.001 ? '↓ 更稳定' : '—' },
        { label: 'WUE 代理', v1: s.wue_t1, v2: s.wue_t2, good: true, delta: (s.wue_change_pct >= 0 ? '+' : '') + s.wue_change_pct + '%' },
      ]
    })

    async function runSeasonComparison() {
      seasonCompareLoading.value = true
      seasonCompareError.value = ''
      seasonCompareResult.value = null
      try {
        const data = await runSeasonCompare({ weather: seasonCompareWeather.value })
        if (!data.success) {
          seasonCompareError.value = data.error || '仿真失败'
          return
        }
        seasonCompareResult.value = data
      } catch (e) {
        seasonCompareError.value = e.message || '网络错误'
      } finally {
        seasonCompareLoading.value = false
      }
    }

    function seriesValues(key) {
      return simulationResult.value?.series?.[key] || []
    }

    function formatNumber(value, digits = 3) {
      if (!Number.isFinite(value)) return '—'
      return Number(value).toFixed(digits).replace(/\.?0+$/, '')
    }

    function domainFor(keys, includeZero = false) {
      const values = keys.flatMap((key) => seriesValues(key)).filter((v) => Number.isFinite(Number(v))).map(Number)
      if (includeZero) values.push(0)
      if (keys.includes('theta')) values.push(0.04, 0.32)
      if (!values.length) return { min: 0, max: 1 }
      let min = Math.min(...values)
      let max = Math.max(...values)
      if (min === max) {
        const pad = Math.abs(max || 1) * 0.1
        min -= pad
        max += pad
      }
      const pad = (max - min) * 0.08
      return { min: Math.max(0, min - pad), max: max + pad }
    }

    function valueY(value, domain) {
      const ratio = (domain.max - Number(value)) / (domain.max - domain.min || 1)
      return chart.top + ratio * chart.height
    }

    function valueX(index, total) {
      if (total <= 1) return chart.left
      return chart.left + (index / (total - 1)) * chart.width
    }

    function linePoints(key, domain) {
      const values = seriesValues(key)
      return values.map((value, index) => `${valueX(index, values.length).toFixed(1)},${valueY(value, domain).toFixed(1)}`).join(' ')
    }

    function barRects(key, domain) {
      const values = seriesValues(key)
      const barWidth = Math.max(2, chart.width / Math.max(values.length, 1) * 0.72)
      return values.map((value, index) => {
        const x = valueX(index, values.length) - barWidth / 2
        const y = valueY(value, domain)
        return {
          key: `${key}-${index}`,
          x: x.toFixed(1),
          y: y.toFixed(1),
          width: barWidth.toFixed(1),
          height: Math.max(1, chart.bottom - y).toFixed(1),
        }
      })
    }

    function latestValue(key) {
      const values = seriesValues(key)
      return formatNumber(Number(values[values.length - 1]))
    }

    function minValue(key) {
      const values = seriesValues(key).map(Number)
      return formatNumber(Math.min(...values))
    }

    function maxValue(key) {
      const values = seriesValues(key).map(Number)
      return formatNumber(Math.max(...values))
    }

    function meanValue(key) {
      const values = seriesValues(key).map(Number)
      return formatNumber(values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1))
    }

    return {
      activeTab,
      simulationParams,
      simulationLoading,
      simulationError,
      simulationResult,
      runShortTermSimulation,
      chart,
      gridY,
      domainFor,
      valueY,
      linePoints,
      barRects,
      latestValue,
      minValue,
      maxValue,
      meanValue,
      seasonCompareWeather,
      seasonCompareLoading,
      seasonCompareError,
      seasonCompareResult,
      seasonCompareStatRows,
      runSeasonComparison,
    }
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

.tabs-container {
  margin-top: 0;
}

.tabs-header {
  display: flex;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 20px;
}

.tab-button {
  padding: 10px 20px;
  background-color: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  font-size: 16px;
  color: var(--text-secondary);
  transition: all 0.2s ease;
}

.tab-button:hover {
  color: var(--primary-color);
}

.tab-button.active {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
  font-weight: 600;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.stat-card {
  background: var(--card-bg);
  border-radius: 8px;
  border: 1px solid var(--border-color);
  padding: 16px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--primary-color);
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.stat-card.accent .stat-value { color: #f39c12; } /* Orange */
.stat-card.success .stat-value { color: #27ae60; } /* Green */
.stat-card.warning .stat-value { color: #e74c3c; } /* Red */

.twin-visual-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.viz-panel {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  min-width: 0;
}

.viz-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.viz-head h3 {
  margin: 0;
  font-size: 15px;
  line-height: 1.3;
  color: var(--text-color);
}

.viz-head span {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-secondary);
}

.viz-head strong {
  font-size: 18px;
  color: var(--primary-color);
  white-space: nowrap;
}

.mini-chart {
  display: block;
  width: 100%;
  height: 190px;
  overflow: visible;
}

.grid-lines line {
  stroke: #e9eef5;
  stroke-width: 1;
}

.line {
  fill: none;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.line.dashed {
  stroke-dasharray: 9 8;
}

.line.blue { stroke: #3498db; }
.line.red { stroke: #e74c3c; }
.line.purple { stroke: #8e44ad; }
.line.orange { stroke: #e67e22; }
.line.green { stroke: #27ae60; }
.line.amber { stroke: #f39c12; }

.guide {
  stroke-width: 2;
  stroke-dasharray: 7 7;
  opacity: 0.75;
}

.guide.success { stroke: #27ae60; }
.guide.danger { stroke: #e74c3c; }

.bar {
  opacity: 0.42;
  rx: 2;
}

.bar.blue { fill: #3498db; }

.viz-meta,
.legend-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  min-height: 20px;
  color: var(--text-secondary);
  font-size: 12px;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
  margin-left: 2px;
}

.dot.blue { background: #3498db; }
.dot.red { background: #e74c3c; }
.dot.purple { background: #8e44ad; }
.dot.orange { background: #e67e22; }
.dot.green { background: #27ae60; }
.dot.amber { background: #f39c12; }

.error-box {
  background-color: #fdecea;
  color: #c62828;
  padding: 12px 16px;
  border-radius: 6px;
  margin-top: 16px;
  font-size: 14px;
  border: 1px solid #ef9a9a;
}

.stats-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 16px;
  font-size: 14px;
}

.stats-table th, .stats-table td {
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  text-align: left;
}

.stats-table th {
  background-color: #f8f9fa;
  font-weight: 600;
  color: var(--text-color);
}

.stats-table tbody tr:nth-child(even) {
  background-color: #fcfcfc;
}

.stats-table .improve {
  color: #27ae60;
  font-weight: 600;
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Toggle Switch */
.toggle {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 24px;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #ccc;
  -webkit-transition: .4s;
  transition: .4s;
  border-radius: 24px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 4px;
  bottom: 4px;
  background-color: white;
  -webkit-transition: .4s;
  transition: .4s;
  border-radius: 50%;
}

input:checked + .slider {
  background-color: var(--primary-color);
}

input:focus + .slider {
  box-shadow: 0 0 1px var(--primary-color);
}

input:checked + .slider:before {
  -webkit-transform: translateX(16px);
  -ms-transform: translateX(16px);
  transform: translateX(16px);
}

@media (max-width: 900px) {
  .twin-visual-grid {
    grid-template-columns: 1fr;
  }

  .mini-chart {
    height: 160px;
  }
}
</style>
