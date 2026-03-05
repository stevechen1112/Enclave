/**
 * ProgressDashboardScreen — P12-2 三角色儀表板
 *
 * 完整對標 web ProgressDashboardPage.tsx：
 *
 *   Admin/owner/superuser → 完整管理儀表板
 *     - 4 統計卡片（已入庫/待審核/向量化中/總提案）
 *     - Agent 狀態（watcher / scheduler / 資料夾數）
 *     - 狀態分佈橫條圖
 *     - 觸發重建索引 / PDF 報告下載
 *     - 失敗警告
 *
 *   HR（助理）→ 待審核摘要 + 快速前往審核佇列
 *
 *   一般使用者 → 已入庫文件數（唯讀）
 */
import { useState, useCallback } from 'react'
import {
  View, Text, StyleSheet, TouchableOpacity,
  ScrollView, ActivityIndicator, RefreshControl, Alert, Linking,
} from 'react-native'
import { useFocusEffect, useNavigation } from '@react-navigation/native'
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs'
import { Ionicons } from '@expo/vector-icons'
import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'
import api from '../api'
import { useAuth } from '../auth'
import { API_BASE_URL } from '../config'
import * as SecureStore from 'expo-secure-store'
import type { MainTabParamList } from '../navigation/MainNavigator'

// ── Types ────────────────────────────────────────────────────────────────────

interface StatusSummary {
  watcher_running: boolean
  scheduler_running: boolean
  active_folders: number
  pending_review_count: number
}

interface BatchSummary {
  status_summary: Record<string, number>
}

interface SystemHealth {
  status: string
  database: string
  redis: string
  uptime_seconds: number
  python_version: string
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  pending: '待審核', approved: '已核准', modified: '修改確認',
  rejected: '已拒絕', processing: '向量化中', indexed: '已入庫', failed: '失敗',
}

const STATUS_BAR_COLOR: Record<string, string> = {
  indexed: '#34D399', pending: '#FBBF24', rejected: '#F87171',
  failed: '#F87171', processing: '#A78BFA',
}

function isAdmin(role: string, superuser?: boolean) {
  return !!superuser || role === 'owner' || role === 'admin'
}

// ── StatCard ─────────────────────────────────────────────────────────────────

