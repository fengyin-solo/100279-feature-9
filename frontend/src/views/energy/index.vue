<template>
  <section class="page" data-module="energy">
    <header class="page-head">
      <div>
        <h2>能耗监测管理</h2>
        <p class="page-desc">按设备大类汇总电耗与油耗，超标排名靠前，可下钻到单台设备的班次抄表明细；数据与下方流水台账同源。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记能耗记录</button>
        <button class="btn" type="button" @click="exportRows">导出能耗监测清单</button>
      </div>
    </header>

    <!-- ================= 能耗监测钻取视图 ================= -->
    <div class="monitor-panel">
      <div class="monitor-head">
        <h3>能耗监测视图</h3>
        <div class="period-bar" role="group" aria-label="统计周期">
          <button
            v-for="item in periods"
            :key="item"
            type="button"
            class="chip"
            :class="{ active: period === item }"
            @click="switchPeriod(item)"
          >
            {{ item }}
          </button>
        </div>
      </div>

      <div class="monitor-stat-row">
        <article class="monitor-stat">
          <span class="monitor-stat-label">监测设备</span>
          <strong>{{ monitorTotals.deviceCount ?? 0 }}</strong>
          <span class="monitor-stat-unit">台</span>
        </article>
        <article class="monitor-stat">
          <span class="monitor-stat-label">电耗合计</span>
          <strong>{{ formatNum(monitorTotals.powerTotal) }}</strong>
          <span class="monitor-stat-unit">度</span>
        </article>
        <article class="monitor-stat">
          <span class="monitor-stat-label">油耗合计</span>
          <strong>{{ formatNum(monitorTotals.fuelTotal) }}</strong>
          <span class="monitor-stat-unit">升</span>
        </article>
        <article class="monitor-stat warn">
          <span class="monitor-stat-label">超标设备</span>
          <strong>{{ monitorTotals.overDeviceCount ?? 0 }}</strong>
          <span class="monitor-stat-unit">台</span>
        </article>
        <article class="monitor-stat">
          <span class="monitor-stat-label">当班未抄表</span>
          <strong>{{ monitorTotals.missingReadingCount ?? 0 }}</strong>
          <span class="monitor-stat-unit">班次</span>
        </article>
        <article class="monitor-stat">
          <span class="monitor-stat-label">抄表人/时段缺失</span>
          <strong>{{ monitorTotals.issueDeviceCount ?? 0 }}</strong>
          <span class="monitor-stat-unit">台</span>
        </article>
      </div>

      <p v-if="monitorNote" class="monitor-note">{{ monitorNote }}</p>
      <p v-if="monitorError" class="error-text">{{ monitorError }}</p>

      <!-- 大类层 -->
      <table v-if="!activeCategory" class="data-table monitor-table">
        <thead>
          <tr>
            <th class="col-rank">排名</th>
            <th>设备大类</th>
            <th>设备数</th>
            <th>电耗合计（度）</th>
            <th class="col-rank">电耗排名</th>
            <th>油耗合计（升）</th>
            <th class="col-rank">油耗排名</th>
            <th>超标设备</th>
            <th>数据质量</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="cat in categories"
            :key="cat.category"
            class="category-row"
            :class="{ 'row-over': cat.overLimit }"
            @click="drillIn(cat.category)"
          >
            <td class="col-rank">
              <span class="rank-badge" :class="{ 'rank-over': cat.overLimit }">{{ cat.rank }}</span>
            </td>
            <td class="cell-strong">{{ cat.category }}</td>
            <td>{{ cat.deviceCount }}</td>
            <td>
              <span v-if="!cat.powerApplicable" class="cell-na">不适用</span>
              <span v-else :class="{ 'num-over': cat.overLimit }">{{ formatNum(cat.powerTotal) }}</span>
            </td>
            <td class="col-rank">{{ cat.powerRank ?? '—' }}</td>
            <td>
              <span v-if="!cat.fuelApplicable" class="cell-na">不适用</span>
              <span v-else :class="{ 'num-over': cat.overLimit }">{{ formatNum(cat.fuelTotal) }}</span>
            </td>
            <td class="col-rank">{{ cat.fuelRank ?? '—' }}</td>
            <td>
              <span v-if="cat.overDeviceCount" class="tag tag-over">{{ cat.overDeviceCount }} 台超标</span>
              <span v-else class="tag tag-ok">正常</span>
            </td>
            <td>
              <span v-if="cat.missingReadingCount" class="tag tag-blank">{{ cat.missingReadingCount }} 班未抄表</span>
              <span v-if="cat.issueDeviceCount" class="tag tag-issue">{{ cat.issueDeviceCount }} 台信息缺失</span>
              <span v-if="!cat.missingReadingCount && !cat.issueDeviceCount" class="tag tag-ok">完整</span>
            </td>
            <td class="col-drill"><button type="button" class="link">查看设备明细 →</button></td>
          </tr>
          <tr v-if="!categories.length">
            <td colspan="10" class="empty-state">当前周期内暂无抄表记录</td>
          </tr>
        </tbody>
      </table>

      <!-- 设备层（下钻） -->
      <div v-else class="drill-panel">
        <div class="drill-head">
          <button type="button" class="btn" @click="drillOut">← 返回大类排名</button>
          <h3>
            {{ activeCategory }} · 单台设备明细
            <span class="drill-limit" v-if="detailPowerLimit != null">电耗阈值 {{ formatNum(detailPowerLimit) }} 度/班</span>
            <span class="drill-limit" v-if="detailFuelLimit != null">油耗阈值 {{ formatNum(detailFuelLimit) }} 升/班</span>
          </h3>
        </div>

        <table class="data-table monitor-table">
          <thead>
            <tr>
              <th class="col-rank">排名</th>
              <th>设备编号</th>
              <th>周期电耗（度）</th>
              <th class="col-rank">电耗排名</th>
              <th>班均电耗</th>
              <th>周期油耗（升）</th>
              <th class="col-rank">油耗排名</th>
              <th>班均油耗</th>
              <th>抄表班次</th>
              <th>状态</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="dev in devices" :key="dev.device">
              <tr
                class="device-row"
                :class="{ 'row-over': dev.overLimit, 'row-issue': dev.hasIssues }"
                @click="toggleDevice(dev.device)"
              >
                <td class="col-rank">
                  <span class="rank-badge" :class="{ 'rank-over': dev.overLimit }">{{ deviceDisplayRank(dev) }}</span>
                </td>
                <td class="cell-strong">{{ dev.device }}</td>
                <td>
                  <span v-if="!dev.powerApplicable" class="cell-na">不适用</span>
                  <span v-else :class="{ 'num-over': dev.overLimit }">{{ formatNum(dev.powerTotal) }}</span>
                </td>
                <td class="col-rank">{{ dev.powerRank ?? '—' }}</td>
                <td>
                  <span v-if="!dev.powerApplicable" class="cell-na">不适用</span>
                  <span v-else>{{ formatNum(dev.powerAvg) }}</span>
                </td>
                <td>
                  <span v-if="!dev.fuelApplicable" class="cell-na">不适用</span>
                  <span v-else :class="{ 'num-over': dev.overLimit }">{{ formatNum(dev.fuelTotal) }}</span>
                </td>
                <td class="col-rank">{{ dev.fuelRank ?? '—' }}</td>
                <td>
                  <span v-if="!dev.fuelApplicable" class="cell-na">不适用</span>
                  <span v-else>{{ formatNum(dev.fuelAvg) }}</span>
                </td>
                <td>{{ dev.readingCount }}</td>
                <td>
                  <span v-if="dev.overLimit" class="tag tag-over">超标</span>
                  <span v-if="dev.missingReadingCount" class="tag tag-blank">{{ dev.missingReadingCount }} 班未抄表</span>
                  <span v-if="issueText(dev)" class="tag tag-issue">{{ issueText(dev) }}</span>
                  <span v-if="!dev.overLimit && !dev.missingReadingCount && !issueText(dev)" class="tag tag-ok">正常</span>
                </td>
                <td class="col-drill"><button type="button" class="link">{{ expandedDevices.includes(dev.device) ? '收起班次' : '班次抄表' }}</button></td>
              </tr>
              <tr v-if="expandedDevices.includes(dev.device)" class="reading-row">
                <td colspan="11">
                  <table class="data-table reading-table">
                    <thead>
                      <tr>
                        <th>记录时段</th>
                        <th>电耗（度）</th>
                        <th>油耗（升）</th>
                        <th>抄表人员</th>
                        <th>记录编号</th>
                        <th>标注</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="r in dev.readings" :key="String(r.sourceId)" :class="{ 'row-over': r.overLimit }">
                        <td>
                          <span v-if="r.period">{{ r.period }}</span>
                          <span v-else class="tag tag-issue">时段缺失</span>
                        </td>
                        <td>
                          <template v-if="!r.powerApplicable"><span class="cell-na">不适用</span></template>
                          <template v-else-if="r.missingPower"><span class="cell-blank">未抄表</span></template>
                          <span v-else :class="{ 'num-over': r.overPower }">{{ formatNum(r.power) }}</span>
                        </td>
                        <td>
                          <template v-if="!r.fuelApplicable"><span class="cell-na">不适用</span></template>
                          <template v-else-if="r.missingFuel"><span class="cell-blank">未抄表</span></template>
                          <span v-else :class="{ 'num-over': r.overFuel }">{{ formatNum(r.fuel) }}</span>
                        </td>
                        <td>
                          <span v-if="r.reader">{{ r.reader }}</span>
                          <span v-else class="tag tag-issue">抄表人缺失</span>
                        </td>
                        <td>{{ r.recordId ?? '—' }}</td>
                        <td>
                          <span v-if="r.overLimit" class="tag tag-over">单班超标</span>
                          <span v-for="issue in r.issues" :key="issue" class="tag tag-issue">{{ issue }}</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ================= 流水台账（与监测视图同源） ================= -->
    <div class="ledger-block">
      <h3 class="block-title">能耗流水台账</h3>
      <form class="filter-bar" @submit.prevent="reload">
        <label v-for="field in filterFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="filters[field]" :placeholder="`按${field}检索`" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无能耗监测数据，可先登记能耗记录</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条能耗监测记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface CategorySummary {
  category: string
  deviceCount: number
  powerTotal: number | null
  fuelTotal: number | null
  powerApplicable: boolean
  fuelApplicable: boolean
  overLimit: boolean
  overDeviceCount: number
  missingReadingCount: number
  issueDeviceCount: number
  rank: number
  powerRank?: number
  fuelRank?: number
}

