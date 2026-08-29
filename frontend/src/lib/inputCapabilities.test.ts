import { describe, expect, it } from 'vitest'
import { buildDropAccept, capabilitySummary, preflightFile } from './inputCapabilities'
import type { InputCapabilityContract } from '../types'

const contract = {
  contract_version: 'input.v1',
  registry_sha256: 'a'.repeat(64),
  tenant_id: 'tenant-1',
  policy: { accepted_modes: ['file'], data_classifications: ['internal'], core_capture: true, capture_modes: ['long_audio', 'photo', 'video'], capture_policy_path: '/api/v1/knowledge/captures/policy', generic_resumable_upload: false, resumable_part_size: 8_388_608, resumable_min_part_size: 262_144, resumable_max_part_size: 16_777_216, resumable_max_parts: 10_000, resumable_session_ttl_hours: 24, video_allowed_codecs: [] },
  formats: [
    { extension: '.pdf', media_type: 'application/pdf', parser_kind: 'document', asset_kind: 'document', capabilities: ['extract_text'], evidence_state: 'internally_verified', ui_default: true, max_bytes: 10, max_duration_seconds: null, processing_status: 'configured', degradation_reasons: [] },
    { extension: '.heic', media_type: 'image/heic', parser_kind: 'image', asset_kind: 'image', capabilities: ['ocr'], evidence_state: 'environment_validation_pending', ui_default: true, max_bytes: 10, max_duration_seconds: null, processing_status: 'degraded', degradation_reasons: ['decoder unavailable'] },
    { extension: '.mp3', media_type: 'audio/mpeg', parser_kind: 'audio', asset_kind: 'audio', capabilities: ['transcribe'], evidence_state: 'environment_validation_pending', ui_default: true, max_bytes: 10, max_duration_seconds: null, processing_status: 'disabled', degradation_reasons: ['STT disabled'] },
  ],
  quota: null,
  providers: [],
} as InputCapabilityContract

describe('input capability helpers', () => {
  it('builds browser accept rules only from enabled deployment capabilities', () => {
    expect(buildDropAccept(contract)).toEqual({
      'application/pdf': ['.pdf'],
      'image/heic': ['.heic'],
    })
  })

  it('blocks unknown, disabled, oversized and quota-exceeding files before upload', () => {
    expect(preflightFile({ name: 'bad.exe', size: 1 }, contract).error).toMatch(/不支援/)
    expect(preflightFile({ name: 'voice.mp3', size: 1 }, contract).error).toBe('STT disabled')
    expect(preflightFile({ name: 'manual.pdf', size: 11 }, contract).error).toMatch(/上限/)
    expect(preflightFile({ name: 'manual.pdf', size: 8 }, contract, 4).error).toMatch(/剩餘儲存空間/)
    expect(preflightFile({ name: 'photo.heic', size: 8 }, contract).warning).toBe('decoder unavailable')
  })

  it('shows the server-owned content quality threshold when available', () => {
    const format = {
      ...contract.formats[0],
      quality_gate: { key: 'pdf-page-v1', min_content_accuracy: 0.98, min_locator_coverage: 1, min_parse_success: 0.99, review_below_confidence: 0.9, sample_rate: 0.05, max_provider_regression: 0.03 },
    }
    expect(capabilitySummary(format)).toContain('品質門檻 98%')
  })
})
