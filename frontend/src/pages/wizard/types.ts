/** Shared types for the Folder Import Wizard sub-components */

export type FileWithPath = File & { webkitRelativePath: string }

export interface AddedFolder {
  id: string
  rootName: string
  files: FileWithPath[]
}

export interface SubfolderRow {
  path: string
  name: string
  depth: number
  fileCount: number
  summary: string
  hasContentSamples: boolean
  expanded: boolean
  selected: boolean
  files: FileWithPath[]
}

export interface SkippedInfo {
  count: number
  exts: string[]
}

export interface ImportResult {
  succeeded: number
  failed: number
  failedFiles: { name: string; reason: string }[]
}

export type WizardStep = 'select' | 'scanning' | 'confirm' | 'importing' | 'done'