interface Reading {
  recordId: string | null
  sourceId: number
  period: string | null
  reader: string | null
  power: number | null
  fuel: number | null
  powerApplicable: boolean
  fuelApplicable: boolean
  missingPower: boolean
  missingFuel: boolean
  missingReader: boolean
  missingPeriod: boolean
  overPower: boolean
  overFuel: boolean
  overLimit: boolean
  issues: string[]
}

interface DeviceSummary {
  category: string
  device: string
  powerApplicable: boolean
  fuelApplicable: boolean
  powerTotal: number | null
  fuelTotal: number | null
  powerAvg: number | null
  fuelAvg: number | null
  readingCount: number
  missingReadingCount: number
  issueReadings: Reading[]
  readings: Reading[]
  overLimit: boolean
  hasIssues: boolean
  powerRank?: number
  fuelRank?: number
}

const ENDPOINT = '/api/energy'
const columns = ['记录编号', '设备类型', '设备编号', '电耗度数', '油耗升数', '记录时段', '抄表人员', '能耗状态']
const actions = ['记录能耗', '异常登记', '核实确认']
const filterFields = columns.slice(0, 3)
const periods = ['全日', '近30天', '本月', '本周']

// ---------------- 监测视图状态 ----------------
const period = ref('全日')
const categories = ref<CategorySummary[]>([])
const monitorTotals = ref<Record<string, number>>({})
const monitorError = ref('')
// 下钻状态：换周期只重排数据，不清展开；返回时靠这个把视图停回原来的位置
const activeCategory = ref('')
const expandedDevices = ref<string[]>([])
let detailCache: DeviceSummary[] = []
const devices = computed(() => detailCache)
const detailPowerLimit = ref<number | null>(null)
const detailFuelLimit = ref<number | null>(null)
// 下钻前记录大类表滚动位置，返回时恢复
let restoreScrollTarget = 0

