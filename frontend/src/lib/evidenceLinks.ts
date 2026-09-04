const ALLOWED_QUERY = new Set(['page', 'section', 't', 'end', 'frame', 'bbox', 'region', 'evidence'])
const EVIDENCE_PATH = /^\/(?:knowledge\/(?:assets|documents|videos|wiki)|knowhow)\/[a-zA-Z0-9._:-]{1,160}$/
const SAFE_ID = /^[a-zA-Z0-9._:-]{1,80}$/
const BBOX = /^-?\d+(?:\.\d+)?(?:,-?\d+(?:\.\d+)?){3}$/

function isSafeText(value: string) {
  return value.length > 0 && value.length <= 160 && [...value].every(character => {
    const code = character.charCodeAt(0)
    return code >= 0x20 && code !== 0x7f
  })
}

export function normalizeEvidenceDeepLink(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null
  try {
    const url = new URL(value, 'https://enclave.invalid')
    if (!EVIDENCE_PATH.test(url.pathname)) return null
    if (url.hash && url.hash !== '#evidence-locator') return null
    for (const key of url.searchParams.keys()) {
      if (!ALLOWED_QUERY.has(key)) return null
    }
    if (url.searchParams.has('t') && !/^\d+$/.test(url.searchParams.get('t') || '')) return null
    if (url.searchParams.has('end') && !/^\d+$/.test(url.searchParams.get('end') || '')) return null
    if (url.searchParams.has('page') && !/^[1-9]\d*$/.test(url.searchParams.get('page') || '')) return null
    if (url.searchParams.has('section') && !isSafeText(url.searchParams.get('section') || '')) return null
    if (url.searchParams.has('frame') && !SAFE_ID.test(url.searchParams.get('frame') || '')) return null
    if (url.searchParams.has('region') && !SAFE_ID.test(url.searchParams.get('region') || '')) return null
    if (url.searchParams.has('bbox') && !BBOX.test(url.searchParams.get('bbox') || '')) return null
    if (url.searchParams.has('evidence') && !SAFE_ID.test(url.searchParams.get('evidence') || '')) return null
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return null
  }
}
