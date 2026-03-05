/**
 * GenerateScreen — Mobile content generation (P11)
 *
 * Mirrors web GeneratePage.tsx (simplified for mobile):
 *   - Template selector (horizontal scroll chips)
 *   - Prompt textarea
 *   - SSE streaming to generate/stream
 *   - Scrollable result text
 *   - No export in P12-1 (add in P12-2)
 */
import { useState, useRef } from 'react'
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ScrollView, KeyboardAvoidingView, Platform, ActivityIndicator,
  Alert,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import * as SecureStore from 'expo-secure-store'
import { API_BASE_URL } from '../config'
import type { SSEEvent } from '../types'

const TEMPLATES = [
  { id: 'draft_response',  label: '函件草稿', icon: '✉️' },
  { id: 'case_summary',    label: '案件摘要', icon: '📋' },
  { id: 'meeting_minutes', label: '會議記錄', icon: '📝' },
  { id: 'analysis_report', label: '分析報告', icon: '📊' },
  { id: 'faq_draft',       label: 'FAQ 草稿', icon: '❓' },
]

export default function GenerateScreen() {
  const [selectedTemplate, setSelectedTemplate] = useState(TEMPLATES[0].id)
  const [prompt, setPrompt] = useState('')
  const [contextQuery, setContextQuery] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [result, setResult] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  const handleGenerate = async () => {
    const q = prompt.trim()
    if (!q) {
      Alert.alert('提示', '請輸入需求說明')
      return
    }
    setIsGenerating(true)
    setResult('')

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const token = await SecureStore.getItemAsync('token')
      const response = await fetch(`${API_BASE_URL}/generate/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          template: selectedTemplate,
          user_prompt: q,
          context_query: contextQuery,
          max_tokens: 2000,
          document_ids: [],
        }),
        signal: ctrl.signal,
        // @ts-ignore
        reactNative: { textStreaming: true },
      })

      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      if (!response.body) throw new Error('No body')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw || raw === '[DONE]') continue
          try {
            const event = JSON.parse(raw) as SSEEvent
            if (event.type === 'token') {
              accumulated += event.content
              setResult(accumulated)
            }
          } catch { /* ignore */ }
        }
      }
    } catch (err: unknown) {
      const isAbort = (err as Error)?.name === 'AbortError'
      if (!isAbort && !result) Alert.alert('錯誤', '生成失敗，請稍後再試')
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">

        {/* ── Template chips ── */}
        <Text style={styles.sectionLabel}>選擇模板</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipScroll}>
          {TEMPLATES.map(t => (
            <TouchableOpacity
              key={t.id}
              style={[styles.chip, selectedTemplate === t.id && styles.chipActive]}
              onPress={() => setSelectedTemplate(t.id)}
            >
              <Text style={styles.chipIcon}>{t.icon}</Text>
              <Text style={[styles.chipLabel, selectedTemplate === t.id && styles.chipLabelActive]}>
                {t.label}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        {/* ── Prompt ── */}
        <Text style={styles.sectionLabel}>需求說明</Text>
        <TextInput
          style={styles.textarea}
          placeholder="描述您要生成的內容，例如：請幫我起草一份針對 XXX 事項的正式回覆函…"
          placeholderTextColor="#9CA3AF"
          multiline
          numberOfLines={5}
          value={prompt}
          onChangeText={setPrompt}
          editable={!isGenerating}
          textAlignVertical="top"
        />

        {/* ── Context query (optional) ── */}
        <Text style={styles.sectionLabel}>知識庫查詢關鍵字 <Text style={styles.optionalTag}>（選填）</Text></Text>
        <TextInput
          style={[styles.textarea, { minHeight: 44 }]}
          placeholder="輸入關鍵字以從知識庫擷取相關段落…"
          placeholderTextColor="#9CA3AF"
          value={contextQuery}
          onChangeText={setContextQuery}
          editable={!isGenerating}
        />

        {/* ── Generate / Stop button ── */}
        {isGenerating ? (
          <TouchableOpacity
            style={[styles.btn, styles.stopBtn]}
            onPress={() => abortRef.current?.abort()}
          >
            <Ionicons name="stop-circle-outline" size={20} color="#FFFFFF" />
            <Text style={styles.btnText}>停止生成</Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={[styles.btn, !prompt.trim() && styles.btnDisabled]}
            onPress={handleGenerate}
            disabled={!prompt.trim()}
          >
            <Ionicons name="sparkles-outline" size={20} color="#FFFFFF" />
            <Text style={styles.btnText}>開始生成</Text>
          </TouchableOpacity>
        )}

        {/* ── Result ── */}
        {(result || isGenerating) && (
          <View style={styles.resultBox}>
            <View style={styles.resultHeader}>
              <Text style={styles.resultTitle}>生成內容</Text>
              {isGenerating && <ActivityIndicator size="small" color="#2563EB" />}
            </View>
            <Text style={styles.resultText} selectable>
              {result}
              {isGenerating && <Text style={styles.cursor}>▋</Text>}
            </Text>
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#F9FAFB' },
  scroll: { padding: 16, paddingBottom: 40 },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 8,
    marginTop: 16,
  },
  optionalTag: { fontWeight: '400', color: '#9CA3AF' },
  chipScroll: { marginBottom: 4 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    marginRight: 8,
  },
  chipActive: {
    backgroundColor: '#EFF6FF',
    borderColor: '#2563EB',
  },
  chipIcon: { fontSize: 14 },
  chipLabel: { fontSize: 13, color: '#6B7280', fontWeight: '500' },
  chipLabelActive: { color: '#2563EB' },
  textarea: {
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    color: '#111827',
    minHeight: 100,
  },
  btn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: 20,
    backgroundColor: '#2563EB',
    borderRadius: 12,
    paddingVertical: 13,
  },
  btnDisabled: { backgroundColor: '#BFDBFE' },
  stopBtn: { backgroundColor: '#EF4444' },
  btnText: { color: '#FFFFFF', fontSize: 15, fontWeight: '600' },
  resultBox: {
    marginTop: 20,
    backgroundColor: '#FFFFFF',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  resultHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  resultTitle: { fontSize: 13, fontWeight: '600', color: '#374151' },
  resultText: { fontSize: 14, color: '#111827', lineHeight: 22 },
  cursor: { color: '#2563EB' },
})