const monitorNote = computed(() => {
  const notes: string[] = []
  if (monitorTotals.value.dedupedCount > 0) {
    notes.push(`已对 ${monitorTotals.value.dedupedCount} 条同设备同班次的重复抄表按最新提交去重`)
  }
  if (monitorTotals.value.missingPeriodCount > 0) {
    notes.push(`${monitorTotals.value.missingPeriodCount} 条记录时段缺失，未计入周期合计`)
  }
  return notes.join('；')
})

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function deviceDisplayRank(dev: DeviceSummary): number {
  // 大类排名顺序即设备行顺序（超标在前），用行序做总排名更直观
  return detailCache.findIndex((item) => item.device === dev.device) + 1
}

function issueText(dev: DeviceSummary): string {
  const set = new Set<string>()
  dev.issueReadings.forEach((r) => r.issues.forEach((i) => set.add(i)))
  return Array.from(set).join('、')
}

async function loadSummary() {
  monitorError.value = ''
  try {
    const response = await request(`${ENDPOINT}/monitor/summary?period=${encodeURIComponent(period.value)}`)
    if (!response.ok) {
      throw new Error(`监测汇总读取失败（${response.status}）`)
    }
    const payload = await response.json()
    categories.value = payload.categories ?? []
    monitorTotals.value = payload.totals ?? {}
    // 正在下钻时，周期切换后按同一大类重新拉明细，展开状态不动
    if (activeCategory.value) {
      await loadDetail(activeCategory.value, { keepScroll: true })
    }
  } catch (error) {
    monitorError.value = error instanceof Error ? error.message : '监测视图加载失败'
  }
}

