import CoreAudioRecorder from '../../platform/input/CoreAudioRecorder'
import type { CaptureSessionInfo } from '../../platform/input/captureApi'

/**
 * MKA presentation adapter. Capture lifecycle, offline queue and API ownership
 * live in the core Input platform so disabling MKA does not remove capture.
 */
export default function LongInterviewRecorder({
  title,
  equipmentId,
  disabled,
  captureStatus,
  onQueued,
  onError,
}: {
  title: string
  equipmentId?: string
  disabled?: boolean
  captureStatus?: CaptureSessionInfo['status']
  onQueued: (session: CaptureSessionInfo) => void
  onError?: (message: string) => void
}) {
  return (
    <CoreAudioRecorder
      title={title}
      equipmentId={equipmentId}
      disabled={disabled}
      captureStatus={captureStatus}
      sourceModule="mka"
      purpose="master_interview"
      heading="直接開始訪談"
      onQueued={onQueued}
      onError={onError}
    />
  )
}