function StatCard({ icon, label, value, iconBg, iconColor }: {
  icon: keyof typeof Ionicons.glyphMap
  label: string; value: string | number
  iconBg: string; iconColor: string
}) {
  return (
    <View style={styles.statCard}>
      <View style={[styles.statIconBox, { backgroundColor: iconBg }]}>
        <Ionicons name={icon} size={18} color={iconColor} />
      </View>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value}</Text>
    </View>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
//  USER view
// ══════════════════════════════════════════════════════════════════════════════

function UserView({ batches, loading, onRefresh }: {
  batches: BatchSummary | null; loading: boolean; onRefresh: () => void
}) {
  const indexed = batches?.status_summary?.indexed ?? 0
  return (
    <ScrollView
      style={styles.root}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={onRefresh} tintColor="#2563EB" />}
    >
      <View style={styles.pageHeader}>
        <Text style={styles.pageTitle}>知識庫狀態</Text>
        <Text style={styles.pageSubtitle}>文件索引即時狀態</Text>
      </View>
      <View style={styles.section}>
        <View style={styles.bigStatCard}>
          <View style={[styles.statIconBox, { backgroundColor: '#D1FAE5', width: 52, height: 52, borderRadius: 14 }]}>
            <Ionicons name="library-outline" size={26} color="#059669" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.statLabel}>已入庫可查詢文件</Text>
            <Text style={[styles.statValue, { fontSize: 32 }]}>{loading ? '—' : indexed}</Text>
            <Text style={styles.subtleHint}>AI 問答功能可使用上述文件進行搜尋</Text>
          </View>
        </View>
      </View>
    </ScrollView>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
//  HR view
// ══════════════════════════════════════════════════════════════════════════════

function HRView({ status, batches, loading, onRefresh }: {
  status: StatusSummary | null; batches: BatchSummary | null
  loading: boolean; onRefresh: () => void
}) {
  const nav = useNavigation<BottomTabNavigationProp<MainTabParamList>>()
  const pending = batches?.status_summary?.pending ?? 0
  const indexed = batches?.status_summary?.indexed ?? 0
  const modified = batches?.status_summary?.modified ?? 0

  return (
    <ScrollView
      style={styles.root}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={onRefresh} tintColor="#2563EB" />}
    >
      <View style={styles.pageHeader}>
        <Text style={styles.pageTitle}>知識庫審核中心</Text>
        <Text style={styles.pageSubtitle}>待審核文件摘要 — 助理視圖</Text>
      </View>

      <View style={styles.section}>
        {pending > 0 ? (
          <View style={styles.pendingCard}>
            <View style={{ flex: 1 }}>
              <Text style={styles.pendingCount}>{pending}</Text>
              <Text style={styles.pendingLabel}>份文件等待您審核</Text>
              {modified > 0 && (
                <Text style={styles.pendingHint}>（另有 {modified} 份已修改待確認）</Text>
              )}
            </View>
            <TouchableOpacity
              style={styles.goReviewBtn}
              onPress={() => nav.navigate('ReviewQueue')}
            >
              <Text style={styles.goReviewText}>前往審核</Text>
              <Ionicons name="arrow-forward" size={16} color="#FFF" />
            </TouchableOpacity>
          </View>
        ) : (
          <View style={styles.allClearCard}>
            <Ionicons name="checkmark-circle" size={24} color="#059669" />
            <View>
              <Text style={styles.allClearTitle}>審核佇列已清空</Text>
              <Text style={styles.allClearSub}>目前沒有待審核文件</Text>
            </View>
          </View>
        )}
      </View>

      <View style={[styles.section, { flexDirection: 'row', gap: 12 }]}>
        <View style={[styles.statCard, { flex: 1 }]}>
          <Text style={styles.statLabel}>已入庫文件</Text>
          <Text style={styles.statValue}>{loading ? '—' : indexed}</Text>
        </View>
        <View style={[styles.statCard, { flex: 1 }]}>
          <Text style={styles.statLabel}>監控資料夾</Text>
          <Text style={styles.statValue}>{loading ? '—' : (status?.active_folders ?? '—')}</Text>
        </View>
      </View>
    </ScrollView>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
//  Admin view
// ══════════════════════════════════════════════════════════════════════════════

function AdminView({ status, batches, health, loading, onRefresh }: {
  status: StatusSummary | null; batches: BatchSummary | null
  health: SystemHealth | null; loading: boolean; onRefresh: () => void
}) {
  const [triggering, setTriggering] = useState(false)
  const [lastTriggered, setLastTriggered] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  const summary = batches?.status_summary ?? {}
  const indexed    = summary.indexed    ?? 0
  const pending    = summary.pending    ?? 0
  const processing = summary.processing ?? 0
  const total = Object.entries(summary)
    .filter(([k]) => k !== 'rejected' && k !== 'failed')
    .reduce((s, [, v]) => s + v, 0)

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      const { data } = await api.post<{ triggered: boolean; triggered_at?: string }>('/agent/batches/trigger')
      setLastTriggered(data.triggered_at || new Date().toISOString())
      onRefresh()
    } catch {
      Alert.alert('錯誤', '觸發失敗，請稍後再試')
    } finally { setTriggering(false) }
  }

  const handleDownloadReport = async () => {
    setDownloading(true)
    try {
      const token = await SecureStore.getItemAsync('token')
      const fileName = `batch_report_${new Date().toISOString().slice(0, 10)}.pdf`
      const fileUri = `${FileSystem.documentDirectory}${fileName}`

      const downloadRes = await FileSystem.downloadAsync(
        `${API_BASE_URL}/agent/batches/report`,
        fileUri,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      )

      if (downloadRes.status !== 200) throw new Error(`HTTP ${downloadRes.status}`)

      const canShare = await Sharing.isAvailableAsync()
      if (canShare) {
        await Sharing.shareAsync(downloadRes.uri, {
          mimeType: 'application/pdf',
          dialogTitle: '批次處理報告',
          UTI: 'com.adobe.pdf',
        })
      } else {
        Alert.alert('已下載', `報告儲存至：${downloadRes.uri}`)
      }
    } catch {
      Alert.alert('錯誤', '報告下載失敗')
    } finally { setDownloading(false) }
  }

  const sumTotal = Object.values(summary).reduce((s, v) => s + v, 1)

  return (
    <ScrollView
      style={styles.root}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={onRefresh} tintColor="#2563EB" />}
    >
      {/* ── Header actions ── */}
      <View style={styles.pageHeader}>
        <View>
          <Text style={styles.pageTitle}>處理進度儀表板</Text>
          <Text style={styles.pageSubtitle}>知識庫索引狀態與批次處理統計</Text>
        </View>
      </View>

      {/* ── Toolbar buttons ── */}
      <View style={styles.adminToolbar}>
        <TouchableOpacity
          style={[styles.outlineBtn, downloading && styles.btnDisabled]}
          onPress={handleDownloadReport}
          disabled={downloading}
        >
          {downloading
            ? <ActivityIndicator size="small" color="#374151" />
            : <Ionicons name="download-outline" size={16} color="#374151" />
          }
          <Text style={styles.outlineBtnText}>下載報告</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.primaryBtn, (triggering || loading) && styles.btnDisabled]}
          onPress={handleTrigger}
          disabled={triggering || loading}
        >
          {triggering
            ? <ActivityIndicator size="small" color="#FFF" />
            : <Ionicons name="play-outline" size={16} color="#FFF" />
          }
          <Text style={styles.primaryBtnText}>立即重建索引</Text>
        </TouchableOpacity>
      </View>

      {/* ── Triggered notice ── */}
      {lastTriggered && (
        <View style={[styles.section, { paddingTop: 0 }]}>
          <View style={styles.successBanner}>
            <Ionicons name="checkmark-circle" size={16} color="#059669" />
            <Text style={styles.successBannerText}>
              批次重建已觸發（{new Date(lastTriggered).toLocaleTimeString('zh-TW')}）
            </Text>
          </View>
        </View>
      )}

      {/* ── 4 stat cards ── */}
      <View style={styles.section}>
        <View style={styles.statsGrid}>
          <StatCard icon="library-outline"    label="已入庫文件"  value={loading ? '—' : indexed}    iconBg="#D1FAE5" iconColor="#059669" />
          <StatCard icon="time-outline"       label="待審核"      value={loading ? '—' : pending}    iconBg="#FEF3C7" iconColor="#D97706" />
          <StatCard icon="analytics-outline"  label="向量化中"    value={loading ? '—' : processing} iconBg="#EDE9FE" iconColor="#7C3AED" />
          <StatCard icon="documents-outline"  label="總提案數"    value={loading ? '—' : total}      iconBg="#DBEAFE" iconColor="#2563EB" />
        </View>
      </View>

      {/* ── Agent status ── */}
      <View style={styles.section}>
        <View style={styles.panel}>
          <Text style={styles.panelTitle}>Agent 狀態</Text>
          <View style={styles.agentStatusRow}>
            <View style={styles.agentStatusItem}>
              <Ionicons
                name={status?.watcher_running ? 'checkmark-circle' : 'alert-circle-outline'}
                size={16} color={status?.watcher_running ? '#059669' : '#9CA3AF'} />
              <Text style={{ fontSize: 13, color: status?.watcher_running ? '#065F46' : '#9CA3AF' }}>
                檔案監控：{status?.watcher_running ? '運行中' : '已停止'}
              </Text>
            </View>
            <View style={styles.agentStatusItem}>
              <Ionicons
                name={status?.scheduler_running ? 'checkmark-circle' : 'alert-circle-outline'}
                size={16} color={status?.scheduler_running ? '#059669' : '#9CA3AF'} />
              <Text style={{ fontSize: 13, color: status?.scheduler_running ? '#065F46' : '#9CA3AF' }}>
                排程器：{status?.scheduler_running ? '運行中' : '已停止'}
              </Text>
            </View>
            <View style={styles.agentStatusItem}>
              <Ionicons name="folder-outline" size={16} color="#6B7280" />
              <Text style={{ fontSize: 13, color: '#6B7280' }}>
                啟用資料夾：{status?.active_folders ?? '—'}
              </Text>
            </View>
          </View>
        </View>
      </View>

      {/* ── System health (superuser) ── */}
      {health && (
        <View style={styles.section}>
          <View style={styles.panel}>
            <Text style={styles.panelTitle}>系統健康（IT）</Text>
            <View style={styles.agentStatusRow}>
              {[
                { label: 'DB', value: health.database, ok: health.database === 'healthy' },
                { label: 'Redis', value: health.redis, ok: health.redis === 'healthy' },
              ].map(({ label, value, ok }) => (
                <View key={label} style={styles.agentStatusItem}>
                  <Ionicons name={ok ? 'checkmark-circle' : 'close-circle'} size={16} color={ok ? '#059669' : '#DC2626'} />
                  <Text style={{ fontSize: 13, color: ok ? '#065F46' : '#991B1B' }}>{label}：{value}</Text>
                </View>
              ))}
              <Text style={{ fontSize: 12, color: '#9CA3AF' }}>Python {health.python_version}</Text>
            </View>
          </View>
        </View>
      )}

      {/* ── Status bar chart ── */}
      <View style={styles.section}>
        <View style={styles.panel}>
          <Text style={styles.panelTitle}>審核佇列狀態分佈</Text>
          {loading ? (
            <ActivityIndicator color="#2563EB" style={{ marginVertical: 16 }} />
          ) : Object.keys(summary).length === 0 ? (
            <Text style={styles.subtleHint}>尚無紀錄，Agent 啟動後自動統計</Text>
          ) : (
            <View style={{ gap: 8, marginTop: 8 }}>
              {Object.entries(summary).sort((a, b) => b[1] - a[1]).map(([st, count]) => {
                const pct = Math.round((count / sumTotal) * 100)
                return (
                  <View key={st} style={styles.barRow}>
                    <View style={styles.barLabel}>
                      <Text style={styles.barLabelText}>{STATUS_LABEL[st] || st}</Text>
                    </View>
                    <View style={styles.barTrack}>
                      <View style={[styles.barFill, {
                        width: `${pct}%`,
                        backgroundColor: STATUS_BAR_COLOR[st] || '#93C5FD',
                      }]} />
                    </View>
                    <Text style={styles.barCount}>{count}</Text>
                  </View>
                )
              })}
            </View>
          )}
        </View>
      </View>

      {/* ── Failed warning ── */}
      {(summary.failed ?? 0) > 0 && (
        <View style={styles.section}>
          <View style={styles.errorBanner}>
            <Ionicons name="close-circle" size={20} color="#DC2626" style={{ marginTop: 2 }} />
            <View style={{ flex: 1 }}>
              <Text style={styles.errorBannerTitle}>有 {summary.failed} 個文件向量化失敗</Text>
              <Text style={styles.errorBannerSub}>請檢查 Celery Worker 日誌，或重新觸發批次重建索引</Text>
            </View>
          </View>
        </View>
      )}

      {/* Bottom padding */}
      <View style={{ height: 32 }} />
    </ScrollView>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
