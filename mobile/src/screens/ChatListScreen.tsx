/**
 * ChatListScreen — Conversation list
 *
 * Mirrors the left-panel of web ChatPage.tsx.
 * Tap a conversation → navigate to ChatDetailScreen.
 * "New Chat" FAB to start a fresh conversation.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  Alert, ActivityIndicator, RefreshControl,
} from 'react-native'
import { useNavigation, useFocusEffect } from '@react-navigation/native'
import type { NativeStackNavigationProp } from '@react-navigation/native-stack'
import { Ionicons } from '@expo/vector-icons'
import { chatApi } from '../api'
import { useAuth } from '../auth'
import { cacheConversations, getCachedConversations } from '../cache'
import type { Conversation } from '../types'
import type { RootStackParamList } from '../navigation/AppNavigator'

type Nav = NativeStackNavigationProp<RootStackParamList>

function formatDate(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000)
  if (diffDays === 0) return d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
  if (diffDays < 7) return d.toLocaleDateString('zh-TW', { weekday: 'short' })
  return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })
}

export default function ChatListScreen() {
  const nav = useNavigation<Nav>()
  const { user, logout } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [offline, setOffline] = useState(false)
  const [staleCache, setStaleCache] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await chatApi.conversations()
      setConversations(data)
      setOffline(false)
      setStaleCache(false)
      await cacheConversations(data)
    } catch {
      // 網路失敗，回退至快取
      const { conversations: cached, stale } = await getCachedConversations()
      if (cached.length > 0) {
        setConversations(cached)
        setOffline(true)
        setStaleCache(stale)
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  // Reload when screen comes into focus (e.g. returning from ChatDetail)
  useFocusEffect(useCallback(() => { load() }, [load]))

  const deleteConv = (id: string) => {
    Alert.alert('刪除對話', '確定要刪除這個對話嗎？', [
      { text: '取消', style: 'cancel' },
      {
        text: '刪除', style: 'destructive',
        onPress: async () => {
          await chatApi.deleteConversation(id)
          setConversations(c => c.filter(x => x.id !== id))
        },
      },
    ])
  }

  const handleLogout = () => {
    Alert.alert('登出', '確定要登出嗎？', [
      { text: '取消', style: 'cancel' },
      { text: '登出', style: 'destructive', onPress: () => logout() },
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
      {/* P12-8: 離線横幅 */}
      {offline && (
        <View style={styles.offlineBanner}>
          <Ionicons name="cloud-offline-outline" size={14} color="#92400E" />
          <Text style={styles.offlineText}>
            {staleCache ? '離線模式（快取已超過 24 小時）' : '離線横幅 — 顯示本機快取'}
          </Text>
        </View>
      )}

      {/* ── User bar ── */}
      <View style={styles.userBar}>
        <View>
          <Text style={styles.userName}>{user?.full_name || user?.email}</Text>
          <Text style={styles.userRole}>{(user?.role ?? '').toUpperCase()}</Text>
        </View>
        <TouchableOpacity onPress={handleLogout} style={styles.logoutBtn}>
          <Ionicons name="log-out-outline" size={22} color="#6B7280" />
        </TouchableOpacity>
      </View>

      {/* ── Conversation list ── */}
      <FlatList
        data={conversations}
        keyExtractor={item => item.id}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load() }} tintColor="#2563EB" />
        }
        ListEmptyComponent={
          <View style={styles.emptyBox}>
            <Ionicons name="chatbubble-ellipses-outline" size={48} color="#D1D5DB" />
            <Text style={styles.emptyText}>尚無對話</Text>
            <Text style={styles.emptyHint}>點擊下方「新對話」開始</Text>
          </View>
        }
        renderItem={({ item }) => (
          <TouchableOpacity
            style={styles.convItem}
            onPress={() => nav.navigate('ChatDetail', { conversation: item })}
            onLongPress={() => deleteConv(item.id)}
            activeOpacity={0.7}
          >
            <View style={styles.convAvatar}>
              <Ionicons name="chatbubble-ellipses-outline" size={18} color="#2563EB" />
            </View>
            <View style={styles.convBody}>
              <Text style={styles.convTitle} numberOfLines={1}>
                {item.title || '未命名對話'}
              </Text>
              <Text style={styles.convDate}>{formatDate(item.updated_at || item.created_at)}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color="#D1D5DB" />
          </TouchableOpacity>
        )}
        contentContainerStyle={conversations.length === 0 ? styles.listEmpty : undefined}
      />

      {/* ── New chat FAB ── */}
      <TouchableOpacity
        style={styles.fab}
        onPress={() => nav.navigate('ChatDetail', { conversation: null })}
        activeOpacity={0.85}
      >
        <Ionicons name="add" size={28} color="#FFFFFF" />
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
  userBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#FFFFFF',
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  userName: { fontSize: 14, fontWeight: '600', color: '#111827' },
  userRole: { fontSize: 11, color: '#6B7280', marginTop: 1 },
  logoutBtn: { padding: 6 },
  convItem: {
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
  convAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#EFF6FF',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  convBody: { flex: 1, marginRight: 8 },
  convTitle: { fontSize: 14, fontWeight: '500', color: '#111827', marginBottom: 2 },
  convDate: { fontSize: 11, color: '#9CA3AF' },
  emptyBox: { alignItems: 'center', paddingTop: 80, gap: 8 },
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
})