async function loadDetail(categoryName: string, { keepScroll = false } = {}) {
  monitorError.value = ''
  try {
    const response = await request(
      `${ENDPOINT}/monitor/categories/${encodeURIComponent(categoryName)}?period=${encodeURIComponent(period.value)}`,
    )
    if (!response.ok) {
      throw new Error(`设备明细读取失败（${response.status}）`)
    }
    const payload = await response.json()
    detailCache = payload.devices ?? []
    detailPowerLimit.value = payload.powerLimit ?? null
    detailFuelLimit.value = payload.fuelLimit ?? null
    // 周期切换后，之前展开但本周期没有记录的设备自然收起
    const valid = new Set(detailCache.map((d: DeviceSummary) => d.device))
    expandedDevices.value = expandedDevices.value.filter((name) => valid.has(name))
    if (!keepScroll) {
      // 下钻时把大类表的滚动位置记下来，返回时恢复
      await nextTick()
      window.scrollTo({ top: 0 })
    }
  } catch (error) {
    monitorError.value = error instanceof Error ? error.message : '设备明细加载失败'
  }
}

async function drillIn(categoryName: string) {
  if (activeCategory.value === categoryName) {
    return
  }
  restoreScrollTarget = window.scrollY
  activeCategory.value = categoryName
  expandedDevices.value = []
  await loadDetail(categoryName)
}

