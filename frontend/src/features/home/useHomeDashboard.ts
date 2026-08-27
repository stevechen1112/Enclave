import { useCallback, useEffect, useMemo, useState } from 'react'

import { useAuth } from '../../auth'
import { knowledgeAssetApi, knowledgeReviewApi, parseApiError, type ApiErrorInfo } from '../../api'
import { useCapabilities } from '../../navigation/useCapabilities'
import type { KnowledgeAsset } from '../../types'

export type HomeDashboardModel = {
  title: string
  subtitle: string
  loading: boolean
  error: ApiErrorInfo | null
  assets: KnowledgeAsset[]
  stats: { total: number; ready: number; processing: number; review: number; failed: number }
  canUpload: boolean
  canReview: boolean
  canManage: boolean
  applications: Array<{ to: string; label: string; pack?: string }>
  reload: () => Promise<void>
}

function copyForRole(role?: string): Pick<HomeDashboardModel, 'title' | 'subtitle'> {
  if (role === 'owner' || role === 'admin') return { title: '公司知識營運總覽', subtitle: '掌握待辦、知識健康、處理狀態與已啟用應用。' }
  if (role === 'hr') return { title: '內容與知識工作', subtitle: '快速新增、確認並使用公司知識。' }
  if (role === 'viewer') return { title: '知識首頁', subtitle: '從已授權的企業知識開始查找與提問。' }
  return { title: '我的工作首頁', subtitle: '從提問、知識查找與已啟用應用開始工作。' }
}

export function useHomeDashboard(): HomeDashboardModel {
  const { user, experience } = useAuth()
  const capabilities = useCapabilities()
  const [assets, setAssets] = useState<KnowledgeAsset[]>([])
  const [reviewCount, setReviewCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const canReview = capabilities.has('review_queue')
  const canManage = capabilities.has('manage_sources')
  const canUpload = capabilities.has('upload_documents')
  const fetchDashboard = useCallback(() => Promise.allSettled([
    knowledgeAssetApi.list(),
    canReview ? knowledgeReviewApi.list() : Promise.resolve(null),
  ]), [canReview])
  const reload = useCallback(async () => {
    setLoading(true); setError(null)
    const [assetResult, reviewResult] = await fetchDashboard()
    if (assetResult.status === 'fulfilled') setAssets(assetResult.value)
    else setError(parseApiError(assetResult.reason, '無法載入知識首頁'))
    if (reviewResult.status === 'fulfilled' && reviewResult.value) setReviewCount(reviewResult.value.total)
    else setReviewCount(0)
    setLoading(false)
  }, [fetchDashboard])
  useEffect(() => {
    let cancelled = false
    void fetchDashboard().then(([assetResult, reviewResult]) => {
      if (cancelled) return
      if (assetResult.status === 'fulfilled') setAssets(assetResult.value)
      else setError(parseApiError(assetResult.reason, '無法載入知識首頁'))
      if (reviewResult.status === 'fulfilled' && reviewResult.value) setReviewCount(reviewResult.value.total)
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [fetchDashboard])
  const stats = useMemo(() => ({
    total: assets.length,
    ready: assets.filter(asset => asset.status === 'active' || asset.job?.status === 'ready').length,
    processing: assets.filter(asset => ['queued', 'running'].includes(asset.job?.status || '')).length,
    review: reviewCount || assets.filter(asset => asset.job?.status === 'review_required').length,
    failed: assets.filter(asset => asset.job?.status === 'failed' || asset.status === 'failed').length,
  }), [assets, reviewCount])
  const applications = useMemo(() => {
    const seen = new Set<string>()
    return (experience?.ui_modules || []).flatMap(manifest => manifest.navigation.map(item => ({ ...item, pack: manifest.pack_key }))).filter(item => {
      if (seen.has(item.to)) return false
      seen.add(item.to); return true
    })
  }, [experience?.ui_modules])
  return { ...copyForRole(user?.role), loading, error, assets, stats, canUpload, canReview, canManage, applications, reload }
}
