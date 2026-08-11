import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import FormPage from './FormPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

const schemaMock = vi.fn()
const createMock = vi.fn()
const patchMock = vi.fn()
const calculateMock = vi.fn()
const validateMock = vi.fn()
const submitMock = vi.fn()
vi.mock('../../services/mka', () => ({
  formsApi: {
    schema: (...args: unknown[]) => schemaMock(...args),
    createInstance: (...args: unknown[]) => createMock(...args),
    patchInstance: (...args: unknown[]) => patchMock(...args),
    calculate: (...args: unknown[]) => calculateMock(...args),
    validate: (...args: unknown[]) => validateMock(...args),
    submit: (...args: unknown[]) => submitMock(...args),
    exportSync: vi.fn(),
  },
  downloadBlob: vi.fn(),
}))

const QUOTE_SCHEMA = {
  id: 'fd1',
  form_key: 'quote',
  name: '報價單',
  schema_version: '1.0',
  status: 'active',
  json_schema: {},
  ui_schema: {},
  fields: [
    { name: 'customer', label: '客戶', type: 'text', required: true },
    { name: 'part_number', label: '料號', type: 'part_number', required: true },
    { name: 'quantity', label: '數量', type: 'number', required: true },
    { name: 'unit_price', label: '單價', type: 'amount', required: true },
    {
      name: 'payment_terms',
      label: '付款條件',
      type: 'select',
      required: true,
      options: ['現金', '月結30天'],
    },
  ],
}

const INSTANCE = {
  id: 'inst-1',
  form_version: '1.0',
  module_key: 'quote',
  status: 'draft',
  record_version: 1,
  values: {},
  provenance: {},
  calculation_snapshot: {},
  validation_result: { valid: true, errors: [] },
  approval_request_id: null,
  created_at: null,
  updated_at: null,
}

function renderPage(prefill?: Record<string, string>, formKey = 'quote') {
  return render(
    <MemoryRouter
      initialEntries={[
        { pathname: `/forms/${formKey}`, state: prefill ? { prefill, transcript: '語音原文' } : undefined },
      ]}
    >
      <Routes>
        <Route path="/forms/:formKey" element={<FormPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('FormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    schemaMock.mockResolvedValue(QUOTE_SCHEMA)
    createMock.mockResolvedValue(INSTANCE)
    calculateMock.mockResolvedValue({
      ...INSTANCE,
      record_version: 2,
      calculation_snapshot: { 小計: 24000, 稅額: 1200, 總計: 25200 },
    })
    validateMock.mockResolvedValue({
      ...INSTANCE,
      record_version: 3,
      calculation_snapshot: { 小計: 24000, 稅額: 1200, 總計: 25200 },
      validation_result: { valid: true, errors: [] },
    })
    submitMock.mockResolvedValue({
      form: { ...INSTANCE, status: 'pending_review' },
      approval: { id: 'approval-12345678', status: 'pending' },
    })
  })

  it('載入 schema 並渲染欄位（含語音預填）', async () => {
    renderPage({ customer: '台中精機', part_number: 'P-100' })
    expect(await screen.findByLabelText(/客戶/)).toHaveValue('台中精機')
    expect(screen.getByLabelText(/料號/)).toHaveValue('P-100')
    expect(screen.getByText(/語音帶入/)).toBeInTheDocument()
    // 送出前必須先檢查
    expect(screen.getByRole('button', { name: '送出給主管審核' })).toBeDisabled()
  })

  it('依路由 formKey 載入對應表單', async () => {
    renderPage(undefined, 'incident_report')
    await waitFor(() => expect(schemaMock).toHaveBeenCalledWith('incident_report'))
    expect(await screen.findByRole('heading', { name: '報價單' })).toBeInTheDocument()
  })

  it('檢查流程：建檔→計算→驗證，通過後可送出審核', async () => {
    renderPage()
    await screen.findByLabelText(/客戶/)
    await userEvent.type(screen.getByLabelText(/客戶/), '台中精機')
    await userEvent.type(screen.getByLabelText(/料號/), 'P-100')
    await userEvent.type(screen.getByLabelText(/數量/), '200')
    await userEvent.type(screen.getByLabelText(/單價/), '120')
    await userEvent.selectOptions(screen.getByLabelText(/付款條件/), '月結30天')

    await userEvent.click(screen.getByRole('button', { name: /檢查/ }))
    await waitFor(() => expect(createMock).toHaveBeenCalled())
    expect(createMock.mock.calls[0][0]).toBe('quote')
    expect(calculateMock).toHaveBeenCalledWith('inst-1', 1)
    expect(validateMock).toHaveBeenCalledWith('inst-1', 2)
    // 計算結果顯示
    expect(await screen.findByText('總計')).toBeInTheDocument()
    // 數字欄位轉型為 number 送出
    expect(createMock.mock.calls[0][1]).toMatchObject({ quantity: 200, unit_price: 120 })

    const submitBtn = screen.getByRole('button', { name: '送出給主管審核' })
    expect(submitBtn).toBeEnabled()
    await userEvent.click(submitBtn)
    await waitFor(() => expect(submitMock).toHaveBeenCalled())
    expect(await screen.findByText('已送出審核')).toBeInTheDocument()
  })

  it('schema 載入失敗時顯示錯誤態並可重試', async () => {
    schemaMock.mockRejectedValueOnce(new Error('network'))
    renderPage()
    expect(await screen.findByText('無法載入這張表單')).toBeInTheDocument()
    schemaMock.mockResolvedValueOnce(QUOTE_SCHEMA)
    await userEvent.click(screen.getByRole('button', { name: '重試' }))
    expect(await screen.findByLabelText(/客戶/)).toBeInTheDocument()
  })

  it('驗證失敗時逐條列出錯誤且不可送出', async () => {
    validateMock.mockResolvedValue({
      ...INSTANCE,
      record_version: 3,
      validation_result: { valid: false, errors: ['必填欄位缺少或格式非法: 單價'] },
    })
    renderPage()
    await screen.findByLabelText(/客戶/)
    await userEvent.click(screen.getByRole('button', { name: /檢查/ }))
    expect(await screen.findByText(/必填欄位缺少/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '送出給主管審核' })).toBeDisabled()
  })
})
