/**
 * ReviewQueueScreen — P12-2 完整操作版
 *
 * 完整對標 web ReviewQueuePage.tsx：
 *   - 高信心度（≥0.8）可選取批量核准
 *   - 低信心度（<0.8）需逐一操作
 *   - 核准 / 拒絕 / 修改後確認
 *   - 展開顯示 AI 判斷依據、標籤、關聯文件
 *   - ModifyModal（RN 原生 Modal）
 */
import { useState, useCallback } from 'react'
import {
  View, Text, StyleSheet, TouchableOpacity,
  ActivityIndicator, RefreshControl, Modal, TextInput,
  ScrollView, Alert, Pressable,
} from 'react-native'
import { useFocusEffect } from '@react-navigation/native'
import { Ionicons } from '@expo/vector-icons'
import api from '../api'

// ── Types ────────────────────────────────────────────────────────────────────

interface RelatedDoc {
  id: string
  file_name: string
  match: string
}

interface ReviewItem {
  id: string
  file_name: string
  file_path: string
  file_ext: string | null
  file_size: number | null
  suggested_category: string | null
  suggested_subcategory: string | null
  suggested_tags: Record<string, string> | null
  confidence_score: number | null
  reasoning: string | null
  related_documents: RelatedDoc[]
  status: string
  created_at: string
}

// ── ConfidenceBadge ──────────────────────────────────────────────────────────

function ConfidenceBadge({ score }: { score: number | null }) {
  if (score == null) return null
  const pct = Math.round(score * 100)
  const [bg, fg] =
    score >= 0.8 ? ['#D1FAE5', '#065F46'] :
    score >= 0.6 ? ['#FEF3C7', '#92400E'] :
                   ['#FEE2E2', '#991B1B']
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={[styles.badgeText, { color: fg }]}>{pct}%</Text>
    </View>
  )
}

// ── ModifyModal ──────────────────────────────────────────────────────────────

function ModifyModal({
  item, onClose, onDone,
}: { item: ReviewItem; onClose: () => void; onDone: () => void }) {
  const [category, setCategory] = useState(item.suggested_category ?? '')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    setSaving(true)
    try {
      await api.post(`/agent/review/${item.id}/modify`, { category, note })
      onDone(); onClose()
    } catch {
      Alert.alert('錯誤', '修改失敗，請稍後再試')
    } finally { setSaving(false) }
  }

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={styles.overlay} onPress={onClose}>
        <Pressable style={styles.modalCard} onPress={() => {}}>
          <Text style={styles.modalTitle}>修改分類後確認</Text>
          <Text style={styles.modalFileName} numberOfLines={1}>{item.file_name}</Text>

          <Text style={styles.modalLabel}>分類</Text>
          <TextInput
            style={styles.modalInput}
            value={category}
            onChangeText={setCategory}
            placeholder="輸入分類名稱"
            placeholderTextColor="#9CA3AF"
          />

          <Text style={styles.modalLabel}>審核備註（選填）</Text>
          <TextInput
            style={[styles.modalInput, styles.modalTextarea]}
            value={note}
            onChangeText={setNote}
            placeholder="備註說明…"
            placeholderTextColor="#9CA3AF"
            multiline
            numberOfLines={3}
            textAlignVertical="top"
          />

          <View style={styles.modalActions}>
            <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
              <Text style={styles.cancelBtnText}>取消</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.confirmBtn, saving && styles.btnDisabled]}
              onPress={submit}
              disabled={saving}
            >
              {saving
                ? <ActivityIndicator color="#FFF" size="small" />
                : <Ionicons name="checkmark-circle-outline" size={16} color="#FFF" />
              }
              <Text style={styles.confirmBtnText}>確認入庫</Text>
            </TouchableOpacity>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  )
}

// ── ReviewItemCard ───────────────────────────────────────────────────────────

