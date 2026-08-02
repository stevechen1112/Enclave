/** Shared keys for first-run readiness (UIUX §9.2) */
export const TEST_ASK_DONE_KEY = 'enclave_test_ask_done'
export const TEST_ASK_DONE_EVENT = 'enclave:test-ask-done'

export function markTestAskDone(): void {
  try {
    localStorage.setItem(TEST_ASK_DONE_KEY, '1')
  } catch {
    /* ignore quota / private mode */
  }
  try {
    window.dispatchEvent(new Event(TEST_ASK_DONE_EVENT))
  } catch {
    /* ignore */
  }
}

export function isTestAskDone(): boolean {
  try {
    return localStorage.getItem(TEST_ASK_DONE_KEY) === '1'
  } catch {
    return false
  }
}