async function drillOut() {
  activeCategory.value = ''
  detailCache = []

  // 等大类表渲染回来，再把视图停在下钻前的位置
  await nextTick()
  window.scrollTo({ top: restoreScrollTarget })
}

function toggleDevice(deviceName: string) {
  const index = expandedDevices.value.indexOf(deviceName)
  if (index >= 0) {
    expandedDevices.value.splice(index, 1)
  } else {
    expandedDevices.value.push(deviceName)
  }
}

function switchPeriod(next: string) {
  if (period.value === next) {
    return
  }
  period.value = next
  void loadSummary()
}

// ---------------- 流水台账状态 ----------------
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '能耗记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('能耗监测动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '能耗监测操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('能耗记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '能耗监测列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>

<style scoped>
.monitor-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 18px;
}

.monitor-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.monitor-head h3 {
  margin: 0;
  font-size: 15px;
}

.period-bar {
  display: flex;
  gap: 6px;
}

.chip {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 999px;
  padding: 4px 14px;
  font-size: 12px;
  cursor: pointer;
  color: var(--muted);
}

.chip.active {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}

.monitor-stat-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.monitor-stat {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  background: #fafbfd;
}

.monitor-stat.warn strong {
  color: #b42318;
}

.monitor-stat-label {
  display: block;
  font-size: 12px;
  color: var(--muted);
}

.monitor-stat strong {
  font-size: 22px;
}

.monitor-stat-unit {
  font-size: 12px;
  color: var(--muted);
  margin-left: 2px;
}

.monitor-note {
  font-size: 12px;
  color: #8a6100;
  background: #fff8e1;
  border: 1px solid #f0d98c;
  border-radius: 6px;
  padding: 6px 10px;
  margin: 0 0 10px;
}

.monitor-table th,
.monitor-table td {
  font-size: 12.5px;
}

.col-rank {
  text-align: center;
  width: 52px;
}

.col-drill {
  white-space: nowrap;
  text-align: right;
}

.cell-strong {
  font-weight: 600;
}

.cell-na {
  color: #9aa4b2;
}

.cell-blank {
  display: inline-block;
  background: #eef2f7;
  color: #64748b;
  border: 1px dashed #b6c2d2;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
}

.num-over {
  color: #b42318;
  font-weight: 700;
}

.rank-badge {
  display: inline-block;
  min-width: 22px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #eef2f7;
  color: #475569;
  font-size: 12px;
}

.rank-badge.rank-over {
  background: #b42318;
  color: #fff;
}

.tag {
  display: inline-block;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 12px;
  margin-right: 4px;
  white-space: nowrap;
}

.tag-over {
  background: #fde8e6;
  color: #b42318;
  border: 1px solid #f3bcb5;
}

.tag-issue {
  background: #fff4e5;
  color: #9a5b00;
  border: 1px solid #f2d3a4;
}

.tag-blank {
  background: #eef2f7;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.tag-ok {
  background: #e8f6ee;
  color: #1a7f4b;
  border: 1px solid #aedcc2;
}

.category-row {
  cursor: pointer;
}

.category-row:hover {
  background: #f4f8ff;
}

.row-over {
  background: #fff7f6;
}

.row-over:hover {
  background: #ffefed;
}

.row-issue {
  box-shadow: inset 3px 0 0 #e6a23c;
}

.drill-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.drill-head h3 {
  margin: 0;
  font-size: 15px;
}

.drill-limit {
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
  margin-left: 8px;
}

.device-row {
  cursor: pointer;
}

.device-row:hover {
  background: #f4f8ff;
}

.reading-row > td {
  padding: 0;
  background: #fafbfd;
}

.reading-table {
  margin: 0;
}

.reading-table th,
.reading-table td {
  font-size: 12px;
  padding: 6px 10px;
}

.ledger-block {
  margin-top: 6px;
}

.block-title {
  font-size: 15px;
  margin: 0 0 10px;
}
</style>
