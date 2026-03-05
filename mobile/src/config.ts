/**
 * 伺服器設定
 *
 * 地端部署時修改 API_BASE_URL 為實際伺服器 IP / 域名，例如：
 *   http://192.168.1.100:8000/api/v1
 *   https://enclave.company.com/api/v1
 *
 * 開發階段若使用 Expo Go，不可使用 localhost；
 * 請改用電腦的區域網路 IP（例如 http://192.168.x.x:8000/api/v1）。
 */
export const API_BASE_URL = 'http://192.168.1.100:8000/api/v1'

/** SSE 串流 endpoint（直接使用 fetch，非 axios） */
export const STREAM_BASE_URL = API_BASE_URL.replace('/api/v1', '')