//  Main Screen — role router
// ══════════════════════════════════════════════════════════════════════════════

export default function ProgressDashboardScreen() {
  const { user } = useAuth()
  const [status, setStatus]   = useState<StatusSummary | null>(null)
  const [batches, setBatches] = useState<BatchSummary | null>(null)
  const [health, setHealth]   = useState<SystemHealth | null>(null)
  const [loading, setLoading] = useState(true)

  const adminRole = user ? isAdmin(user.role, user.is_superuser) : false
  const hrRole    = !adminRole && user?.role === 'hr'

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [statusRes, batchRes] = await Promise.all([
        api.get<StatusSummary>('/agent/status'),
        api.get<BatchSummary>('/agent/batches'),
      ])
      setStatus(statusRes.data)
      setBatches(batchRes.data)

      if (user?.is_superuser) {
        try {
          const h = await api.get<SystemHealth>('/admin/system/health')
          setHealth(h.data)
        } catch { /* optional */ }
      }
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [user])

  useFocusEffect(useCallback(() => { load() }, [load]))

  if (adminRole) return (
    <AdminView status={status} batches={batches} health={health} loading={loading} onRefresh={load} />
  )
  if (hrRole) return (
    <HRView status={status} batches={batches} loading={loading} onRefresh={load} />
  )
  return (
    <UserView batches={batches} loading={loading} onRefresh={load} />
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#F9FAFB' },

  pageHeader: {
    paddingHorizontal: 16, paddingTop: 16, paddingBottom: 4,
  },
  pageTitle: { fontSize: 18, fontWeight: '700', color: '#111827' },
  pageSubtitle: { fontSize: 13, color: '#6B7280', marginTop: 2 },

  section: { paddingHorizontal: 16, paddingTop: 14 },

  adminToolbar: {
    flexDirection: 'row', gap: 10,
    paddingHorizontal: 16, paddingTop: 12,
  },
  outlineBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, borderWidth: 1, borderColor: '#D1D5DB', borderRadius: 10,
    paddingVertical: 10, backgroundColor: '#FFF',
  },
  outlineBtnText: { fontSize: 13, color: '#374151', fontWeight: '500' },
  primaryBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, backgroundColor: '#2563EB', borderRadius: 10, paddingVertical: 10,
  },
  primaryBtnText: { fontSize: 13, color: '#FFF', fontWeight: '600' },
  btnDisabled: { opacity: 0.5 },

  successBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    backgroundColor: '#D1FAE5', borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 10,
    borderWidth: 1, borderColor: '#6EE7B7',
  },
  successBannerText: { fontSize: 13, color: '#065F46', flex: 1 },

  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  statCard: {
    minWidth: '45%', flex: 1,
    backgroundColor: '#FFF', borderRadius: 14,
    padding: 14, borderWidth: 1, borderColor: '#E5E7EB',
  },
  statIconBox: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: 'center', justifyContent: 'center', marginBottom: 8,
  },
  statLabel: { fontSize: 12, color: '#6B7280', marginBottom: 2 },
  statValue: { fontSize: 24, fontWeight: '700', color: '#111827' },

  panel: {
    backgroundColor: '#FFF', borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: '#E5E7EB',
  },
  panelTitle: { fontSize: 14, fontWeight: '700', color: '#111827', marginBottom: 10 },
  agentStatusRow: { gap: 8 },
  agentStatusItem: { flexDirection: 'row', alignItems: 'center', gap: 8 },

  barRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barLabel: { width: 60 },
  barLabelText: { fontSize: 11, color: '#6B7280', textAlign: 'right' },
  barTrack: { flex: 1, height: 14, backgroundColor: '#F3F4F6', borderRadius: 7, overflow: 'hidden' },
  barFill: { height: 14, borderRadius: 7 },
  barCount: { width: 30, fontSize: 12, fontWeight: '600', color: '#374151', textAlign: 'right' },

  errorBanner: {
    flexDirection: 'row', gap: 10,
    backgroundColor: '#FEF2F2', borderRadius: 12, padding: 14,
    borderWidth: 1, borderColor: '#FECACA', alignItems: 'flex-start',
  },
  errorBannerTitle: { fontSize: 13, fontWeight: '600', color: '#991B1B' },
  errorBannerSub: { fontSize: 12, color: '#B91C1C', marginTop: 2 },

  subtleHint: { fontSize: 12, color: '#9CA3AF', marginTop: 4 },

  // HR / User view extras
  bigStatCard: {
    backgroundColor: '#FFF', borderRadius: 14, padding: 18,
    flexDirection: 'row', alignItems: 'center', gap: 16,
    borderWidth: 1, borderColor: '#E5E7EB',
  },
  pendingCard: {
    backgroundColor: '#FFFBEB', borderRadius: 14, padding: 18,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    borderWidth: 1, borderColor: '#FDE68A',
  },
  pendingCount: { fontSize: 36, fontWeight: '700', color: '#B45309' },
  pendingLabel: { fontSize: 14, color: '#92400E', marginTop: 2 },
  pendingHint: { fontSize: 11, color: '#B45309', marginTop: 4 },
  goReviewBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: '#D97706', borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 10,
  },
  goReviewText: { fontSize: 13, fontWeight: '600', color: '#FFF' },
  allClearCard: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    backgroundColor: '#D1FAE5', borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: '#6EE7B7',
  },
  allClearTitle: { fontSize: 14, fontWeight: '600', color: '#065F46' },
  allClearSub: { fontSize: 12, color: '#047857', marginTop: 2 },
})
