import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from './api'
import { AuthProvider, useAuth } from './auth'

vi.mock('./api', () => ({
  authApi: {
    me: vi.fn(),
    experience: vi.fn(),
    login: vi.fn(),
    demoLogin: vi.fn(),
  },
}))

function Probe() {
  const auth = useAuth()
  return <div data-testid="state">{`${auth.token ?? 'none'}:${auth.experienceStatus}:${auth.loading}`}</div>
}

describe('AuthProvider bootstrap failures', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('retains the token when users/me fails transiently', async () => {
    localStorage.setItem('token', 'valid-session')
    vi.mocked(authApi.me).mockRejectedValue(
      Object.assign(new Error('gateway unavailable'), {
        isAxiosError: true,
        response: { status: 503 },
      }),
    )

    render(<AuthProvider><Probe /></AuthProvider>)

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('valid-session:error:false'))
    expect(localStorage.getItem('token')).toBe('valid-session')
  })

  it('clears the token when users/me returns unauthorized', async () => {
    localStorage.setItem('token', 'expired-session')
    vi.mocked(authApi.me).mockRejectedValue(
      Object.assign(new Error('unauthorized'), {
        isAxiosError: true,
        response: { status: 401 },
      }),
    )

    render(<AuthProvider><Probe /></AuthProvider>)

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:idle:false'))
    expect(localStorage.getItem('token')).toBeNull()
  })
})
