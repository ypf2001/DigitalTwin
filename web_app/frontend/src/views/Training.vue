<template>
  <div>
    <!-- Toast 通知 -->
    <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.msg }}</div>

    <!-- 开始新训练确认弹窗 -->
    <div v-if="showNewTrainModal" class="modal-overlay" @click.self="showNewTrainModal = false">
      <div class="modal-content">
        <h3>⚠️ 开始新训练</h3>
        <p>确定要开始新的训练吗？</p>
        <div class="modal-buttons">
          <button class="btn btn-primary" @click="confirmNewTrain">确认开始</button>
          <button class="btn btn-outline" @click="showNewTrainModal = false">取消</button>
        </div>
      </div>
    </div>

    <!-- 继续训练确认弹窗 -->
    <div v-if="showResumeModal" class="modal-overlay" @click.self="showResumeModal = false">
      <div class="modal-content">
        <h3>⚠️ 继续训练</h3>
        <p>确定要继续当前训练吗？</p>
        <p class="modal-info">
          当前进度：{{ training.timesteps.toLocaleString() }} / {{ params.timesteps.toLocaleString() }} 步
        </p>
        <div class="modal-buttons">
          <button class="btn btn-primary" @click="confirmResume">确认继续</button>
          <button class="btn btn-outline" @click="showResumeModal = false">取消</button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">训练参数设置</div>
      <div class="form-row">
        <div class="form-group">
          <label>训练阶段</label>
          <select v-model="params.stage" class="form-select" :disabled="training.running">
            <option value="EMERGENCE">出苗期 (INI)</option>
            <option value="VEGETATIVE">营养生长期 (DEV)</option>
            <option value="TUBER_INIT">块茎形成期 (DEV)</option>
            <option value="BULKING">块茎膨大期 (MID)</option>
            <option value="STARCH_ACCUMULATION">淀粉积累期 (LATE)</option>
            <option value="MATURATION">成熟期 (LATE)</option>
          </select>
        </div>
        <div class="form-group">
          <label>训练步数</label>
          <div class="input-with-unit">
            <input type="number" v-model.number="params.timesteps" class="form-input" min="1000" max="500000" step="1000" style="width:140px" />
            <span class="unit">步</span>
          </div>
          <small class="hint">目标：120,000 步</small>
        </div>
        <div class="form-group">
          <label>续训模式</label>
          <div class="toggle-row">
            <label class="toggle">
              <input type="checkbox" v-model="params.resume" />
              <span class="slider"></span>
            </label>
            <span style="font-size:13px;color:var(--text-secondary)">从已有模型继续</span>
          </div>
        </div>
      </div>
      <div style="margin-top:16px;display:flex;gap:12px;align-items:center">
        <button v-if="!training.running" class="btn btn-primary" @click="showNewTrainModal = true" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '启动中...' : '▶ 开始新训练' }}
        </button>
        <button v-else class="btn btn-danger" @click="handleStop">
          ⏹ 停止训练
        </button>
      </div>
      <div v-if="error" class="error-box" style="margin-top:12px">{{ error }}</div>
      <div v-if="training.error" class="error-box" style="margin-top:12px">{{ training.error }}</div>
      <div v-if="message" class="success-box" style="margin-top:12px">{{ message }}</div>
    </div>

    <!-- 训练进度列表 -->
    <div class="card" style="margin-top:16px">
      <div class="card-title">
        <span>📈 训练进度</span>
        <span v-if="training.running" class="training-badge">
          <span class="pulse-dot"></span> 训练中
        </span>
        <span v-else-if="training.progress >= 100 && training.timesteps >= training.target_steps" class="completed-badge">✓ 完成</span>
        <span v-else-if="training.timesteps > 0" class="stopped-badge">⏹ 已中断</span>
        <span v-else class="idle-badge">○ 待机</span>
      </div>

      <!-- 进度表格 - 多阶段显示 -->
      <table class="progress-table">
        <thead>
          <tr>
            <th>阶段</th>
            <th>目标步数</th>
            <th>当前步数</th>
            <th style="width:180px">进度</th>
            <th>状态</th>
            <th style="width:120px">操作</th>
          </tr>
        </thead>
        <tbody>
          <!-- 当前训练进度 -->
          <tr v-if="training.timesteps > 0 || training.running" :class="{ 'running-row': training.running }">
            <td><span class="stage-badge">{{ training.stage ? getStageName(training.stage) : '-' }}</span></td>
            <td>{{ training.running && training.target_steps ? training.target_steps.toLocaleString() : params.timesteps.toLocaleString() }}</td>
            <td>{{ training.timesteps ? training.timesteps.toLocaleString() : '0' }}</td>
            <td>
              <div class="table-progress">
                <div class="table-progress-bar" :class="{ animating: training.running }"
                     :style="{ width: Math.max(2, training.progress) + '%' }"></div>
                <span class="table-progress-text">{{ training.progress.toFixed(1) }}%</span>
              </div>
            </td>
            <td>
              <span v-if="training.running" class="status-running">● 运行中</span>
              <span v-else-if="training.progress >= 100 && training.timesteps >= (training.running ? training.target_steps : params.timesteps)" class="status-done">✓ 完成</span>
              <span v-else-if="training.timesteps > 0" class="status-stopped">⏹ 已中断</span>
              <span v-else class="status-idle">○ 待机</span>
            </td>
            <td>
              <button v-if="training.running" class="btn btn-sm btn-danger" @click="handleStop" :disabled="loading">
                ⏹ 停止
              </button>
              <button v-else-if="training.timesteps > 0 && training.progress < 100" class="btn btn-sm btn-success" @click="resumeTraining" :disabled="loading">
                🔄 继续
              </button>
              <span v-else class="status-done">✓ 完成</span>
            </td>
          </tr>
          <!-- 空状态 -->
          <tr v-else>
            <td colspan="6" style="text-align:center;color:var(--text-secondary);padding:24px">
              暂无训练记录，点击上方"开始新训练"启动
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 时间信息 -->
      <div v-if="training.start_time" class="time-info">
        <span>⏱️ 已用时间: {{ formatDuration(elapsedTime) }}</span>
        <span v-if="training.running">📅 开始于: {{ training.start_time }}</span>
      </div>
    </div>

    <!-- 模型列表 -->
    <div class="card" style="margin-top:16px">
      <div class="card-title">已训练模型</div>
      <div v-if="models.length === 0" style="color:var(--text-secondary);padding:16px 0">
        暂无已训练的模型
      </div>
      <template v-else>
        <!-- 未完成 -->
        <div v-if="incompleteModels.length > 0" style="margin-bottom:20px">
          <div class="card-title" style="font-size:14px;color:var(--warning);display:flex;align-items:center;gap:12px">
            <span>⏳ 训练中 / 未完成</span>
            <button v-if="!uploading" class="btn btn-sm btn-outline" @click="checkAllIncomplete">☐ 全选</button>
          </div>
          <div style="overflow:auto;max-height:300px">
            <table class="stats-table">
              <thead>
                <tr><th style="width:30px">☐</th><th>模型名称</th><th>阶段</th><th>步数</th><th>大小</th><th>更新时间</th><th>云端</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="m in incompleteModels" :key="m.name">
                  <td><input type="checkbox" :checked="checkedModels.has(m.name)" :disabled="m.in_cloud" @change="toggleCheck(m.name)" /></td>
                  <td><code>{{ m.name }}</code></td>
                  <td>{{ m.stage }}</td>
                  <td>{{ m.steps }}</td>
                  <td>{{ m.size_mb }} MB</td>
                  <td>{{ m.mtime }}</td>
                  <td><span v-if="m.in_cloud" style="color:var(--success)">☁️</span><span v-else style="color:#ccc">—</span></td>
                  <td><button class="btn btn-sm btn-success" @click="selectModel(m)" :disabled="training.running">继续训练</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <!-- 已完成 -->
        <div v-if="completedModels.length > 0">
          <div class="card-title" style="font-size:14px;color:var(--success);display:flex;align-items:center;gap:12px;flex-wrap:wrap">
            <span>✓ 已完成 (120,000 步)</span>
            <button v-if="!uploading" class="btn btn-sm" style="background:#4caf50;color:#fff" @click="checkAllCompleted">☐ 全选</button>
            <button v-if="!uploading" class="btn btn-sm" style="background:#1976d2;color:#fff" @click="uploadChecked" :disabled="checkedModels.size === 0">☁️ 上传选中</button>
            <button v-if="uploading" class="btn btn-sm btn-danger" @click="stopUploading">⏹ 停止上传</button>
          </div>
          <div v-if="uploading" style="margin:8px 0;background:#e9ecef;border-radius:6px;height:16px;overflow:hidden">
            <div :style="{ width: uploadPct + '%', height:'100%', background:'linear-gradient(90deg,#4caf50,#8bc34a)', transition:'width .3s' }"></div>
          </div>
          <div v-if="uploading" style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">
            {{ uploadCurrent }} / {{ uploadTotal }}
          </div>
          <div style="overflow:auto;max-height:300px">
            <table class="stats-table">
              <thead>
                <tr><th style="width:30px">☐</th><th>模型名称</th><th>阶段</th><th>步数</th><th>大小</th><th>更新时间</th><th>云端</th></tr>
              </thead>
              <tbody>
                <tr v-for="m in completedModels" :key="m.name">
                  <td><input type="checkbox" :checked="checkedModels.has(m.name)" :disabled="m.in_cloud" @change="toggleCheck(m.name)" /></td>
                  <td><code>{{ m.name }}</code></td>
                  <td>{{ m.stage }}</td>
                  <td>{{ m.steps }}</td>
                  <td>{{ m.size_mb }} MB</td>
                  <td>{{ m.mtime }}</td>
                  <td><span v-if="m.in_cloud" style="color:var(--success)">☁️</span><span v-else style="color:#ccc">—</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>

    <!-- 训练日志 -->
    <div v-if="training.logLines && training.logLines.length > 0" class="card" style="margin-top:16px">
      <div class="card-title">训练日志</div>
      <div class="log-container">
        <div v-for="(line, i) in training.logLines" :key="i" class="log-line">{{ line }}</div>
      </div>
    </div>

    <!-- SAC 参数参考 -->
    <div class="card" style="margin-top:16px">
      <div class="card-title">SAC 算法参数说明</div>
      <table class="stats-table">
        <tr><th>参数</th><th>说明</th></tr>
        <tr><td>learning_rate</td><td>学习率，控制策略更新的步长</td></tr>
        <tr><td>buffer_size</td><td>经验回放缓冲区大小</td></tr>
        <tr><td>batch_size</td><td>每次更新的批量大小</td></tr>
        <tr><td>gamma</td><td>折扣因子，影响长期奖励权重</td></tr>
        <tr><td>tau</td><td>目标网络更新系数</td></tr>
        <tr><td>ent_coef</td><td>熵正则化系数，探索与利用平衡</td></tr>
      </table>
      <div style="margin-top:12px;font-size:13px;color:var(--text-secondary)">
        💡 提示：训练过程中可以随时点击"停止训练"按钮，模型会自动保存。
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, computed, onMounted } from 'vue'
import { getTrainingStatus, startTraining, stopTraining, getTrainingModels, uploadModels, uploadSelected, stopUpload, getUploadProgress } from '../api/index.js'

