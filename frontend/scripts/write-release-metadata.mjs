import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const contract = JSON.parse(await readFile(resolve(root, 'release-contract.json'), 'utf8'))
const contractHash = createHash('sha256')
  .update(JSON.stringify(contract.canonical_routes))
  .digest('hex')

const value = (name, fallback = 'unknown') => process.env[name]?.trim() || fallback
const metadata = {
  schema_version: 1,
  release_id: value('VITE_RELEASE_ID', 'dev'),
  source_commit: value('VITE_SOURCE_COMMIT'),
  source_dirty: value('VITE_SOURCE_DIRTY'),
  build_time: value('VITE_BUILD_TIME'),
  deployment_manifest_id: value('VITE_DEPLOYMENT_MANIFEST_ID'),
  schema_head: value('VITE_SCHEMA_HEAD'),
  route_contract_hash: contractHash,
  canonical_routes: contract.canonical_routes,
}

await mkdir(resolve(root, 'dist'), { recursive: true })
await writeFile(
  resolve(root, 'dist', 'release.json'),
  `${JSON.stringify(metadata, null, 2)}\n`,
  'utf8',
)
