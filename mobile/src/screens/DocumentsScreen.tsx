/**
 * DocumentsScreen — File list + upload
 *
 * Mirrors web DocumentsPage.tsx.
 * Features:
 *   - List documents with status chips
 *   - Pick file via expo-document-picker and upload
 *   - Pull-to-refresh
 *   - Delete with long-press
 */
import { useState, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  Alert, ActivityIndicator, RefreshControl, Modal, ActionSheetIOS, Platform,
} from 'react-native'
import * as DocumentPicker from 'expo-document-picker'
import * as ImagePicker from 'expo-image-picker'
import { useFocusEffect } from '@react-navigation/native'
import { Ionicons } from '@expo/vector-icons'
import { docApi } from '../api'
import { cacheDocuments, getCachedDocuments } from '../cache'
import type { Document } from '../types'

type UploadMode = 'immediate' | 'review'

// ─── Upload Mode Modal ────────────────────────────────────────────────────────
function UploadModeModal({ visible, fileName, onSelect, onCancel }: {
  visible: boolean
  fileName: string
  onSelect: (mode: UploadMode) => void
  onCancel: () => void
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCancel}>
      <TouchableOpacity style={mStyles.overlay} activeOpacity={1} onPress={onCancel} />
      <View style={mStyles.sheet}>
        <View style={mStyles.handle} />
        <Text style={mStyles.title}>選擇上傳模式</Text>
        <Text style={mStyles.fileName} numberOfLines={2}>{fileName}</Text>

        {/* 立即入庫 */}
        <TouchableOpacity style={mStyles.option} onPress={() => onSelect('immediate')} activeOpacity={0.8}>
          <View style={[mStyles.optionIcon, { backgroundColor: '#D1FAE5' }]}>
            <Ionicons name="flash" size={22} color="#059669" />
          </View>
          <View style={mStyles.optionBody}>
            <Text style={mStyles.optionTitle}>立即入庫</Text>
            <Text style={mStyles.optionDesc}>律師自行分類，立即向量化並進入知識庫可查詢</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#9CA3AF" />
        </TouchableOpacity>

        {/* 待審核佇列 */}
        <TouchableOpacity style={mStyles.option} onPress={() => onSelect('review')} activeOpacity={0.8}>
          <View style={[mStyles.optionIcon, { backgroundColor: '#FEF3C7' }]}>
            <Ionicons name="time-outline" size={22} color="#D97706" />
          </View>
          <View style={mStyles.optionBody}>
            <Text style={mStyles.optionTitle}>待審核佇列</Text>
            <Text style={mStyles.optionDesc}>暫存佇列，回事務所後由助理審核分類確認</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#9CA3AF" />
        </TouchableOpacity>

        <TouchableOpacity style={mStyles.cancelBtn} onPress={onCancel}>
          <Text style={mStyles.cancelText}>取消</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  )
}

const mStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)' },
  sheet: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    backgroundColor: '#FFF', borderTopLeftRadius: 20, borderTopRightRadius: 20,
    paddingBottom: 40, paddingHorizontal: 20, paddingTop: 12,
  },
  handle: { width: 40, height: 4, backgroundColor: '#E5E7EB', borderRadius: 2, alignSelf: 'center', marginBottom: 16 },
  title: { fontSize: 17, fontWeight: '700', color: '#111827', marginBottom: 4 },
  fileName: { fontSize: 12, color: '#6B7280', marginBottom: 18 },
  option: {
    flexDirection: 'row', alignItems: 'center', gap: 14,
    backgroundColor: '#F9FAFB', borderRadius: 14, padding: 14, marginBottom: 10,
    borderWidth: 1, borderColor: '#E5E7EB',
  },
  optionIcon: { width: 44, height: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  optionBody: { flex: 1 },
  optionTitle: { fontSize: 15, fontWeight: '600', color: '#111827' },
  optionDesc: { fontSize: 12, color: '#6B7280', marginTop: 2 },
  cancelBtn: { alignItems: 'center', paddingVertical: 14, marginTop: 4 },
  cancelText: { fontSize: 15, color: '#6B7280' },
})

