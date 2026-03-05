/**
 * ChatDetailScreen — SSE streaming chat thread
 *
 * Mirrors right-panel / message view of web ChatPage.tsx.
 * Features:
 *   - Load existing messages when entering a conversation
 *   - SSE streaming (chatApi.stream) → token-by-token response
 *   - Source panel (documents used in answer)
 *   - Follow-up suggestions
 *   - Abort mid-stream
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  View, Text, FlatList, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform,
  ActivityIndicator, Alert,
} from 'react-native'
import { useNavigation, useRoute } from '@react-navigation/native'
import type { NativeStackNavigationProp, RouteProp } from '@react-navigation/native-stack'
import { Ionicons } from '@expo/vector-icons'
import { chatApi } from '../api'
import type { Message, ChatSource, Conversation } from '../types'
import type { RootStackParamList } from '../navigation/AppNavigator'

type Nav = NativeStackNavigationProp<RootStackParamList>
type Route = RouteProp<RootStackParamList, 'ChatDetail'>

interface ChatMessage extends Message {
  sources?: ChatSource[]
  suggestions?: string[]
}

const STREAMING_ID = '__streaming__'

export default function ChatDetailScreen() {
  const nav = useNavigation<Nav>()
  const route = useRoute<Route>()
  const initConv: Conversation | null = route.params.conversation

  const [conversationId, setConversationId] = useState<string | null>(initConv?.id ?? null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [streamSources, setStreamSources] = useState<ChatSource[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<FlatList>(null)

  // Set header title
  useEffect(() => {
    nav.setOptions({
      title: initConv?.title || '新對話',
    })
  }, [nav, initConv])

  // Load messages for existing conversation
  useEffect(() => {
    if (!conversationId) return
    chatApi.messages(conversationId).then(msgs => {
      setMessages(msgs as ChatMessage[])
    }).catch(() => {})
  }, [conversationId])

  // Auto-scroll to bottom when messages or stream changes
  useEffect(() => {
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100)
  }, [messages, streamContent])

  const handleAbort = useCallback(() => {
    abortRef.current?.abort()
    setSending(false)
    setStreamContent('')
  }, [])

  const handleSend = async () => {
    const question = input.trim()
    if (!question || sending) return

    const userMsg: ChatMessage = {
      id: 'temp-' + Date.now(),
      conversation_id: conversationId || '',
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setSending(true)
    setStreamContent('')
    setStreamSources([])

    const ctrl = new AbortController()
    abortRef.current = ctrl

    let finalConvId = conversationId
    let finalMsgId = ''
    let accumulated = ''
    const suggestions: string[] = []
    const sources: ChatSource[] = []

    try {
      await chatApi.stream(
        { question, conversation_id: conversationId },
        (event) => {
          switch (event.type) {
            case 'token':
              accumulated += event.content
              setStreamContent(accumulated)
              break
            case 'sources':
              sources.push(...event.sources)
              setStreamSources([...sources])
              break
            case 'suggestions':
              suggestions.push(...event.items)
              break
            case 'done':
              finalConvId = event.conversation_id
              setConversationId(event.conversation_id)
              finalMsgId = event.message_id
              break
          }
        },
        ctrl.signal,
      )
    } catch (err: unknown) {
      const isAbort = (err as Error)?.name === 'AbortError'
      if (!isAbort && accumulated === '') {
        Alert.alert('錯誤', '無法取得回應，請稍後再試')
      }
    }

    // Commit streamed message to list
    if (accumulated) {
      const assistantMsg: ChatMessage = {
        id: finalMsgId || 'ai-' + Date.now(),
        conversation_id: finalConvId || '',
        role: 'assistant',
        content: accumulated,
        created_at: new Date().toISOString(),
        sources: sources.length > 0 ? sources : undefined,
        suggestions: suggestions.length > 0 ? suggestions : undefined,
      }
      setMessages(prev => [...prev, assistantMsg])
    }
    setStreamContent('')
    setStreamSources([])
    setSending(false)

    // Update header title with actual conversation
    if (finalConvId && !initConv?.title) {
      nav.setOptions({ title: question.slice(0, 30) })
    }
  }

  // Render a single message bubble
  const renderMessage = ({ item }: { item: ChatMessage }) => {
    const isUser = item.role === 'user'
    return (
      <View style={[styles.msgRow, isUser ? styles.msgRowUser : styles.msgRowAI]}>
        {!isUser && (
          <View style={styles.aiAvatar}>
            <Ionicons name="shield-checkmark" size={14} color="#2563EB" />
          </View>
        )}
        <View style={[styles.bubble, isUser ? styles.bubbleUser : styles.bubbleAI]}>
          <Text style={[styles.bubbleText, isUser ? styles.bubbleTextUser : styles.bubbleTextAI]}>
            {item.content}
          </Text>

          {/* Sources */}
          {item.sources && item.sources.length > 0 && (
            <View style={styles.sourcesBox}>
              <Text style={styles.sourcesTitle}>📎 參考資料</Text>
              {item.sources.map((src, i) => (
                <Text key={i} style={styles.sourceItem} numberOfLines={2}>
                  [{i + 1}] {src.filename}
                </Text>
              ))}
            </View>
          )}
        </View>
      </View>
    )
  }

  // Streaming message row (shown while AI is generating)
  const renderStreaming = () => {
    if (!sending && !streamContent) return null
    return (
      <View style={[styles.msgRow, styles.msgRowAI]}>
        <View style={styles.aiAvatar}>
          <Ionicons name="shield-checkmark" size={14} color="#2563EB" />
        </View>
        <View style={[styles.bubble, styles.bubbleAI]}>
          {streamContent
            ? <Text style={styles.bubbleTextAI}>{streamContent}</Text>
            : (
              <View style={styles.typingRow}>
                <ActivityIndicator size="small" color="#2563EB" />
                <Text style={styles.typingText}> 思考中…</Text>
              </View>
            )
          }
        </View>
      </View>
    )
  }

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
    >
      {/* ── Messages ── */}
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={item => item.id}
        renderItem={renderMessage}
        ListFooterComponent={renderStreaming}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <View style={styles.emptyBox}>
            <Ionicons name="chatbubble-ellipses-outline" size={48} color="#D1D5DB" />
            <Text style={styles.emptyText}>輸入問題開始對話</Text>
          </View>
        }
      />

      {/* ── Input bar ── */}
      <View style={styles.inputBar}>
        <TextInput
          style={styles.textInput}
          placeholder="輸入問題…"
          placeholderTextColor="#9CA3AF"
          multiline
          value={input}
          onChangeText={setInput}
          editable={!sending}
          returnKeyType="send"
          onSubmitEditing={handleSend}
          blurOnSubmit={false}
        />
        {sending ? (
          <TouchableOpacity style={[styles.sendBtn, styles.stopBtn]} onPress={handleAbort}>
            <Ionicons name="stop-circle-outline" size={24} color="#FFFFFF" />
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={[styles.sendBtn, !input.trim() && styles.sendBtnDisabled]}
            onPress={handleSend}
            disabled={!input.trim()}
          >
            <Ionicons name="send" size={20} color="#FFFFFF" />
          </TouchableOpacity>
        )}
      </View>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#F9FAFB' },
  listContent: { padding: 12, paddingBottom: 8, flexGrow: 1 },
  msgRow: { flexDirection: 'row', marginBottom: 12, alignItems: 'flex-start' },
  msgRowUser: { justifyContent: 'flex-end' },
  msgRowAI: { justifyContent: 'flex-start' },
  aiAvatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#EFF6FF',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
    marginTop: 2,
  },
  bubble: {
    maxWidth: '78%',
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  bubbleUser: {
    backgroundColor: '#2563EB',
    borderBottomRightRadius: 4,
  },
  bubbleAI: {
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderBottomLeftRadius: 4,
  },
  bubbleText: { fontSize: 14, lineHeight: 20 },
  bubbleTextUser: { color: '#FFFFFF' },
  bubbleTextAI: { color: '#111827' },
  sourcesBox: {
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
  },
  sourcesTitle: { fontSize: 11, fontWeight: '600', color: '#6B7280', marginBottom: 4 },
  sourceItem: { fontSize: 11, color: '#2563EB', marginBottom: 2 },
  typingRow: { flexDirection: 'row', alignItems: 'center' },
  typingText: { fontSize: 13, color: '#6B7280' },
  emptyBox: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingTop: 80, gap: 8 },
  emptyText: { fontSize: 15, color: '#9CA3AF', marginTop: 8 },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: '#FFFFFF',
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
    gap: 8,
  },
  textInput: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    fontSize: 14,
    color: '#111827',
    backgroundColor: '#F9FAFB',
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#2563EB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnDisabled: { backgroundColor: '#BFDBFE' },
  stopBtn: { backgroundColor: '#EF4444' },
})