function ReviewItemCard({
  item, selected, canSelect,
  onToggleSelect, onApprove, onReject, onModify,
}: {
  item: ReviewItem; selected: boolean; canSelect: boolean
  onToggleSelect: () => void; onApprove: () => void
  onReject: () => void; onModify: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const hasTags = item.suggested_tags && Object.keys(item.suggested_tags).length > 0
  const hasRelated = item.related_documents?.length > 0

  return (
    <View style={[styles.card, selected && styles.cardSelected]}>
      <View style={styles.cardTop}>
        {canSelect && (
          <TouchableOpacity onPress={onToggleSelect} style={styles.checkbox}>
            <Ionicons
              name={selected ? 'checkbox' : 'square-outline'}
              size={20}
              color={selected ? '#2563EB' : '#D1D5DB'}
            />
          </TouchableOpacity>
        )}
        <View style={styles.cardInfo}>
          <Text style={styles.cardFileName} numberOfLines={1}>{item.file_name}</Text>
          <Text style={styles.cardCategory} numberOfLines={1}>
            {item.suggested_category ?? '（未分類）'}
            {item.suggested_subcategory ? ` › ${item.suggested_subcategory}` : ''}
          </Text>
        </View>
        <ConfidenceBadge score={item.confidence_score} />
      </View>

      <View style={styles.cardActions}>
        <TouchableOpacity style={styles.actionBtn} onPress={onApprove}>
          <Ionicons name="checkmark-circle-outline" size={20} color="#059669" />
          <Text style={[styles.actionText, { color: '#059669' }]}>核准</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionBtn} onPress={onModify}>
          <Ionicons name="create-outline" size={20} color="#2563EB" />
          <Text style={[styles.actionText, { color: '#2563EB' }]}>修改</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionBtn} onPress={onReject}>
          <Ionicons name="close-circle-outline" size={20} color="#DC2626" />
          <Text style={[styles.actionText, { color: '#DC2626' }]}>拒絕</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionBtn} onPress={() => setExpanded(e => !e)}>
          <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={18} color="#6B7280" />
        </TouchableOpacity>
      </View>

      {expanded && (
        <View style={styles.cardDetail}>
          {!!item.reasoning && (
            <Text style={styles.detailText}>
              <Text style={styles.detailLabel}>AI 判斷依據：</Text>{item.reasoning}
            </Text>
          )}
          <Text style={styles.detailText}>
            <Text style={styles.detailLabel}>路徑：</Text>
            <Text style={styles.monoText}>{item.file_path}</Text>
          </Text>
          {hasTags && (
            <View style={styles.tagRow}>
              {Object.entries(item.suggested_tags!).map(([k, v]) => (
                <View key={k} style={styles.tag}>
                  <Text style={styles.tagText}>{k}: {v}</Text>
                </View>
              ))}
            </View>
          )}
          {hasRelated && (
            <View style={styles.relatedBox}>
              <Text style={styles.relatedTitle}>⚠ 關聯文件（{item.related_documents.length} 筆）</Text>
              {item.related_documents.map(rel => (
                <Text key={rel.id} style={styles.relatedItem} numberOfLines={1}>📄 {rel.file_name}</Text>
              ))}
            </View>
          )}
        </View>
      )}
    </View>
  )
}

// ── Main Screen ──────────────────────────────────────────────────────────────

