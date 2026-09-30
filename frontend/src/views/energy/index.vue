<template>
  <section ref="rootRef" class="page energy-page" data-module="energy">
    <header class="page-head">
      <div>
        <h2>能耗监测</h2>
        <p class="page-desc">按设备大类汇总电耗与油耗，超标靠前；点开大类钻到单台设备与班次抄表。台账与视图共用同一份去重流水。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出台账</button>
      </div>
    </header>

    <!-- 账期 + 视图切换：换账期只重排，不清展开/钻取状态 -->
    <div class="control-bar">
      <div class="segmented" role="group" aria-label="统计周期">
        <button
          v-for="item in periodOptions"
          :key="item.value"
          type="button"
          class="seg-item"
          :class="{ active: period === item.value }"
          @click="changePeriod(item.value)"
        >
          {{ item.short }}
        </button>
      </div>
      <div class="segmented" role="group" aria-label="视图">
        <button type="button" class="seg-item" :class="{ active: tab === 'monitor' }" @click="tab = 'monitor'">监测视图</button>
        <button type="button" class="seg-item" :class="{ active: tab === 'ledger' }" @click="tab = 'ledger'">能耗台账</button>
      </div>
    </div>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">电耗合计（度）</span>
        <strong class="stat-value">{{ fmt(summary.elec_total) }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">油耗合计（升）</span>
        <strong class="stat-value">{{ fmt(summary.fuel_total) }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">整班漏抄（空白格）</span>
        <strong class="stat-value" :class="{ warn: summary.blank_shift_count > 0 }">{{ summary.blank_shift_count ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">数据问题（缺人/缺时段）</span>
        <strong class="stat-value" :class="{ warn: issueTotal > 0 }">{{ issueTotal }}</strong>
      </article>
    </div>

    <p class="dedup-note">
      本期原始抄表 {{ summary.raw_count ?? 0 }} 条，同设备同班重复提交已自动合并
      <strong>{{ summary.duplicate_count ?? 0 }}</strong> 条（保留提交时间最新的一条）；
      未抄表的班次显示为<span class="blank-cell-inline">空白</span>，不计入合计。
    </p>

    <!-- ============================ 监测视图 ============================ -->
    <template v-if="tab === 'monitor'">
      <!-- 第一层：设备大类 -->
      <template v-if="!selectedCategory">
        <table class="data-table">
          <thead>
            <tr>
              <th class="col-rank">排名（电/油）</th>
              <th>设备大类</th>
              <th class="col-num">电耗合计（度）</th>
              <th class="col-num">油耗合计（升）</th>
              <th class="col-num">抄表条数</th>
              <th class="col-num">漏抄班次</th>
              <th>超标情况</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in categories" :key="row.category" :class="{ 'row-over': row.is_over }">
              <td class="col-rank">{{ rankText(row.elec_rank) }} / {{ rankText(row.fuel_rank) }}</td>
              <td class="cell-strong">
                <span v-if="row.is_over" class="flag-over" title="存在超标班次">超标</span>
                {{ row.category_label }}
              </td>
              <td class="col-num">{{ fmt(row.elec_total) }}</td>
              <td class="col-num">{{ fmt(row.fuel_total) }}</td>
              <td class="col-num">{{ row.reading_count }}</td>
              <td class="col-num">
                <span v-if="row.blank_shift_count" class="warn-text">{{ row.blank_shift_count }} 个空白</span>
                <span v-else>—</span>
              </td>
              <td>
                <span v-for="over in row.over_items" :key="over.metric" class="over-pill">
                  {{ over.metric_label }} {{ over.count }} 班超
                  <em>（最高 {{ over.worst_device }} {{ fmt(over.worst_value) }}，{{ over.ratio }}× 上限）</em>
                </span>
                <span v-if="!row.over_items.length" class="muted">未超标</span>
              </td>
              <td class="row-actions">
                <button class="link" type="button" @click="drillInto(row.category)">钻取明细 →</button>
              </td>
            </tr>
            <tr v-if="!categories.length">
              <td colspan="8" class="empty-state">该账期暂无抄表记录</td>
            </tr>
          </tbody>
        </table>
      </template>

      <!-- 第二层：单台设备 -->
      <template v-else>
        <div class="breadcrumb">
          <button class="link" type="button" @click="backToCategories">← 返回设备大类</button>
          <span class="crumb-sep">/</span>
          <strong>{{ categoryDetail?.category_label ?? selectedCategory }}</strong>
          <span class="muted">（超标设备靠前，点设备行展开班次抄表）</span>
        </div>

        <table class="data-table">
          <thead>
            <tr>
              <th class="col-rank">#</th>
              <th>设备编号</th>
              <th class="col-num">电耗合计（度）</th>
              <th class="col-num">油耗合计（升）</th>
              <th class="col-num">抄表条数</th>
              <th class="col-num">漏抄班次</th>
              <th class="col-num">缺抄表人</th>
              <th>超标情况</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="dev in categoryDetail?.devices ?? []" :key="dev.device">
              <tr
                class="device-row"
                :class="{ 'row-over': dev.is_over, expanded: expandedDevices.includes(dev.device) }"
              >
                <td class="col-rank">{{ dev.rank }}</td>
                <td class="cell-strong">{{ dev.device }}</td>
                <td class="col-num">{{ fmt(dev.elec_total) }}</td>
                <td class="col-num">{{ fmt(dev.fuel_total) }}</td>
                <td class="col-num">{{ dev.reading_count }}</td>
                <td class="col-num">
                  <span v-if="dev.blank_shift_count" class="warn-text">{{ dev.blank_shift_count }} 个空白</span>
                  <span v-else>—</span>
                </td>
                <td class="col-num">
                  <span v-if="dev.missing_reader_count" class="warn-text">{{ dev.missing_reader_count }}</span>
                  <span v-else>—</span>
                </td>
                <td>
                  <span v-for="over in dev.over_items" :key="over.metric" class="over-pill">
                    {{ over.metric_label }} {{ over.count }} 班超，最高 {{ fmt(over.worst_value) }}（{{ over.ratio }}×）
                  </span>
                  <span v-if="!dev.over_items.length" class="muted">未超标</span>
                </td>
                <td class="row-actions">
                  <button class="link" type="button" @click="toggleDevice(dev.device)">
                    {{ expandedDevices.includes(dev.device) ? '收起班次' : '展开班次' }}
                  </button>
                </td>
              </tr>
              <tr v-if="expandedDevices.includes(dev.device)" class="reading-row">
                <td colspan="9">
                  <table class="sub-table">
                    <thead>
                      <tr>
                        <th>记录时段</th>
                        <th class="col-num">电耗度数</th>
                        <th class="col-num">油耗升数</th>
                        <th>抄表人员</th>
                        <th>提交时间</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="rd in dev.readings" :key="String(rd.id)" :class="{ 'row-reading-over': rd.over_metrics?.length }">
                        <td>{{ rd.记录时段 ?? '—' }}</td>
                        <td class="col-num">
                          <span v-if="rd.电耗度数 === null || rd.电耗度数 === undefined" class="blank-cell">空白（未抄）</span>
                          <span v-else :class="{ 'num-over': rd.over_metrics?.includes('elec') }">{{ fmt(rd.电耗度数) }}</span>
                        </td>
                        <td class="col-num">
                          <span v-if="rd.油耗升数 === null || rd.油耗升数 === undefined" class="blank-cell">空白（未抄）</span>
                          <span v-else :class="{ 'num-over': rd.over_metrics?.includes('fuel') }">{{ fmt(rd.油耗升数) }}</span>
                        </td>
                        <td>
                          <span v-if="rd.抄表人员">{{ rd.抄表人员 }}</span>
                          <span v-else class="issue-badge">缺抄表人</span>
                        </td>
                        <td class="muted">{{ rd.提交时间 ?? '—' }}</td>
                        <td>
                          <span class="status-tag" :class="statusClass(rd.能耗状态)">{{ rd.能耗状态 }}</span>
                          <span v-if="rd.over_metrics?.length" class="flag-over small">超标</span>
                        </td>
                      </tr>
                      <tr v-if="!dev.readings.length">
                        <td colspan="6" class="empty-state">该设备本账期没有任何抄表记录（全部班次空白）</td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </template>

      <!-- 问题清单：缺抄表人 / 缺记录时段，单独圈出 -->
      <section class="issues-panel">
        <h3>数据质量问题（不参与合计，需补录）</h3>
        <div class="issue-cols">
          <div class="issue-col">
            <h4 class="issue-title">缺抄表人员 · {{ missingReader.length }} 条</h4>
            <ul v-if="missingReader.length" class="issue-list">
              <li v-for="item in missingReader" :key="String(item.id)">
                <span class="issue-device">{{ item.设备类型 }} {{ item.设备编号 }}</span>
                <span class="muted">{{ item.记录时段 ?? '时段缺失' }}</span>
                <span class="muted">电 {{ fmt(item.电耗度数) }} / 油 {{ fmt(item.油耗升数) }}</span>
              </li>
            </ul>
            <p v-else class="muted">没有缺抄表人的记录</p>
          </div>
          <div class="issue-col">
            <h4 class="issue-title">缺记录时段 · {{ missingPeriod.length }} 条</h4>
            <ul v-if="missingPeriod.length" class="issue-list">
              <li v-for="item in missingPeriod" :key="String(item.id)">
                <span class="issue-device">{{ item.设备类型 }} {{ item.设备编号 }}</span>
                <span class="issue-badge">无法归班</span>
                <span class="muted">电 {{ fmt(item.电耗度数) }} / 油 {{ fmt(item.油耗升数) }}</span>
              </li>
            </ul>
            <p v-else class="muted">没有缺时段的记录</p>
          </div>
        </div>
      </section>
    </template>

    <!-- ============================ 能耗台账 ============================ -->
    <template v-else>
      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>关键字（记录编号 / 设备编号）</span>
          <input v-model="filters.keyword" placeholder="如 ENER、QC-104" />
        </label>
        <label class="filter-item">
          <span>能耗状态</span>
          <select v-model="filters.status">
            <option value="">全部</option>
            <option v-for="st in statuses" :key="st" :value="st">{{ st }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
        <span class="muted ledger-hint">台账同样按「重复抄表留最新」去重，账期与监测视图一致。</span>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="String(row.id)">
            <td>{{ row.记录编号 ?? '—' }}</td>
            <td>{{ row.设备类型 ?? '—' }}</td>
            <td>{{ row.设备编号 ?? '—' }}</td>
            <td class="col-num">
              <span v-if="row.电耗度数 === null || row.电耗度数 === undefined" class="blank-cell">空白</span>
              <span v-else>{{ fmt(row.电耗度数) }}</span>
            </td>
            <td class="col-num">
              <span v-if="row.油耗升数 === null || row.油耗升数 === undefined" class="blank-cell">空白</span>
              <span v-else>{{ fmt(row.油耗升数) }}</span>
            </td>
            <td>
              <span v-if="row.记录时段">{{ row.记录时段 }}</span>
              <span v-else class="issue-badge">缺时段</span>
            </td>
            <td>
              <span v-if="row.抄表人员">{{ row.抄表人员 }}</span>
              <span v-else class="issue-badge">缺抄表人</span>
            </td>
            <td><span class="status-tag" :class="statusClass(row.能耗状态)">{{ row.能耗状态 }}</span></td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length" class="empty-state">该账期/条件下暂无台账记录</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ ledgerTotal }} 条去重后抄表记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Num = number | null
interface OverItem {
  metric: 'elec' | 'fuel'
  metric_label: string
  threshold: number
  count: number
  worst_device?: string
  worst_value: number
  worst_shift?: string | null
  ratio: number
}
interface CategoryRow {
  category: string
  category_label: string
  elec_total: Num
  fuel_total: Num
  reading_count: number
  device_count: number
  blank_shift_count: number
  over_items: OverItem[]
  is_over: boolean
  elec_rank: number | null
  fuel_rank: number | null
}
interface Reading {
  id: number | string
  记录编号: string | null
  电耗度数: Num
  油耗升数: Num
  记录时段: string | null
  抄表人员: string | null
  能耗状态: string
  提交时间: string | null
  shift: string | null
  missing_reader: boolean
  over_metrics: ('elec' | 'fuel')[] | null
}
interface DeviceRow {
  device: string
  elec_total: Num
  fuel_total: Num
  reading_count: number
  blank_shift_count: number
  missing_reader_count: number
  is_over: boolean
  over_items: OverItem[]
  readings: Reading[]
  rank: number
}
interface IssueRow {
  id: number | string
  记录编号: string | null
  设备类型: string
  设备编号: string
  记录时段: string | null
  抄表人员: string | null
  电耗度数: Num
  油耗升数: Num
  issue: 'missing_reader' | 'missing_period'
}
interface Summary {
  elec_total: Num
  fuel_total: Num
  reading_count: number
  blank_shift_count: number
  missing_reader_count: number
  missing_period_count: number
  duplicate_count: number
  raw_count: number
  issues?: { missing_reader: IssueRow[]; missing_period: IssueRow[] }
}
interface LedgerRow {
  id: number | string
  status: string
  记录编号: string | null
  设备类型: string
  设备编号: string
  电耗度数: Num
  油耗升数: Num
  记录时段: string | null
  抄表人员: string | null
  能耗状态: string
}

const ENDPOINT = '/api/energy'
const statuses = ['正常', '异常偏高', '异常偏低', '已核实']
const ledgerColumns = ['记录编号', '设备类型', '设备编号', '电耗度数', '油耗升数', '记录时段', '抄表人员', '能耗状态']

const periodOptions = [
  { value: 'week', short: '本周' },
  { value: 'month', short: '本月' },
  { value: 'quarter', short: '本季度' },
  { value: 'all', short: '全部' },
]

// —— 视图状态：换账期只重排，钻取层级与展开的设备行都保留 ——
const period = ref('week')
const tab = ref<'monitor' | 'ledger'>('monitor')
const categories = ref<CategoryRow[]>([])
const summary = ref<Summary>({
  elec_total: null, fuel_total: null, reading_count: 0, blank_shift_count: 0,
  missing_reader_count: 0, missing_period_count: 0, duplicate_count: 0, raw_count: 0,
})
const selectedCategory = ref<string | null>(null)
const categoryDetail = ref<{ category: string; category_label: string; devices: DeviceRow[] } | null>(null)
const expandedDevices = ref<string[]>([])

// 台账
const ledgerRows = ref<LedgerRow[]>([])
const ledgerTotal = ref(0)
const filters = ref<{ keyword: string; status: string }>({ keyword: '', status: '' })
const errorMessage = ref('')

const rootRef = ref<HTMLElement | null>(null)
let scrollBeforeDrill = 0

const missingReader = computed<IssueRow[]>(() => summary.value.issues?.missing_reader ?? [])
const missingPeriod = computed<IssueRow[]>(() => summary.value.issues?.missing_period ?? [])
const issueTotal = computed(() => (summary.value.missing_reader_count ?? 0) + (summary.value.missing_period_count ?? 0))

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined) return ''
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 1 })
}

function rankText(rank: number | null): string {
  return rank === null || rank === undefined ? '—' : String(rank)
}

function statusClass(status: string): string {
  if (status === '异常偏高') return 'st-over'
  if (status === '异常偏低') return 'st-low'
  if (status === '已核实') return 'st-done'
  return ''
}

async function loadOverview() {
  try {
    const response = await request(`${ENDPOINT}/analysis?period=${period.value}`)
    if (!response.ok) throw new Error('监测视图读取失败')
    const payload = await response.json()
    categories.value = payload.categories ?? []
    summary.value = payload.summary ?? summary.value
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '监测视图读取失败'
  }
}

async function loadCategoryDetail() {
  if (!selectedCategory.value) {
    categoryDetail.value = null
    return
  }
  try {
    const response = await request(`${ENDPOINT}/analysis/${encodeURIComponent(selectedCategory.value)}?period=${period.value}`)
    if (!response.ok) throw new Error('设备明细读取失败')
    categoryDetail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '设备明细读取失败'
  }
}

// 下钻：记住滚动位置，返回时停在原来的地方
async function drillInto(cat: string) {
  scrollBeforeDrill = window.scrollY
  selectedCategory.value = cat
  await loadCategoryDetail()
  window.scrollTo({ top: 0 })
}

function backToCategories() {
  selectedCategory.value = null
  categoryDetail.value = null
  requestAnimationFrame(() => window.scrollTo({ top: scrollBeforeDrill }))
}

function toggleDevice(device: string) {
  const index = expandedDevices.value.indexOf(device)
  if (index >= 0) {
    expandedDevices.value.splice(index, 1)
  } else {
    expandedDevices.value.push(device)
  }
}

// 换账期：数据重新拉取、排名后端重排；展开/钻取状态原封不动
async function changePeriod(next: string) {
  if (next === period.value) return
  period.value = next
  errorMessage.value = ''
  await Promise.all([loadOverview(), selectedCategory.value ? loadCategoryDetail() : Promise.resolve()])
  if (tab.value === 'ledger') await reloadLedger()
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reloadLedger()
}

function exportRows() {
  window.open(`${ENDPOINT}/export?period=all`, '_blank')
}

async function reloadLedger() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  query.set('period', period.value)
  query.set('page', '1')
  query.set('size', '200')
  if (filters.value.keyword.trim()) query.set('keyword', filters.value.keyword.trim())
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('能耗台账读取失败')
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
    ledgerTotal.value = payload.total ?? ledgerRows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '能耗台账读取失败'
  }
}