export default {
  name: 'Training',
  setup() {
    const params = reactive({ stage: 'BULKING', timesteps: 120000, resume: false })
    const loading = ref(false)
    const error = ref('')
    const message = ref('')
    const models = ref([])
    const uploadMsg = ref('')
    const uploading = ref(false)
    const uploadPct = ref(0)
    const uploadCurrent = ref('0')
    const uploadTotal = ref('0')
    const checkedModels = reactive(new Set())
    let uploadPollTimer = null
    const toast = reactive({ show: false, msg: '', type: 'success', timer: null })
    const incompleteModels = computed(() => models.value.filter(m => (m.steps_num || 0) < 120000))
    const completedModels = computed(() => models.value.filter(m => (m.steps_num || 0) >= 120000))
    const training = reactive({
      running: false,
      stage: null,
      timesteps: 0,
      target_steps: 0,
      progress: 0,
      start_time: null,
      logLines: [],
      error: null,
    })
    let pollTimer = null
    let elapsedTimer = null
    const elapsedTime = ref(0)
    const trainingStarted = ref(false)

    // 弹窗状态
    const showNewTrainModal = ref(false)
    const showResumeModal = ref(false)

    const stageNames = {
      'EMERGENCE': '出苗期',
      'VEGETATIVE': '营养生长期',
      'TUBER_INIT': '块茎形成期',
      'BULKING': '块茎膨大期',
      'STARCH_ACCUMULATION': '淀粉积累期',
      'MATURATION': '成熟期',
    }

    function getStageName(stage) {
      return stageNames[stage] || stage
    }

    function formatDuration(seconds) {
      if (!seconds || seconds <= 0) return '0:00'
      const mins = Math.floor(seconds / 60)
      const secs = Math.floor(seconds % 60)
      const hours = Math.floor(mins / 60)
      const displayMins = mins % 60
      if (hours > 0) {
        return `${hours}:${String(displayMins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
      }
      return `${mins}:${String(secs).padStart(2, '0')}`
    }

    function updateElapsed() {
      if (training.start_time && training.running) {
        const start = new Date(training.start_time).getTime()
        const now = Date.now()
        elapsedTime.value = Math.floor((now - start) / 1000)
      } else if (!training.running && training.start_time) {
        // 保持最终时间
      } else {
        elapsedTime.value = 0
      }
    }

    async function refreshStatus() {
      try {
        const status = await getTrainingStatus()
        training.running = status.running
        training.stage = status.stage
        training.timesteps = status.timesteps
        training.target_steps = status.target_steps
        training.progress = status.progress
        training.start_time = status.start_time
        training.logLines = status.log_lines || []
        training.error = status.error
        updateElapsed()
      } catch (e) {
        console.error('Failed to get training status:', e)
      }
    }

    async function loadModels() {
      try {
        const info = await getTrainingModels()
        models.value = info.models || []
      } catch (e) {
        console.error('Failed to load models:', e)
      }
    }

    async function confirmNewTrain() {
      showNewTrainModal.value = false
      loading.value = true
      error.value = ''
      message.value = ''
      try {
        // 不使用 resume，清空历史
        const res = await startTraining({
          stage: params.stage,
          timesteps: params.timesteps,
          resume: false,
        })
        if (res.success) {
          message.value = res.message
          trainingStarted.value = true
          await refreshStatus()
          startPolling()
        } else {
          error.value = res.error || '启动失败'
        }
      } catch (e) {
        error.value = e.message || '网络错误'
      } finally {
        loading.value = false
      }
    }

    async function confirmResume() {
      showResumeModal.value = false
      loading.value = true
      error.value = ''
      message.value = ''
      try {
        // 使用 resume 继续训练
        const res = await startTraining({
          stage: training.stage || params.stage,
          timesteps: params.timesteps,
          resume: true,
        })
        if (res.success) {
          message.value = res.message
          trainingStarted.value = true
          await refreshStatus()
          startPolling()
        } else {
          error.value = res.error || '启动失败'
        }
      } catch (e) {
        error.value = e.message || '网络错误'
      } finally {
        loading.value = false
      }
    }

    function resumeTraining() {
      showResumeModal.value = true
    }

    function showToast(msg, type = 'success') {
      if (toast.timer) clearTimeout(toast.timer)
      toast.show = true; toast.msg = msg; toast.type = type
      toast.timer = setTimeout(() => { toast.show = false }, 3000)
    }

    function toggleCheck(name) {
      if (checkedModels.has(name)) { checkedModels.delete(name) } else { checkedModels.add(name) }
    }

    function checkAllCompleted() {
      const names = completedModels.value.filter(m => !m.in_cloud).map(m => m.name)
      names.forEach(n => checkedModels.add(n))
    }

    function checkAllIncomplete() {
      const names = incompleteModels.value.filter(m => !m.in_cloud).map(m => m.name)
      names.forEach(n => checkedModels.add(n))
    }

    function uncheckAll() { checkedModels.clear() }

    async function uploadChecked() {
      const names = [...checkedModels].filter(n => {
        const m = models.value.find(x => x.name === n)
        return m && !m.in_cloud
      })
      if (names.length === 0) { showToast('请勾选未上传的模型', 'error'); return }
      uploading.value = true
      uploadPct.value = 0
      uploadCurrent.value = '0'
      uploadTotal.value = '0'
      try {
        const res = await uploadSelected(names)
        if (!res.success) { showToast(res.error || '启动失败', 'error'); uploading.value = false; return }
        startUploadPolling()
      } catch (e) { showToast(e.message || '网络错误', 'error'); uploading.value = false }
    }

    async function stopUploading() {
      try { await stopUpload(); showToast('上传已停止') } catch (e) { showToast(e.message || '停止失败', 'error') }
    }

    function startUploadPolling() {
      if (uploadPollTimer) clearInterval(uploadPollTimer)
      uploadPollTimer = setInterval(async () => {
        try {
          const p = await getUploadProgress()
          uploadPct.value = Math.min(100, p.total > 0 ? ((p.processed || p.uploaded + p.skipped) / p.total * 100) : 0)
          uploadCurrent.value = (p.processed || p.uploaded + p.skipped).toString()
          uploadTotal.value = p.total.toString()
          if (p.done) {
            clearInterval(uploadPollTimer)
            uploadPollTimer = null
            uploading.value = false
            checkedModels.clear()
            await loadModels()
            const parts = []
            if (p.uploaded > 0) parts.push(`新增 ${p.uploaded} 个`)
            if (p.skipped > 0) parts.push(`跳过 ${p.skipped} 个`)
            if (p.errors && p.errors.length > 0) parts.push(`错误 ${p.errors.length} 个`)
            showToast(parts.length > 0 ? '✅ ' + parts.join('，') : '✅ 上传完成')
          }
        } catch (_) {}
      }, 500)
    }

    async function handleStop() {
      stopPolling()
      try {
        const res = await stopTraining()
        if (res.success) {
          message.value = '训练已停止'
          error.value = ''
          await refreshStatus()
          await loadModels()
        } else {
          error.value = res.error || '停止失败'
          if (training.running) startPolling()
        }
      } catch (e) {
        error.value = e.message || '网络错误'
        if (training.running) startPolling()
      }
    }

    function startPolling() {
      stopPolling()
      pollTimer = setInterval(async () => {
        await refreshStatus()
        if (!training.running && pollTimer) {
          stopPolling()
          await loadModels()
          if (training.error) {
            error.value = training.error
          } else if (!message.value) {
            message.value = '训练已完成，模型已保存'
          }
        }
      }, 3000)
      // 额外计时器更新已用时间
      elapsedTimer = setInterval(() => {
        updateElapsed()
      }, 1000)
    }

    function selectModel(model) {
      if (training.running) {
        error.value = '训练进行中，请先停止'
        return
      }
      // 从模型名解析 stage（sac_mid_6000_steps → BULKING）
      const name = model.name
      const stageMap = { ini: 'EMERGENCE', dev: 'VEGETATIVE', mid: 'BULKING', late: 'STARCH_ACCUMULATION' }
      let stage = params.stage
      for (const [short, full] of Object.entries(stageMap)) {
        if (name.includes('_' + short + '_') || name.includes('_' + short) || name === 'best_model') {
          stage = full; break
        }
      }
      params.stage = stage
      loading.value = true
      error.value = ''
      message.value = ''
      startTraining({ stage, timesteps: params.timesteps, resume: true, load_model: name })
        .then(res => {
          if (res.success) {
            message.value = res.message
            trainingStarted.value = true
            refreshStatus().then(() => startPolling())
          } else { error.value = res.error || '启动失败' }
        })
        .catch(e => { error.value = e.message || '网络错误' })
        .finally(() => { loading.value = false })
    }

    function stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
      if (elapsedTimer) {
        clearInterval(elapsedTimer)
        elapsedTimer = null
      }
    }

    onMounted(async () => {
      await refreshStatus()
      await loadModels()
      if (training.running) {
        trainingStarted.value = true
        startPolling()
      } else {
        // 训练未运行，停止计时器
        stopPolling()
      }
    })

    // 不要在卸载时停止轮询，保持后台训练状态
    // onUnmounted(() => {
    //   stopPolling()
    // })

    return {
      params,
      loading,
      error,
      message,
      models,
      incompleteModels,
      completedModels,
      training,
      toast,
      showToast,
      uploadMsg,
      uploading,
      uploadPct,
      uploadCurrent,
      uploadTotal,
      checkedModels,
      toggleCheck,
      checkAllCompleted,
      checkAllIncomplete,
      uncheckAll,
      uploadChecked,
      stopUploading,
      elapsedTime,
      showNewTrainModal,
      showResumeModal,
      confirmNewTrain,
      confirmResume,
      resumeTraining,
      handleStop,
      selectModel,
      refreshStatus,
      getStageName,
      formatDuration,
    }
  },
}
</script>

<style scoped>
/* 弹窗样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: #fff;
  padding: 24px;
  border-radius: 12px;
  max-width: 400px;
  width: 90%;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.modal-content h3 { margin: 0 0 12px 0; color: #333; font-size: 18px; }
.modal-content p { margin: 8px 0; color: #666; font-size: 14px; }

.modal-info {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
}

.modal-buttons {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  justify-content: flex-end;
}

/* 状态徽章 */
.training-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: linear-gradient(135deg, #00c6ff, #0072ff);
  color: white;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  margin-left: 12px;
  animation: badgePulse 2s ease infinite;
}

.completed-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: linear-gradient(135deg, #11998e, #38ef7d);
  color: white;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  margin-left: 12px;
}

.stopped-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: #6c757d;
  color: white;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  margin-left: 12px;
}

.idle-badge {
  font-size: 12px;
  padding: 2px 8px;
  background: #f5f5f5;
  color: #9e9e9e;
  border-radius: 4px;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  background: white;
  border-radius: 50%;
  animation: pulse 1.5s ease infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.3); opacity: 0.7; }
}

@keyframes badgePulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(0,114,255,0.4); }
  50% { box-shadow: 0 0 0 8px rgba(0,114,255,0); }
}

/* 进度表格 */
.progress-table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 13px;
}

.progress-table th,
.progress-table td {
  padding: 10px 8px;
  text-align: left;
  border-bottom: 1px solid #eee;
}

.progress-table th {
  background: #f8f9fa;
  font-weight: 600;
  color: var(--text-secondary);
}

.progress-table tbody tr:hover { background: #fafafa; }

.stage-badge {
  display: inline-block;
  padding: 2px 8px;
  background: #e8f5e9;
  color: #2e7d32;
  border-radius: 4px;
  font-size: 12px;
}

.table-progress {
  position: relative;
  height: 20px;
  background: #e9ecef;
  border-radius: 10px;
  overflow: hidden;
}

.table-progress-bar {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  background: linear-gradient(90deg, #4caf50, #8bc34a);
  border-radius: 10px;
  transition: width 0.3s ease;
}

.table-progress-bar.animating {
  background: linear-gradient(90deg, #667eea, #764ba2);
}

.table-progress-bar.animating::after {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.3) 50%, transparent 100%);
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.table-progress-text {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
  font-weight: 600;
  color: #333;
}

.status-running { color: #4caf50; font-weight: 600; }
.status-done { color: #2196f3; font-weight: 600; }
.status-stopped { color: #ff9800; font-weight: 600; }
.status-idle { color: #9e9e9e; }

.time-info {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #eee;
  font-size: 12px;
  color: var(--text-secondary);
}

.running-row { background: rgba(76, 175, 80, 0.08); }

/* 日志 */
.log-container {
  max-height: 300px;
  overflow-y: auto;
  background: #1e1e1e;
  border-radius: 6px;
  padding: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}

.log-line {
  color: #d4d4d4;
  line-height: 1.6;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.log-line:hover { white-space: normal; overflow: visible; }

/* 通用 */
.success-box {
  padding: 10px 16px;
  background: #e8f5e9;
  color: #2e7d32;
  border-radius: 6px;
  font-size: 14px;
}

.input-with-unit { display: flex; align-items: center; gap: 8px; }
.unit { color: var(--text-secondary); font-size: 14px; }

.hint {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

/* 按钮 */
.btn-danger {
  background: #e74c3c;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.btn-danger:hover { background: #c0392b; }

.btn-success {
  background: #4caf50;
  color: white;
  border: none;
}

.btn-success:hover { background: #45a049; }
.btn-success:disabled { background: #ccc; cursor: not-allowed; }

.btn-sm { padding: 4px 10px; font-size: 12px; border-radius: 4px; }
.btn-sm.btn-danger { background: #f44336; color: white; border: none; }
.btn-sm.btn-danger:hover { background: #d32f2f; }
.btn-sm.btn-success { background: #4caf50; color: white; border: none; }
.btn-sm.btn-success:hover { background: #45a049; }

/* Toast */
.toast {
  position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
  padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 500;
  z-index: 1001; box-shadow: 0 4px 16px rgba(0,0,0,.15);
  animation: toastIn .3s ease;
}
.toast.success { background: #e8f5e9; color: #2e7d32; }
.toast.error { background: #fdecea; color: #c62828; }
@keyframes toastIn { from { opacity: 0; transform: translateX(-50%) translateY(-12px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
</style>