export default function ReviewQueueScreen() {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [acting, setActing] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [modifyItem, setModifyItem] = useState<ReviewItem | null>(null)

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: ReviewItem[]; total: number } | ReviewItem[]>(
        '/agent/review?status=pending&limit=100',
      )
      const arr = Array.isArray(data) ? data : (data as { items: ReviewItem[] }).items
      const tot = Array.isArray(data) ? data.length : (data as { total: number }).total
      setItems(arr ?? [])
      setTotal(tot ?? 0)
      setSelectedIds(new Set())
    } catch { /* silent */ }
    finally { setLoading(false); setRefreshing(false) }
  }, [])

  useFocusEffect(useCallback(() => { load() }, [load]))

  const highConf = items.filter(i => (i.confidence_score ?? 0) >= 0.8)
  const lowConf  = items.filter(i => (i.confidence_score ?? 0) < 0.8)

  const withActing = async (fn: () => Promise<void>) => {
    setActing(true)
    try { await fn(); await load() }
    catch { Alert.alert('錯誤', '操作失敗，請稍後再試') }
    finally { setActing(false) }
  }

  const approve = (id: string) =>
    withActing(() => api.post(`/agent/review/${id}/approve`).then(() => {}))

  const reject = (id: string) =>
    Alert.alert('拒絕入庫', '確定拒絕此文件？', [
      { text: '取消', style: 'cancel' },
      { text: '拒絕', style: 'destructive',
        onPress: () => withActing(() => api.post(`/agent/review/${id}/reject`, { reason: '' }).then(() => {})) },
    ])

  const batchApprove = () => {
    if (!selectedIds.size) return
    Alert.alert(`批量核准 ${selectedIds.size} 件`, '確定全部入庫？', [
      { text: '取消', style: 'cancel' },
      { text: '確認', onPress: () =>
          withActing(() => api.post('/agent/review/batch-approve', { item_ids: [...selectedIds] }).then(() => {})) },
    ])
  }

  const toggleSelect = (id: string) =>
    setSelectedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })

  if (loading) return (
    <View style={styles.center}><ActivityIndicator size="large" color="#2563EB" /></View>
  )

  return (
    <View style={styles.root}>
      <View style={styles.toolbar}>
        <Text style={styles.toolbarTitle}>文件審核佇列{total > 0 ? `（${total}）` : ''}</Text>
        <View style={styles.toolbarRight}>
          {acting && <ActivityIndicator size="small" color="#2563EB" style={{ marginRight: 8 }} />}
          {selectedIds.size > 0 && (
            <TouchableOpacity style={[styles.batchBtn, acting && styles.btnDisabled]} onPress={batchApprove} disabled={acting}>
              <Ionicons name="checkmark-done-outline" size={15} color="#FFF" />
              <Text style={styles.batchBtnText}>批量核准（{selectedIds.size}）</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity onPress={() => { setRefreshing(true); load() }} style={styles.iconBtn}>
            <Ionicons name="refresh-outline" size={20} color="#6B7280" />
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView
        style={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load() }} tintColor="#2563EB" />}
      >
        {items.length === 0 ? (
          <View style={styles.emptyBox}>
            <Ionicons name="checkmark-circle-outline" size={52} color="#34D399" />
            <Text style={styles.emptyTitle}>佇列空了</Text>
            <Text style={styles.emptyHint}>所有文件已完成審核，或尚未啟動 Agent 掃描</Text>
          </View>
        ) : (
          <>
            {highConf.length > 0 && (
              <View style={styles.section}>
                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionLabel}>高信心度 ≥ 80%（{highConf.length}）</Text>
                  <TouchableOpacity onPress={() =>
                    setSelectedIds(prev => { const n = new Set(prev); highConf.forEach(i => n.add(i.id)); return n })
                  }>
                    <Text style={styles.selectAll}>全選</Text>
                  </TouchableOpacity>
                </View>
                {highConf.map(item => (
                  <ReviewItemCard key={item.id} item={item} selected={selectedIds.has(item.id)} canSelect
                    onToggleSelect={() => toggleSelect(item.id)}
                    onApprove={() => approve(item.id)} onReject={() => reject(item.id)} onModify={() => setModifyItem(item)} />
                ))}
              </View>
            )}

            {lowConf.length > 0 && (
              <View style={styles.section}>
                <Text style={[styles.sectionLabel, { color: '#EA580C' }]}>
                  需逐一確認（信心度 &lt; 80%）（{lowConf.length}）
                </Text>
                {lowConf.map(item => (
                  <ReviewItemCard key={item.id} item={item} selected={false} canSelect={false}
                    onToggleSelect={() => {}}
                    onApprove={() => approve(item.id)} onReject={() => reject(item.id)} onModify={() => setModifyItem(item)} />
                ))}
              </View>
            )}

            <Text style={styles.totalText}>共 {total} 筆待審核</Text>
          </>
        )}
      </ScrollView>

      {modifyItem && (
        <ModifyModal item={modifyItem} onClose={() => setModifyItem(null)} onDone={load} />
      )}
    </View>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#F9FAFB' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F9FAFB' },
  scroll: { flex: 1 },

  toolbar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: '#FFF', borderBottomWidth: 1, borderBottomColor: '#E5E7EB',
  },
  toolbarTitle: { fontSize: 15, fontWeight: '700', color: '#111827' },
  toolbarRight: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  batchBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: '#059669', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7,
  },
  batchBtnText: { fontSize: 12, fontWeight: '600', color: '#FFF' },
  iconBtn: { padding: 4 },
  btnDisabled: { opacity: 0.5 },

  section: { paddingHorizontal: 12, paddingTop: 12 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  sectionLabel: { fontSize: 11, fontWeight: '700', color: '#6B7280', textTransform: 'uppercase', letterSpacing: 0.5, flex: 1 },
  selectAll: { fontSize: 12, color: '#2563EB', fontWeight: '600', marginLeft: 8 },

  card: {
    backgroundColor: '#FFF', borderRadius: 12, marginBottom: 8,
    borderWidth: 1, borderColor: '#E5E7EB', overflow: 'hidden',
  },
  cardSelected: { borderColor: '#2563EB' },
  cardTop: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14, paddingTop: 12, paddingBottom: 6, gap: 8 },
  checkbox: { marginRight: 2 },
  cardInfo: { flex: 1 },
  cardFileName: { fontSize: 14, fontWeight: '500', color: '#111827', marginBottom: 2 },
  cardCategory: { fontSize: 12, color: '#6B7280' },
  badge: { borderRadius: 20, paddingHorizontal: 8, paddingVertical: 2 },
  badgeText: { fontSize: 12, fontWeight: '700' },

  cardActions: {
    flexDirection: 'row', borderTopWidth: 1, borderTopColor: '#F3F4F6', paddingHorizontal: 8,
  },
  actionBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, paddingVertical: 9 },
  actionText: { fontSize: 12, fontWeight: '600' },

  cardDetail: {
    borderTopWidth: 1, borderTopColor: '#F3F4F6', backgroundColor: '#F9FAFB',
    paddingHorizontal: 14, paddingVertical: 10, gap: 6,
  },
  detailText: { fontSize: 12, color: '#4B5563', lineHeight: 18 },
  detailLabel: { fontWeight: '600' },
  monoText: { fontFamily: 'monospace', fontSize: 11 },
  tagRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: 2 },
  tag: { backgroundColor: '#EFF6FF', borderRadius: 20, paddingHorizontal: 8, paddingVertical: 2 },
  tagText: { fontSize: 11, color: '#1D4ED8' },
  relatedBox: { backgroundColor: '#FFFBEB', borderRadius: 8, padding: 8, marginTop: 4 },
  relatedTitle: { fontSize: 11, fontWeight: '600', color: '#B45309', marginBottom: 4 },
  relatedItem: { fontSize: 11, color: '#92400E', marginBottom: 2 },

  emptyBox: { alignItems: 'center', paddingTop: 80, paddingHorizontal: 24, gap: 8 },
  emptyTitle: { fontSize: 16, fontWeight: '600', color: '#374151', marginTop: 8 },
  emptyHint: { fontSize: 13, color: '#9CA3AF', textAlign: 'center' },
  totalText: { textAlign: 'center', fontSize: 12, color: '#9CA3AF', paddingVertical: 16 },

  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: '#FFF', borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 24, paddingBottom: 36,
  },
  modalTitle: { fontSize: 17, fontWeight: '700', color: '#111827', marginBottom: 6 },
  modalFileName: { fontSize: 12, color: '#6B7280', marginBottom: 16 },
  modalLabel: { fontSize: 13, fontWeight: '600', color: '#374151', marginBottom: 6 },
  modalInput: {
    borderWidth: 1, borderColor: '#D1D5DB', borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: '#111827', marginBottom: 14,
  },
  modalTextarea: { minHeight: 72, textAlignVertical: 'top' },
  modalActions: { flexDirection: 'row', gap: 10, marginTop: 4 },
  cancelBtn: {
    flex: 1, borderWidth: 1, borderColor: '#D1D5DB', borderRadius: 10,
    paddingVertical: 11, alignItems: 'center',
  },
  cancelBtnText: { fontSize: 14, color: '#374151', fontWeight: '500' },
  confirmBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, backgroundColor: '#2563EB', borderRadius: 10, paddingVertical: 11,
  },
  confirmBtnText: { fontSize: 14, color: '#FFF', fontWeight: '600' },
})