onMounted(loadOverview)
</script>

<style scoped>
.energy-page { display: block; }

.control-bar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin: 10px 0 12px;
}
.segmented {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.seg-item {
  border: none;
  background: transparent;
  padding: 7px 14px;
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
  border-right: 1px solid var(--border);
}
.seg-item:last-child { border-right: none; }
.seg-item.active { background: var(--brand); color: #fff; }

.dedup-note {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--muted);
  background: #f1f5f9;
  border: 1px dashed var(--border);
  border-radius: 6px;
  padding: 7px 10px;
}
.blank-cell-inline {
  display: inline-block;
  min-width: 34px;
  text-align: center;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 4px;
  color: #94a3b8;
  padding: 0 6px;
}

.col-rank { text-align: center; white-space: nowrap; }
.col-num { text-align: right; white-space: nowrap; }
.cell-strong { font-weight: 600; }
.muted { color: var(--muted); }
.warn { color: #b42318 !important; }
.warn-text { color: #b42318; font-weight: 600; }

.row-over { background: #fef3f2; }
.device-row { cursor: pointer; }
.device-row.expanded { background: #eef4ff; }

.flag-over {
  display: inline-block;
  background: #d92d20;
  color: #fff;
  font-size: 11px;
  border-radius: 4px;
  padding: 1px 6px;
  margin-right: 6px;
}
.flag-over.small { margin-left: 6px; margin-right: 0; }
.over-pill {
  display: inline-block;
  background: #fee4e2;
  color: #b42318;
  border: 1px solid #fecdca;
  border-radius: 999px;
  font-size: 12px;
  padding: 2px 10px;
  margin: 2px 6px 2px 0;
  white-space: nowrap;
}
.over-pill em { font-style: normal; color: #7a271a; font-size: 11px; }
.num-over { color: #b42318; font-weight: 700; }

.blank-cell {
  display: inline-block;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  color: #94a3b8;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
}
.issue-badge {
  display: inline-block;
  background: #fff4e5;
  color: #b54708;
  border: 1px solid #fedf89;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 12px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 10px;
  font-size: 13px;
}
.crumb-sep { color: var(--muted); }

.sub-table { width: 100%; border-collapse: collapse; background: #fbfdff; }
.sub-table th, .sub-table td {
  border: 1px solid #e2e8f0;
  padding: 6px 10px;
  font-size: 12px;
  text-align: left;
}
.sub-table th { background: #f1f5f9; }
.reading-row > td { padding: 0 10px 10px 34px; background: #fff; }
.row-reading-over { background: #fff7f6; }

.status-tag {
  display: inline-block;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
  background: #eef2f7;
  color: #475569;
}
.status-tag.st-over { background: #fee4e2; color: #b42318; }
.status-tag.st-low { background: #fef0c7; color: #a15c07; }
.status-tag.st-done { background: #d1fadf; color: #05603a; }

.issues-panel {
  margin-top: 16px;
  border: 1px solid #fedf89;
  background: #fffaeb;
  border-radius: 8px;
  padding: 12px 14px;
}
.issues-panel h3 { margin: 0 0 10px; font-size: 14px; color: #b54708; }
.issue-cols { display: flex; gap: 18px; flex-wrap: wrap; }
.issue-col { flex: 1; min-width: 280px; }
.issue-title { margin: 0 0 6px; font-size: 13px; color: #93370d; }
.issue-list { margin: 0; padding: 0; list-style: none; }
.issue-list li {
  display: flex;
  gap: 10px;
  align-items: center;
  background: #fff;
  border: 1px solid #fde293;
  border-radius: 6px;
  padding: 5px 10px;
  margin-bottom: 6px;
  font-size: 12px;
  flex-wrap: wrap;
}
.issue-device { font-weight: 600; }

.ledger-hint { margin-left: auto; font-size: 12px; }
.filter-item select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
  background: #fff;
}
</style>