const STATUS_CONFIG: Record<string, { label: string; bg: string; text: string }> = {
  uploading:  { label: '上傳中',   bg: '#DBEAFE', text: '#1D4ED8' },
  parsing:    { label: '解析中',   bg: '#FEF3C7', text: '#92400E' },
  embedding:  { label: '索引中',   bg: '#F3E8FF', text: '#6B21A8' },
  completed:  { label: '已完成',   bg: '#D1FAE5', text: '#065F46' },
  failed:     { label: '失敗',     bg: '#FEE2E2', text: '#991B1B' },
}

function formatSize(bytes: number | null) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export default function DocumentsScreen() {
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [offline, setOffline] = useState(false)
  // P12-6: upload mode modal state
  const [pendingAsset, setPendingAsset] = useState<{
    uri: string; name: string; mimeType: string
  } | null>(null)
  // P12-5: 批量上傳多檔 state
  const [pendingBatchAssets, setPendingBatchAssets] = useState<
    { uri: string; name: string; mimeType: string }[]
  >([])

  const load = useCallback(async () => {
    try {
      const data = await docApi.list()
      setDocs(data)
      setOffline(false)
      await cacheDocuments(data)
    } catch {
      // 網路失敗，回退至快取
      const { documents: cached } = await getCachedDocuments()
      if (cached.length > 0) {
        setDocs(cached)
        setOffline(true)
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useFocusEffect(useCallback(() => { load() }, [load]))

  // P12-5: 上傳來源選擇（相機 / 檔案 / 多檔批量）
  const showUploadSourcePicker = () => {
    const options = ['拍照上傳', '選擇檔案', '批量選擇多檔', '取消']
    const cancelIdx = 3

    if (Platform.OS === 'ios') {
      ActionSheetIOS.showActionSheetWithOptions(
        { options, cancelButtonIndex: cancelIdx },
        (idx) => {
          if (idx === 0) handleCameraCapture()
          else if (idx === 1) handleFilePick()
          else if (idx === 2) handleMultiFilePick()
        },
      )
    } else {
      // Android: use Alert as simple action sheet
      Alert.alert('上傳方式', '請選擇上傳來源', [
        { text: '拍照上傳', onPress: handleCameraCapture },
        { text: '選擇檔案', onPress: handleFilePick },
        { text: '批量選擇多檔', onPress: handleMultiFilePick },
        { text: '取消', style: 'cancel' },
      ])
    }
  }

  // P12-5: 相機拍照上傳
  const handleCameraCapture = async () => {
    try {
      const { status } = await ImagePicker.requestCameraPermissionsAsync()
      if (status !== 'granted') {
        Alert.alert('權限不足', '需要相機權限才能拍照上傳，請至設定中允許')
        return
      }
      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: 'images',
        quality: 0.85,
      })
      if (result.canceled || !result.assets?.[0]) return
      const asset = result.assets[0]
      const fileName = asset.fileName ?? `photo_${Date.now()}.jpg`
      setPendingAsset({
        uri: asset.uri,
        name: fileName,
        mimeType: asset.mimeType ?? 'image/jpeg',
      })
    } catch {
      Alert.alert('錯誤', '無法開啟相機')
    }
  }

  // P12-6: Step 1 — pick single file, then show mode modal
  const handleFilePick = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: [
          'application/pdf',
          'application/msword',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          'text/plain',
          'text/markdown',
          'image/*',
        ],
        copyToCacheDirectory: true,
      })
      if (result.canceled || !result.assets?.[0]) return
      const asset = result.assets[0]
      setPendingAsset({
        uri: asset.uri,
        name: asset.name,
        mimeType: asset.mimeType ?? 'application/octet-stream',
      })
    } catch {
      // DocumentPicker cancelled or error — silent
    }
  }

  // P12-5: 批量選擇多檔上傳
  const handleMultiFilePick = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: [
          'application/pdf',
          'application/msword',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          'text/plain',
          'text/markdown',
          'image/*',
        ],
        copyToCacheDirectory: true,
        multiple: true,
      })
      if (result.canceled || !result.assets?.length) return
      // 多檔依次上傳
      setPendingBatchAssets(result.assets.map(a => ({
        uri: a.uri,
        name: a.name,
        mimeType: a.mimeType ?? 'application/octet-stream',
      })))
    } catch {
      // cancelled or error — silent
    }
  }

  // 原有的 handleUpload (for backward compat) — 改為呼叫 showUploadSourcePicker
  const handleUpload = () => showUploadSourcePicker()

  // P12-6: Step 2 — user selects mode, then upload (single or batch)
  const handleModeSelect = async (mode: UploadMode) => {
    // 批量上傳
    if (pendingBatchAssets.length > 0) {
      const assets = [...pendingBatchAssets]
      setPendingBatchAssets([])
      setUploading(true)
      setUploadProgress(0)
      let successCount = 0
      let failCount = 0
      for (let i = 0; i < assets.length; i++) {
        const { uri, name, mimeType } = assets[i]
        try {
          const uploaded = await docApi.upload(
            uri, name, mimeType,
            (pct) => {
              const fileProgress = ((i + pct / 100) / assets.length) * 100
              setUploadProgress(Math.round(fileProgress))
            },
            mode,
          )
          setDocs(prev => [uploaded, ...prev])
          successCount++
        } catch {
          failCount++
        }
      }
      setUploading(false)
      setUploadProgress(0)
      const msg = failCount === 0
        ? `${successCount} 個檔案全部上傳成功`
        : `成功 ${successCount} 個，失敗 ${failCount} 個`
      Alert.alert('批量上傳完成', msg)
      return
    }

    // 單檔上傳
    if (!pendingAsset) return
    const { uri, name, mimeType } = pendingAsset
    setPendingAsset(null)
    setUploading(true)
    setUploadProgress(0)
    try {
      const uploaded = await docApi.upload(uri, name, mimeType, (pct) => setUploadProgress(pct), mode)
      setDocs(prev => [uploaded, ...prev])
      const msg = mode === 'review'
        ? `${name} 已加入待審核佇列，回事務所後確認分類`
        : `${name} 已開始索引，稍後可查詢`
      Alert.alert(mode === 'review' ? '已加入佇列' : '上傳成功', msg)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? '上傳失敗'
      Alert.alert('錯誤', detail)
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const handleDelete = (doc: Document) => {
    Alert.alert('刪除文件', `確定刪除「${doc.filename}」？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '刪除', style: 'destructive',
        onPress: async () => {
          await docApi.delete(doc.id)
          setDocs(prev => prev.filter(d => d.id !== doc.id))
        },
      },
    ])
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2563EB" />
      </View>
    )
  }

  return (
    <View style={styles.root}>
      {/* P12-6: Upload mode selection modal */}
      <UploadModeModal
        visible={!!pendingAsset || pendingBatchAssets.length > 0}
        fileName={
          pendingBatchAssets.length > 0
            ? `${pendingBatchAssets.length} 個檔案已選取`
            : pendingAsset?.name ?? ''
        }
        onSelect={handleModeSelect}
        onCancel={() => { setPendingAsset(null); setPendingBatchAssets([]) }}
      />
      {/* P12-8: \u96e2\u7dda\u6a2a\u5e45 */}
      {offline && (
        <View style={styles.offlineBanner}>
          <Ionicons name="cloud-offline-outline" size={14} color="#92400E" />
          <Text style={styles.offlineText}>\u96e2\u7dda\u6a2a\u5e45 \u2014 \u986f\u793a\u672c\u6a5f\u5feb\u53d6\uff0c\u4e0a\u50b3\u529f\u80fd\u66ab\u505c\u7528</Text>
        </View>
      )}
      {/* ── Upload progress bar ── */}
      {uploading && (
        <View style={styles.progressBar}>
          <View style={[styles.progressFill, { width: `${uploadProgress}%` }]} />
          <Text style={styles.progressText}>
            {uploadProgress < 100 ? `上傳中… ${uploadProgress}%` : '處理中…'}
          </Text>
        </View>
      )}

      {/* ── Document list ── */}
      <FlatList
        data={docs}
        keyExtractor={item => item.id}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load() }} tintColor="#2563EB" />
        }
        ListEmptyComponent={
          <View style={styles.emptyBox}>
            <Ionicons name="document-text-outline" size={48} color="#D1D5DB" />
            <Text style={styles.emptyText}>尚無文件</Text>
            <Text style={styles.emptyHint}>點擊右下角上傳按鈕</Text>
          </View>
        }
        renderItem={({ item }) => {
          const cfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.failed
          return (
            <TouchableOpacity
              style={styles.docItem}
              onLongPress={() => handleDelete(item)}
              activeOpacity={0.8}
            >
              <View style={styles.docIcon}>
                <Ionicons
                  name={item.file_type === 'pdf' ? 'document-text' : 'document'}
                  size={22}
                  color="#2563EB"
                />
              </View>
              <View style={styles.docBody}>
                <Text style={styles.docName} numberOfLines={1}>{item.filename}</Text>
                <View style={styles.docMeta}>
                  <View style={[styles.statusChip, { backgroundColor: cfg.bg }]}>
                    <Text style={[styles.statusText, { color: cfg.text }]}>{cfg.label}</Text>
                  </View>
                  {!!item.file_size && (
                    <Text style={styles.metaText}>{formatSize(item.file_size)}</Text>
                  )}
                  {item.chunk_count != null && item.chunk_count > 0 && (
                    <Text style={styles.metaText}>{item.chunk_count} 塊</Text>
                  )}
                  {item.is_new && (
                    <View style={styles.newBadge}>
                      <Text style={styles.newBadgeText}>NEW</Text>
                    </View>
                  )}
                </View>
              </View>
            </TouchableOpacity>
          )
        }}
        contentContainerStyle={docs.length === 0 ? styles.listEmpty : undefined}
      />

      {/* ── Upload FAB ── */}
      <TouchableOpacity
        style={[styles.fab, uploading && styles.fabDisabled]}
        onPress={handleUpload}
        disabled={uploading}
        activeOpacity={0.85}
      >
        {uploading
          ? <ActivityIndicator color="#FFFFFF" size="small" />
          : <Ionicons name="cloud-upload-outline" size={26} color="#FFFFFF" />
        }
      </TouchableOpacity>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#F9FAFB' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F9FAFB' },
  offlineBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: '#FEF3C7', paddingHorizontal: 14, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: '#FDE68A',
  },
  offlineText: { fontSize: 12, color: '#92400E', flex: 1 },
  progressBar: {
    height: 36,
    backgroundColor: '#DBEAFE',
    justifyContent: 'center',
    paddingHorizontal: 16,
    position: 'relative',
  },
  progressFill: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    backgroundColor: '#BFDBFE',
  },
  progressText: { fontSize: 12, color: '#1D4ED8', zIndex: 1 },
  docItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    marginHorizontal: 12,
    marginTop: 8,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  docIcon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: '#EFF6FF',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  docBody: { flex: 1 },
  docName: { fontSize: 14, fontWeight: '500', color: '#111827', marginBottom: 5 },
  docMeta: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  statusChip: {
    borderRadius: 6,
    paddingHorizontal: 7,
    paddingVertical: 2,
  },
  statusText: { fontSize: 11, fontWeight: '600' },
  metaText: { fontSize: 11, color: '#9CA3AF' },
  newBadge: {
    backgroundColor: '#D1FAE5',
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  newBadgeText: { fontSize: 10, fontWeight: '700', color: '#065F46' },
  emptyBox: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingTop: 80, gap: 8 },
  emptyText: { fontSize: 16, fontWeight: '500', color: '#9CA3AF', marginTop: 8 },
  emptyHint: { fontSize: 13, color: '#D1D5DB' },
  listEmpty: { flex: 1 },
  fab: {
    position: 'absolute',
    bottom: 24,
    right: 20,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#2563EB',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#2563EB',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 10,
    elevation: 8,
  },
  fabDisabled: { backgroundColor: '#93C5FD' },
})
