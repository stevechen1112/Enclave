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

export function useHomeDashboard(): HomeDashboardModel {
  const { experience } = useAuth()
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
  return {
    title: '公司知識工作區',
    subtitle: '從資料匯入、知識查找、提問與已啟用應用開始工作。',
    loading,
    error,
    assets,
    stats,
    canUpload,
    canReview,
    canManage,
    applications,
    reload,
  }
}
